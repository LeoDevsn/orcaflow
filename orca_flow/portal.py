"""Compartilhamento por capacidade: cada token acessa somente uma proposta fixa."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from datetime import date, timedelta
from pathlib import Path

from .core import TERMINAL, line_total, now, text

ACTIONS = {"approve": ("Aprovado", "Aprovação"), "decline": ("Recusado", "Recusa"),
           "changes": ("Negociação", "Pedido de ajustes")}


class PortalError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def rotate_generation(directory: Path):
    path = directory / ".portal-generation"
    temporary = directory / f".portal-generation-{uuid.uuid4().hex}.tmp"
    with temporary.open("x", encoding="ascii") as stream:
        stream.write(secrets.token_hex(32))
    temporary.replace(path)


class Portal:
    def __init__(self, store):
        self.store = store
        path = store.directory / ".portal-generation"
        try:
            with path.open("x", encoding="ascii") as stream:
                stream.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS proposal_links (
                    id TEXT PRIMARY KEY, quote_id INTEGER NOT NULL REFERENCES quotes(id),
                    token_hash TEXT NOT NULL UNIQUE, generation TEXT NOT NULL,
                    snapshot TEXT NOT NULL, created TEXT NOT NULL, expires TEXT NOT NULL,
                    revoked TEXT, first_viewed TEXT, views INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS proposal_links_quote ON proposal_links(quote_id);
                CREATE TABLE IF NOT EXISTS proposal_replies (
                    id INTEGER PRIMARY KEY, link_id TEXT NOT NULL UNIQUE REFERENCES proposal_links(id),
                    action TEXT NOT NULL CHECK(action IN ('approve','decline','changes')),
                    name TEXT NOT NULL, message TEXT NOT NULL, created TEXT NOT NULL
                );
            """)

    def generation(self):
        return (self.store.directory / ".portal-generation").read_text(encoding="ascii")

    @staticmethod
    def token_hash(token):
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise PortalError("Este link não está disponível. Peça um novo link ao responsável pela proposta.", 404)
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def _find(self, db, token):
        row = db.execute("SELECT * FROM proposal_links WHERE token_hash=?", (self.token_hash(token),)).fetchone()
        if not row:
            raise PortalError("Este link não está disponível. Peça um novo link ao responsável pela proposta.", 404)
        if row["revoked"] or row["generation"] != self.generation():
            raise PortalError("Este link foi encerrado. Peça a versão atual da proposta ao responsável.", 410)
        if row["expires"] < date.today().isoformat():
            raise PortalError("A validade desta proposta terminou. Fale com o responsável para receber uma nova versão.", 410)
        return row

    def create(self, quote_id):
        raw = secrets.token_urlsafe(32)
        link_id, timestamp = uuid.uuid4().hex, now()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            quote = self.store._quote_from_db(db, quote_id)
            if quote["stage"] in {"Recusado", "Arquivado"}:
                raise PortalError("Esta negociação já foi encerrada. Duplique a proposta para preparar uma nova versão.")
            if quote["expires"] < date.today().isoformat() and quote["stage"] != "Aprovado":
                raise PortalError("A proposta está vencida. Duplique o orçamento e atualize a validade antes de compartilhar.")
            business = dict(db.execute("SELECT key,value FROM settings"))
            from .documents import business_identity
            snapshot = {"number": quote["number"], "title": quote["title"], "expires": quote["expires"],
                        "customer": {k: quote["customer"][k] for k in ("name", "company")},
                        "business": business_identity(business),
                        "items": [{"description": i["description"], "quantity": i["qty_milli"],
                                   "unit_cents": i["unit_cents"], "total": line_total(i["qty_milli"], i["unit_cents"])} for i in quote["items"]],
                        "subtotal": quote["subtotal"], "discount_cents": quote["discount_cents"],
                        "total": quote["total"], "notes": quote["notes"]}
            # Um novo link substitui o anterior, sem apagar seu histórico.
            db.execute("UPDATE proposal_links SET revoked=? WHERE quote_id=? AND revoked IS NULL", (timestamp, quote_id))
            db.execute("INSERT INTO proposal_links(id,quote_id,token_hash,generation,snapshot,created,expires) VALUES(?,?,?,?,?,?,?)",
                       (link_id, quote_id, self.token_hash(raw), self.generation(), json.dumps(snapshot, ensure_ascii=False), timestamp, (date.today() + timedelta(days=90)).isoformat()))
            if quote["stage"] == "Rascunho":
                self.store._set_stage(db, quote_id, "Enviado")
            db.execute("INSERT INTO events(quote_id,description,created) VALUES(?,?,?)", (quote_id, "Link da proposta gerado para compartilhar", timestamp))
        return {"id": link_id, "token": raw, "expires": (date.today() + timedelta(days=90)).isoformat()}

    def view(self, token, track=True):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._find(db, token)
            quote = db.execute("SELECT stage FROM quotes WHERE id=?", (row["quote_id"],)).fetchone()
            reply = db.execute("SELECT action,name,message,created FROM proposal_replies WHERE link_id=?", (row["id"],)).fetchone()
            snapshot = json.loads(row["snapshot"])
            expired = snapshot["expires"] < date.today().isoformat()
            if track:
                db.execute("UPDATE proposal_links SET first_viewed=COALESCE(first_viewed,?),views=views+1 WHERE id=?", (now(), row["id"]))
            return {"proposal": snapshot, "reply": dict(reply) if reply else None,
                    "can_respond": not reply and quote["stage"] not in TERMINAL and not expired, "proposal_expired": expired,
                    "closed": quote["stage"] in {"Recusado", "Arquivado"} and not reply,
                    "approved": quote["stage"] == "Aprovado", "conversation_open": quote["stage"] != "Arquivado", "quote_id": row["quote_id"]}

    def respond(self, token, action, name, message="", confirmed=False):
        if action not in ACTIONS:
            raise PortalError("Escolha aprovar, recusar ou pedir ajustes.")
        name = text(name, "seu nome", True, 150)
        message = text(message, "mensagem", required=action == "changes", limit=4000)
        if confirmed is not True:
            raise PortalError("Confirme que deseja enviar esta resposta ao responsável pela proposta.")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._find(db, token)
            old = db.execute("SELECT action,name,message,created FROM proposal_replies WHERE link_id=?", (row["id"],)).fetchone()
            if old:
                if (old["action"], old["name"], old["message"]) == (action, name, message):
                    return {"reply": dict(old), "duplicate": True}
                raise PortalError("Já recebemos uma resposta para esta versão. Fale com o responsável para continuar a conversa.", 409)
            if json.loads(row["snapshot"])["expires"] < date.today().isoformat():
                raise PortalError("O prazo para responder esta proposta terminou. Peça uma nova versão ao responsável.", 410)
            quote = db.execute("SELECT stage,title FROM quotes WHERE id=?", (row["quote_id"],)).fetchone()
            if quote["stage"] in TERMINAL:
                raise PortalError("Esta negociação foi encerrada. Fale com o responsável antes de responder.", 409)
            timestamp = now()
            db.execute("INSERT INTO proposal_replies(link_id,action,name,message,created) VALUES(?,?,?,?,?)", (row["id"], action, name, message, timestamp))
            self.store._set_stage(db, row["quote_id"], ACTIONS[action][0])
            db.execute("INSERT INTO events(quote_id,description,created) VALUES(?,?,?)",
                       (row["quote_id"], f"{ACTIONS[action][1]} pelo portal · nome informado: {name}" + (f" · {message}" if message else ""), timestamp))
            if action == "changes":
                db.execute("INSERT INTO tasks(quote_id,title,due,created) VALUES(?,?,?,?)",
                           (row["quote_id"], f"Revisar ajustes solicitados: {quote['title']}", date.today().isoformat(), timestamp))
        return {"reply": {"action": action, "name": name, "message": message, "created": timestamp}, "duplicate": False}

    def revoke(self, quote_id, link_id):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id,revoked FROM proposal_links WHERE id=? AND quote_id=?", (link_id, quote_id)).fetchone()
            if not row:
                raise PortalError("Link não encontrado.", 404)
            if not row["revoked"]:
                timestamp = now()
                db.execute("UPDATE proposal_links SET revoked=? WHERE id=?", (timestamp, link_id))
                db.execute("INSERT INTO events(quote_id,description,created) VALUES(?,?,?)", (quote_id, "Acesso à proposta pelo link encerrado", timestamp))

    def summaries(self):
        generation, result = self.generation(), {}
        with self.store.connect() as db:
            rows = db.execute("""SELECT l.id,l.quote_id,l.generation,l.created,l.expires,l.revoked,l.first_viewed,l.views,
                r.action,r.name,r.message,r.created AS replied
                FROM proposal_links l LEFT JOIN proposal_replies r ON r.link_id=l.id ORDER BY l.created DESC""").fetchall()
        for row in rows:
            status = "responded" if row["action"] else "active"
            if row["expires"] < date.today().isoformat():
                status = "expired"
            if row["revoked"] or row["generation"] != generation:
                status = "revoked"
            item = {key: row[key] for key in ("id", "created", "expires", "first_viewed", "views")}
            item["state"] = status
            item["reply"] = {"action": row["action"], "name": row["name"], "message": row["message"], "created": row["replied"]} if row["action"] else None
            result.setdefault(str(row["quote_id"]), []).append(item)
        return result
