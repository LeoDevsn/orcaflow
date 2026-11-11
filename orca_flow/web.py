"""API e servidor da aplicação web. Os dados de negócio continuam no Store existente."""

from __future__ import annotations

import io
import logging
import secrets
import sqlite3
import tempfile
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta
from pathlib import Path

from flask import Flask, jsonify, request, send_file, session
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

from . import __version__
from .core import Store, seed_demo


class Identity:
    """Login separado do banco de negócio, inclusive ao restaurar backups antigos."""
    def __init__(self, directory: Path):
        self.path = directory / "acesso.sqlite3"
        self.lock = threading.Lock()
        db = sqlite3.connect(self.path)
        try:
            with db:
                db.execute("CREATE TABLE IF NOT EXISTS owner(id INTEGER PRIMARY KEY CHECK(id=1), name TEXT NOT NULL, password TEXT NOT NULL, epoch TEXT NOT NULL)")
        finally:
            db.close()

    def get(self):
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("SELECT name,password,epoch FROM owner WHERE id=1").fetchone()
            return {"name": row[0], "password": row[1], "epoch": row[2]} if row else None
        finally:
            db.close()

    def setup(self, name, password):
        name = str(name).strip()
        if not name or len(name) > 100:
            raise ValueError("Informe seu nome, com até 100 caracteres.")
        self.validate_password(password)
        with self.lock:
            if self.get():
                raise ValueError("O acesso já foi configurado. Entre com sua senha.")
            db = sqlite3.connect(self.path)
            try:
                with db:
                    db.execute("INSERT INTO owner VALUES(1,?,?,?)", (name, generate_password_hash(password, method="scrypt"), secrets.token_hex(16)))
            finally:
                db.close()

    @staticmethod
    def validate_password(password):
        if not isinstance(password, str) or not 10 <= len(password) <= 200:
            raise ValueError("Crie uma senha com pelo menos 10 caracteres e no máximo 200.")

    def change_password(self, old, new):
        self.validate_password(new)
        with self.lock:
            owner = self.get()
            if not owner or not check_password_hash(owner["password"], old):
                raise ValueError("A senha atual não confere.")
            db = sqlite3.connect(self.path)
            try:
                with db:
                    db.execute("UPDATE owner SET password=?,epoch=? WHERE id=1", (generate_password_hash(new, method="scrypt"), secrets.token_hex(16)))
            finally:
                db.close()

    def reset_password(self, new):
        """Somente para o comando local do administrador, não é exposto pela API."""
        self.validate_password(new)
        if not self.get():
            raise ValueError("Configure o primeiro acesso antes de redefinir a senha.")
        db = sqlite3.connect(self.path)
        try:
            with db:
                db.execute("UPDATE owner SET password=?,epoch=? WHERE id=1", (generate_password_hash(new, method="scrypt"), secrets.token_hex(16)))
        finally:
            db.close()


def create_app(directory=None, testing=False, https=False, trusted_hosts=None):
    static = Path(__file__).with_name("frontend")
    app = Flask(__name__, static_folder=str(static), static_url_path="/static")
    real_store = Store(directory)
    identity = Identity(real_store.directory)
    secret_path = real_store.directory / ".server-key"
    try:
        with secret_path.open("xb") as stream:
            stream.write(secrets.token_bytes(48))
    except FileExistsError:
        pass
    app.config.update(SECRET_KEY=secret_path.read_bytes(), TESTING=testing, MAX_CONTENT_LENGTH=12 * 1024 * 1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict", SESSION_COOKIE_SECURE=https,
                      SESSION_COOKIE_NAME="orcaflow_session", PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
                      TRUSTED_HOSTS=trusted_hosts or ["localhost", "127.0.0.1", "[::1]"])
    app.extensions["orca_store"] = real_store
    app.extensions["orca_identity"] = identity
    demos = {}
    demo_lock = threading.Lock()
    failures = defaultdict(deque)
    failures_lock = threading.Lock()

    def owner_session():
        owner = identity.get()
        return bool(owner and session.get("owner_epoch") == owner["epoch"])

    def active_store():
        demo_id = session.get("demo")
        if demo_id:
            with demo_lock:
                if demo_id in demos:
                    demos[demo_id][1] = time.monotonic()
                    return demos[demo_id][0]
        if not owner_session():
            raise PermissionError("Entre na sua conta para continuar.")
        return real_store

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError("Não foi possível ler os dados. Confira os campos e tente novamente.")
        return data

    def authenticate():
        session["owner_epoch"] = identity.get()["epoch"]
        session.permanent = True

    @app.before_request
    def protect():
        if request.path.startswith("/api/"):
            if request.remote_addr not in {"127.0.0.1", "::1", None} and not request.is_secure and not testing:
                return jsonify(error="Este acesso precisa de uma conexão HTTPS. Consulte o responsável pelo servidor."), 403
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                supplied = request.headers.get("X-CSRF-Token", "")
                if not secrets.compare_digest(supplied, session.get("csrf", secrets.token_urlsafe(32))):
                    return jsonify(error="Sua sessão foi atualizada. Recarregue a página e tente novamente."), 403

    @app.after_request
    def headers(response):
        response.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                                 "Referrer-Policy": "same-origin", "Cache-Control": "no-store",
                                 "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                                 "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    @app.errorhandler(Exception)
    def error_handler(error):
        if isinstance(error, PermissionError):
            return jsonify(error=str(error)), 401
        if isinstance(error, (ValueError, KeyError, TypeError)):
            message = str(error) if isinstance(error, ValueError) else "Confira os campos obrigatórios e tente novamente."
            return jsonify(error=message), 400
        if isinstance(error, HTTPException):
            messages = {404: "Este endereço não foi encontrado.", 413: "O arquivo é muito grande. O limite é 12 MB.",
                        405: "Esta ação não está disponível neste endereço."}
            return jsonify(error=messages.get(error.code, "Não foi possível concluir a solicitação.")), error.code
        logging.getLogger("orcaflow").exception("Erro ao atender uma solicitação")
        return jsonify(error="Não foi possível salvar agora. Tente novamente. Seus dados já gravados foram preservados."), 500

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/health")
    def health():
        return jsonify(status="ok", app="orcaflow", version=__version__)

    @app.get("/api/session")
    def bootstrap():
        session.setdefault("csrf", secrets.token_urlsafe(32))
        owner = identity.get()
        return jsonify(configured=bool(owner), authenticated=owner_session(), demo=bool(session.get("demo") in demos),
                       csrf=session["csrf"], name=owner["name"] if owner_session() else "", version=__version__)

    @app.post("/api/setup")
    def setup():
        if request.remote_addr not in {"127.0.0.1", "::1", None}:
            return jsonify(error="O primeiro acesso deve ser configurado no computador do servidor."), 403
        data = body()
        identity.setup(data.get("name", ""), data.get("password", ""))
        authenticate()
        return jsonify(ok=True)

    @app.post("/api/login")
    def login():
        data = body()
        ip = request.remote_addr or "local"
        with failures_lock:
            attempts = failures[ip]
            cutoff = time.monotonic() - 900
            while attempts and attempts[0] < cutoff:
                attempts.popleft()
            if len(attempts) >= 10:
                return jsonify(error="Muitas tentativas. Aguarde 15 minutos antes de tentar novamente."), 429
        owner = identity.get()
        password = data.get("password", "")
        if not isinstance(password, str) or len(password) > 200 or not owner or not check_password_hash(owner["password"], password):
            with failures_lock:
                failures[ip].append(time.monotonic())
            return jsonify(error="A senha não confere. Tente novamente."), 401
        with failures_lock:
            failures.pop(ip, None)
        session.pop("demo", None)
        authenticate()
        return jsonify(ok=True)

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.post("/api/password")
    def password():
        if not owner_session() or session.get("demo"):
            raise PermissionError("Entre nos seus dados para alterar a senha.")
        data = body()
        identity.change_password(data.get("current", ""), data.get("password", ""))
        authenticate()
        return jsonify(ok=True)

    @app.post("/api/demo")
    def demo():
        with demo_lock:
            # As pastas pertencem ao aplicativo e não contêm dados reais.
            for key, value in list(demos.items()):
                if time.monotonic() - value[1] > 12 * 3600:
                    value[2].cleanup()
                    demos.pop(key)
            if len(demos) >= 25:
                return jsonify(error="A demonstração está ocupada. Tente novamente mais tarde."), 429
            temporary = tempfile.TemporaryDirectory(prefix="OrcaFlow-demo-")
            store = Store(temporary.name)
            seed_demo(store)
            key = secrets.token_urlsafe(24)
            demos[key] = [store, time.monotonic(), temporary]
            session["demo"] = key
        return jsonify(ok=True)

    @app.post("/api/demo/exit")
    def demo_exit():
        key = session.pop("demo", None)
        with demo_lock:
            value = demos.pop(key, None)
            if value:
                value[2].cleanup()
        return jsonify(ok=True)

    @app.get("/api/data")
    def data():
        store = active_store()
        return jsonify(customers=store.customers(), quotes=store.quotes(), tasks=store.tasks(),
                       dashboard=store.dashboard(), settings=store.settings(),
                       recovery_available=any(store.directory.glob("antes-restauracao-*.sqlite3")))

    @app.post("/api/customers")
    def save_customer():
        data = body()
        customer_id = active_store().save_customer(**{key: data[key] for key in ("name", "company", "email", "phone", "notes", "customer_id") if key in data})
        return jsonify(id=customer_id)

    @app.post("/api/quotes")
    def save_quote():
        data = body()
        quote_id = active_store().save_quote(**{key: data[key] for key in ("customer_id", "title", "expires", "items", "discount", "notes", "quote_id", "expected_updated") if key in data})
        return jsonify(id=quote_id)

    @app.post("/api/quotes/<int:quote_id>/stage")
    def stage(quote_id):
        active_store().set_stage(quote_id, body().get("stage"))
        return jsonify(ok=True)

    @app.post("/api/quotes/<int:quote_id>/duplicate")
    def duplicate(quote_id):
        return jsonify(id=active_store().duplicate_quote(quote_id))

    @app.get("/api/quotes/<int:quote_id>/message")
    def message(quote_id):
        return jsonify(message=active_store().message(quote_id))

    @app.post("/api/tasks")
    def task():
        data = body()
        return jsonify(id=active_store().add_task(data.get("title", ""), data.get("due", ""), data.get("quote_id")))

    @app.post("/api/tasks/<int:task_id>/complete")
    def complete(task_id):
        active_store().complete_task(task_id)
        return jsonify(ok=True)

    @app.post("/api/settings")
    def settings():
        data = body()
        active_store().save_settings(**{key: data[key] for key in ("company", "email", "phone", "footer") if key in data})
        return jsonify(ok=True)

    def download(kind, quote_id=None):
        store = active_store()
        with tempfile.TemporaryDirectory(prefix="OrcaFlow-export-") as temporary:
            target = Path(temporary) / {"csv": "orcamentos.csv", "backup": "backup-orcaflow.sqlite3", "proposal": "proposta.html"}[kind]
            if kind == "csv":
                store.export_quotes(target)
            elif kind == "backup":
                store.backup(target)
            else:
                store.export_proposal(quote_id, target)
            content = target.read_bytes()
        return send_file(io.BytesIO(content), as_attachment=True, download_name=target.name,
                         mimetype={"csv": "text/csv", "backup": "application/octet-stream", "proposal": "text/html"}[kind])

    @app.get("/api/export/quotes")
    def export_quotes():
        return download("csv")

    @app.get("/api/export/backup")
    def backup():
        return download("backup")

    @app.get("/api/export/recovery")
    def recovery():
        store = active_store()
        files = sorted((p for p in store.directory.glob("antes-restauracao-*.sqlite3") if p.is_file() and not p.is_symlink()),
                       key=lambda p: p.stat().st_mtime_ns, reverse=True)
        if not files:
            raise ValueError("Nenhuma cópia anterior foi criada ainda.")
        return send_file(io.BytesIO(files[0].read_bytes()), as_attachment=True,
                         download_name="copia-anterior-orcaflow.sqlite3", mimetype="application/octet-stream")

    @app.get("/api/template/customers")
    def customer_template():
        active_store()
        content = "nome;empresa;email;telefone;observacoes\r\nCliente Exemplo;Empresa Exemplo;cliente@example.com;;Substitua esta linha pelos seus dados\r\n"
        return send_file(io.BytesIO(content.encode("utf-8-sig")), as_attachment=True,
                         download_name="modelo-clientes.csv", mimetype="text/csv")

    @app.get("/api/quotes/<int:quote_id>/proposal")
    def proposal(quote_id):
        return download("proposal", quote_id)

    def upload(operation, suffix):
        store = active_store()
        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename:
            raise ValueError("Escolha um arquivo para continuar.")
        with tempfile.TemporaryDirectory(prefix="OrcaFlow-import-") as temporary:
            path = Path(temporary) / ("upload" + suffix)
            uploaded.save(path)
            return operation(store, path)

    @app.post("/api/import/customers")
    def import_customers():
        return jsonify(upload(lambda store, path: store.import_customers(path), ".csv"))

    @app.post("/api/import/backup")
    def restore():
        safety = upload(lambda store, path: store.restore(path), ".sqlite3")
        return jsonify(ok=True, safety=safety.name)

    return app
