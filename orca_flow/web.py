"""API e servidor da aplicação web. Os dados de negócio continuam no Store existente."""

from __future__ import annotations

import io
import logging
import os
import secrets
import sqlite3
import tempfile
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, request, send_file, session
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

from . import __version__
from .core import Store, seed_demo
from .portal import Portal, PortalError
from .payments import PaymentConfig, Payments, public_origin
from .documents import Workspace


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


def create_app(directory=None, testing=False, https=False, trusted_hosts=None, public_url=None):
    static = Path(__file__).with_name("frontend")
    app = Flask(__name__, static_folder=str(static), static_url_path="/static")
    real_store = Store(directory)
    identity = Identity(real_store.directory)
    real_portal = Portal(real_store)
    payment_config = PaymentConfig(real_store.directory)
    real_payments = Payments(real_store, payment_config)
    real_workspace = Workspace(real_store)
    portal_lock = threading.RLock()
    configured_origin = public_url or os.environ.get("ORCAFLOW_PUBLIC_URL", "")
    if configured_origin:
        configured_origin = public_origin(configured_origin)
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
    app.extensions["orca_portal"] = real_portal
    app.extensions["orca_payments"] = real_payments
    app.extensions["orca_payment_config"] = payment_config
    for extra_origin in (configured_origin, payment_config.status().get("public_url"), real_store.settings().get("portal_public_url")):
        if extra_origin:
            hostname = urlparse(extra_origin).hostname
            if hostname and hostname not in app.config["TRUSTED_HOSTS"]:
                app.config["TRUSTED_HOSTS"].append(hostname)
    demos = {}
    demo_lock = threading.Lock()
    failures = defaultdict(deque)
    failures_lock = threading.Lock()
    payment_checks = {}

    def active_portal():
        store = active_store()
        if store is real_store:
            return real_portal
        return demos[session["demo"]][3]

    def active_workspace():
        return real_workspace if active_store() is real_store else demos[session["demo"]][4]

    def locate_public(token):
        if "." not in token:
            return real_portal, real_payments, real_workspace, token, False
        scope, raw = token.split(".", 1)
        if not scope.startswith("demo-"):
            raise PortalError("Este link não está disponível.", 404)
        with demo_lock:
            value = demos.get(scope[5:])
            if not value:
                raise PortalError("Esta demonstração foi encerrada. Peça um novo link ao responsável.", 410)
            return value[3], None, value[4], raw, True

    def origin():
        return configured_origin or active_store().settings().get("portal_public_url") or payment_config.status().get("public_url") or request.host_url.rstrip("/")

    def external_ready():
        return bool(configured_origin or active_store().settings().get("portal_public_url") or payment_config.status().get("public_url"))

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
            if request.method not in {"GET", "HEAD", "OPTIONS"} and request.path != "/api/payments/webhook":
                supplied = request.headers.get("X-CSRF-Token", "")
                if not secrets.compare_digest(supplied, session.get("csrf", secrets.token_urlsafe(32))):
                    return jsonify(error="Sua sessão foi atualizada. Recarregue a página e tente novamente."), 403

    @app.after_request
    def headers(response):
        response.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                                 "Referrer-Policy": "same-origin", "Cache-Control": "no-store",
                                 "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                                 "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        if request.path.startswith(("/p/", "/api/public/")) or request.path == "/pagamento/retorno":
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return response

    @app.errorhandler(Exception)
    def error_handler(error):
        if isinstance(error, PortalError):
            return jsonify(error=str(error)), error.status
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

    @app.get("/p/<token>")
    @app.get("/pagamento/retorno")
    def public_page(token=None):
        return app.send_static_file("portal.html")

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
            demos[key] = [store, time.monotonic(), temporary, Portal(store), Workspace(store)]
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
                       recovery_available=any(store.directory.glob("antes-restauracao-*.sqlite3")),
                       sharing=active_portal().summaries(), payments=real_payments.summaries() if store is real_store else {},
                       portal_origin=origin() if external_ready() else "",
                       unread_messages=active_workspace().unread(),
                       payment_config=payment_config.status() if store is real_store else {"configured": False, "enabled": False, "mode": "sandbox", "public_url": "", "account": ""})

    @app.post("/api/quotes/<int:quote_id>/share")
    def share(quote_id):
        with portal_lock:
            created = active_portal().create(quote_id)
            token = ("demo-" + session["demo"] + "." if session.get("demo") else "") + created.pop("token")
            return jsonify(**created, url=origin() + "/p/" + token,
                           external_ready=external_ready(),
                           demo=bool(session.get("demo")))

    @app.post("/api/quotes/<int:quote_id>/share/<link_id>/revoke")
    def revoke(quote_id, link_id):
        with portal_lock:
            active_portal().revoke(quote_id, link_id)
        return jsonify(ok=True)

    @app.get("/api/public/proposals/<token>")
    def public_proposal(token):
        with portal_lock:
            portal, payments, workspace, raw, is_demo = locate_public(token)
            result = portal.view(raw)
            quote_id = result.pop("quote_id")
            result["payment"] = payments.summary(quote_id) if payments else {"state": "not_started", "label": "Demonstração sem pagamentos", "test": True}
            result["payments_available"] = bool(payments and payment_config.status()["enabled"] and result["approved"] and not result["closed"])
            session.setdefault("csrf", secrets.token_urlsafe(32))
            return jsonify(**result, demo=is_demo, csrf=session["csrf"], messages=workspace.messages(quote_id), fiscal=workspace.fiscal(quote_id))

    @app.post("/api/public/proposals/<token>/reply")
    def public_reply(token):
        values = body()
        with portal_lock:
            portal, _, _, raw, _ = locate_public(token)
            result = portal.respond(raw, values.get("action"), values.get("name", ""), values.get("message", ""), values.get("confirmed"))
        return jsonify(**result)

    @app.post("/api/public/proposals/<token>/checkout")
    def public_checkout(token):
        with portal_lock:
            portal, payments, _, raw, _ = locate_public(token)
            if not payments:
                raise PortalError("A demonstração não realiza pagamentos.", 409)
            result = portal.view(raw, track=False)
            return jsonify(**payments.checkout(result["quote_id"], result["proposal"], result["approved"] and not result["closed"]))

    @app.get("/api/public/proposals/<token>/payment")
    def public_payment_status(token):
        with portal_lock:
            portal, payments, _, raw, _ = locate_public(token)
            result = portal.view(raw, track=False)
            return jsonify(**(payments.summary(result["quote_id"]) if payments else {"state": "not_started", "test": True}))

    def refresh_payment(payments, quote_id):
        last = payment_checks.get(quote_id, 0)
        if time.monotonic() - last < 10:
            return payments.summary(quote_id)
        payment_checks[quote_id] = time.monotonic()
        return payments.refresh(quote_id)

    @app.post("/api/public/proposals/<token>/payment/refresh")
    def client_refresh_payment(token):
        with portal_lock:
            portal, payments, _, raw, _ = locate_public(token)
            result = portal.view(raw, track=False)
            if not payments:
                raise PortalError("A demonstração não realiza pagamentos.", 409)
            return jsonify(**refresh_payment(payments, result["quote_id"]))

    @app.post("/api/quotes/<int:quote_id>/payment/refresh")
    def owner_refresh_payment(quote_id):
        if active_store() is not real_store:
            raise PortalError("A demonstração não realiza pagamentos.", 409)
        with portal_lock:
            return jsonify(**refresh_payment(real_payments, quote_id))

    @app.post("/api/public/proposals/<token>/messages")
    def client_message(token):
        values = body()
        with portal_lock:
            portal, _, workspace, raw, _ = locate_public(token)
            result = portal.view(raw, track=False)
            return jsonify(**workspace.send(result["quote_id"], "client", values.get("name"), values.get("body"), values.get("kind", "message"), values.get("nonce")))

    @app.get("/api/public/proposals/<token>/workspace")
    def client_workspace(token):
        with portal_lock:
            portal, payments, workspace, raw, _ = locate_public(token)
            result = portal.view(raw, track=False)
            quote_id = result["quote_id"]
            return jsonify(messages=workspace.messages(quote_id), fiscal=workspace.fiscal(quote_id),
                           payment=payments.summary(quote_id) if payments else {"state": "not_started", "test": True})

    @app.post("/api/public/proposals/<token>/fiscal")
    def client_fiscal(token):
        with portal_lock:
            portal, _, workspace, raw, _ = locate_public(token)
            result = portal.view(raw, track=False)
            workspace.request_invoice(result["quote_id"], body())
        return jsonify(ok=True)

    def document_download(workspace, quote_id, document_id):
        content, mime = workspace.download(quote_id, document_id)
        return send_file(io.BytesIO(content), as_attachment=True, mimetype=mime,
                         download_name=f"nota-{document_id[:12]}." + ("pdf" if mime == "application/pdf" else "xml"))

    @app.get("/api/public/proposals/<token>/fiscal/<document_id>")
    def client_document(token, document_id):
        with portal_lock:
            portal, _, workspace, raw, _ = locate_public(token)
            result = portal.view(raw, track=False)
            return document_download(workspace, result["quote_id"], document_id)

    @app.get("/api/quotes/<int:quote_id>/workspace")
    def owner_workspace(quote_id):
        active_store().quote(quote_id)
        active_workspace().mark_seen(quote_id)
        return jsonify(messages=active_workspace().messages(quote_id), fiscal=active_workspace().fiscal(quote_id, private=True))

    @app.post("/api/quotes/<int:quote_id>/messages")
    def owner_message(quote_id):
        values = body()
        store = active_store()
        return jsonify(**active_workspace().send(quote_id, "owner", store.settings().get("company") or "Responsável", values.get("body"), "message", values.get("nonce")))

    @app.post("/api/quotes/<int:quote_id>/requests/<int:message_id>/resolve")
    def resolve_request(quote_id, message_id):
        active_workspace().resolve(quote_id, message_id)
        return jsonify(ok=True)

    @app.post("/api/quotes/<int:quote_id>/fiscal")
    def attach_fiscal(quote_id):
        workspace = active_workspace()
        uploaded = request.files.get("file")
        if not uploaded or request.form.get("issued") != "yes":
            raise ValueError("Escolha a nota já emitida e confirme que ela corresponde a esta proposta.")
        return jsonify(**workspace.attach_invoice(quote_id, request.form.get("number"), uploaded.read(8 * 1024 * 1024 + 1), Path(uploaded.filename or "").suffix.lower()))

    @app.get("/api/quotes/<int:quote_id>/fiscal/<document_id>")
    def owner_document(quote_id, document_id):
        return document_download(active_workspace(), quote_id, document_id)

    @app.post("/api/portal-config")
    def portal_config():
        if not owner_session() or session.get("demo"):
            raise PermissionError("Entre nos seus dados para configurar o endereço público.")
        store = active_store()
        value = body().get("public_url", "")
        value = public_origin(value) if value else ""
        with store.connect() as db:
            db.execute("INSERT INTO settings(key,value) VALUES('portal_public_url',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (value,))
        if value:
            hostname = urlparse(value).hostname
            if hostname not in app.config["TRUSTED_HOSTS"]:
                app.config["TRUSTED_HOSTS"].append(hostname)
        return jsonify(ok=True)

    @app.post("/api/payment-config")
    def configure_payments():
        if not owner_session() or session.get("demo"):
            raise PermissionError("Entre nos seus dados para configurar os recebimentos.")
        with portal_lock:
            status = payment_config.configure(body())
            hostname = urlparse(status["public_url"]).hostname
            if hostname not in app.config["TRUSTED_HOSTS"]:
                app.config["TRUSTED_HOSTS"].append(hostname)
        return jsonify(**status)

    @app.post("/api/payment-config/disable")
    def disable_payments():
        if not owner_session() or session.get("demo"):
            raise PermissionError("Entre nos seus dados para configurar os recebimentos.")
        config = payment_config.read()
        config["enabled"] = False
        payment_config.write(config)
        return jsonify(ok=True)

    @app.post("/api/payments/webhook")
    def payment_webhook():
        payment_id = request.args.get("data.id", "")
        with portal_lock:
            return jsonify(**real_payments.webhook(payment_id, request.headers.get("x-request-id", ""), request.headers.get("x-signature", "")))

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
        active_store().save_settings(**{key: data[key] for key in ("company", "email", "phone", "footer", "entity_type", "legal_name", "document", "document_visibility") if key in data})
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
        with portal_lock:
            safety = upload(lambda store, path: store.restore(path), ".sqlite3")
            Portal(active_store())
            Workspace(active_store())
            if active_store() is real_store:
                real_payments.ensure_schema()
        return jsonify(ok=True, safety=safety.name)

    return app
