"""Identificação do prestador e dados pedidos para emissão fiscal externa."""
import json
import re
import uuid

from .core import now, text
from .portal import PortalError


def document(value, entity):
    value = re.sub(r"[.\-/\s]", "", str(value or "")).upper()
    if not value:
        return ""
    if entity == "PF":
        valid = bool(re.fullmatch(r"\d{11}", value)) and len(set(value)) > 1
        for length in (9, 10):
            if not valid:
                break
            remainder = sum(int(value[i]) * (length + 1 - i) for i in range(length)) % 11
            valid = int(value[length]) == (0 if remainder < 2 else 11 - remainder)
    elif entity == "PJ":
        valid = bool(re.fullmatch(r"[A-Z0-9]{12}\d{2}", value)) and len(set(value)) > 1
        for length, weights in ((12, (5,4,3,2,9,8,7,6,5,4,3,2)), (13, (6,5,4,3,2,9,8,7,6,5,4,3,2))):
            if not valid:
                break
            remainder = sum((ord(value[i])-48) * weights[i] for i in range(length)) % 11
            valid = int(value[length]) == (0 if remainder < 2 else 11 - remainder)
    else:
        raise ValueError("Escolha pessoa física ou empresa.")
    if not valid:
        raise ValueError("Confira o CPF informado." if entity == "PF" else "Confira o CNPJ informado; letras também são aceitas nas primeiras 12 posições.")
    return value


def format_document(value):
    if len(value) == 11:
        return f"{value[:3]}.{value[3:6]}.{value[6:9]}-{value[9:]}"
    if len(value) == 14:
        return f"{value[:2]}.{value[2:5]}.{value[5:8]}/{value[8:12]}-{value[12:]}"
    return ""


def mask_document(value):
    if len(value) == 11:
        return "***.***.***-" + value[-2:]
    return value[:2] + ".***.***/****-" + value[-2:] if len(value) == 14 else ""


def business_identity(settings):
    entity = settings.get("entity_type", "")
    raw = settings.get("document", "")
    visible = format_document(raw) if entity == "PJ" or settings.get("document_visibility") == "full" else mask_document(raw)
    return {"company": settings.get("company", ""), "legal_name": settings.get("legal_name", ""),
            "document_label": "CNPJ" if entity == "PJ" else "CPF" if raw else "", "document": visible,
            "email": settings.get("email", ""), "phone": settings.get("phone", ""), "footer": settings.get("footer", "")}


class Workspace:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS quote_messages (
                    id INTEGER PRIMARY KEY, quote_id INTEGER NOT NULL REFERENCES quotes(id),
                    role TEXT NOT NULL CHECK(role IN ('owner','client')), name TEXT NOT NULL,
                    body TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('message','request')),
                    state TEXT NOT NULL DEFAULT 'open', task_id INTEGER REFERENCES tasks(id),
                    nonce TEXT NOT NULL, created TEXT NOT NULL, seen TEXT, UNIQUE(quote_id,role,nonce)
                );
                CREATE TABLE IF NOT EXISTS fiscal_requests (
                    quote_id INTEGER PRIMARY KEY REFERENCES quotes(id), data TEXT NOT NULL,
                    created TEXT NOT NULL, updated TEXT NOT NULL, task_id INTEGER REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS fiscal_documents (
                    id TEXT PRIMARY KEY, quote_id INTEGER NOT NULL REFERENCES quotes(id),
                    number TEXT NOT NULL, mime TEXT NOT NULL, content BLOB NOT NULL, created TEXT NOT NULL
                );
            """)

    def messages(self, quote_id):
        with self.store.connect() as db:
            rows = db.execute("SELECT id,role,name,body,kind,state,created FROM quote_messages WHERE quote_id=? ORDER BY id DESC LIMIT 200", (quote_id,)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def unread(self):
        with self.store.connect() as db:
            return {str(r[0]): r[1] for r in db.execute("SELECT quote_id,count(*) FROM quote_messages WHERE role='client' AND seen IS NULL GROUP BY quote_id")}

    def mark_seen(self, quote_id):
        with self.store.connect() as db:
            db.execute("UPDATE quote_messages SET seen=? WHERE quote_id=? AND role='client' AND seen IS NULL", (now(), quote_id))

    def send(self, quote_id, role, name, body, kind="message", nonce=""):
        name, body = text(name, "seu nome", True, 150), text(body, "mensagem", True, 4000)
        if role not in {"owner", "client"} or kind not in {"message", "request"} or (role == "owner" and kind != "message"):
            raise ValueError("Tipo de mensagem inválido.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", str(nonce)):
            raise ValueError("Reabra a conversa e tente enviar novamente.")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            quote = db.execute("SELECT stage,title FROM quotes WHERE id=?", (quote_id,)).fetchone()
            if not quote:
                raise PortalError("Proposta não encontrada.", 404)
            if quote["stage"] == "Arquivado":
                raise PortalError("Esta conversa foi encerrada. Fale com o responsável pelos contatos da proposta.", 409)
            old = db.execute("SELECT id,body,name,kind FROM quote_messages WHERE quote_id=? AND role=? AND nonce=?", (quote_id, role, nonce)).fetchone()
            if old:
                if (old["body"], old["name"], old["kind"]) != (body, name, kind):
                    raise PortalError("A mensagem anterior já foi recebida. Atualize a conversa antes de enviar outra.", 409)
                return {"id": old["id"], "duplicate": True}
            task_id = None
            if kind == "request":
                task_id = db.execute("INSERT INTO tasks(quote_id,title,due,created) VALUES(?,?,date('now','localtime'),?)",
                                     (quote_id, ("Revisar pedido do cliente: " + quote["title"])[:250], now())).lastrowid
            message_id = db.execute("INSERT INTO quote_messages(quote_id,role,name,body,kind,task_id,nonce,created) VALUES(?,?,?,?,?,?,?,?)",
                                    (quote_id, role, name, body, kind, task_id, nonce, now())).lastrowid
        return {"id": message_id, "duplicate": False}

    def resolve(self, quote_id, message_id):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM quote_messages WHERE id=? AND quote_id=? AND kind='request'", (message_id, quote_id)).fetchone()
            if not row:
                raise PortalError("Pedido não encontrado.", 404)
            db.execute("UPDATE quote_messages SET state='done' WHERE id=?", (message_id,))
            if row["task_id"]:
                db.execute("UPDATE tasks SET state='done' WHERE id=? AND state='open'", (row["task_id"],))

    def fiscal(self, quote_id, private=False):
        with self.store.connect() as db:
            request = db.execute("SELECT data,updated FROM fiscal_requests WHERE quote_id=?", (quote_id,)).fetchone()
            docs = db.execute("SELECT id,number,mime,created FROM fiscal_documents WHERE quote_id=? ORDER BY created DESC", (quote_id,)).fetchall()
        data = json.loads(request["data"]) if request else None
        if data and not private:
            data = {"name": data["name"], "entity": data["entity"], "document": mask_document(data["document"])}
        return {"request": data, "documents": [dict(d) for d in docs]}

    def request_invoice(self, quote_id, values):
        entity = values.get("entity", "PF")
        identity = document(values.get("document"), entity)
        if not identity:
            raise ValueError("Informe o CPF ou CNPJ que deve constar na nota.")
        email = text(values.get("email"), "e-mail para contato", True, 254)
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise ValueError("Informe um e-mail válido.")
        data = {"name": text(values.get("name"), "nome ou razão social", True, 200), "entity": entity,
                "document": identity, "email": email, "address": text(values.get("address"), "endereço", limit=1000)}
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT id FROM fiscal_documents WHERE quote_id=? LIMIT 1", (quote_id,)).fetchone():
                raise PortalError("Uma nota já foi anexada. Use a conversa para pedir uma correção ao responsável.", 409)
            quote = db.execute("SELECT title,stage FROM quotes WHERE id=?", (quote_id,)).fetchone()
            if not quote or quote["stage"] == "Arquivado":
                raise PortalError("Esta proposta não recebe novas solicitações.", 409)
            old = db.execute("SELECT task_id FROM fiscal_requests WHERE quote_id=?", (quote_id,)).fetchone()
            task_id = old["task_id"] if old else db.execute("INSERT INTO tasks(quote_id,title,due,created) VALUES(?,?,date('now','localtime'),?)",
                                                          (quote_id, ("Conferir emissão de nota fiscal: " + quote["title"])[:250], now())).lastrowid
            db.execute("INSERT INTO fiscal_requests VALUES(?,?,?,?,?) ON CONFLICT(quote_id) DO UPDATE SET data=excluded.data,updated=excluded.updated",
                       (quote_id, json.dumps(data, ensure_ascii=False), now(), now(), task_id))
            if not old:
                db.execute("INSERT INTO events(quote_id,description,created) VALUES(?,?,?)", (quote_id, "Cliente informou dados para nota fiscal", now()))

    def attach_invoice(self, quote_id, number, content, extension):
        number = text(number, "número da nota", True, 80)
        if not 1 <= len(content) <= 8 * 1024 * 1024:
            raise ValueError("Escolha um PDF ou XML de até 8 MB.")
        if extension == ".pdf" and content.startswith(b"%PDF-"):
            mime = "application/pdf"
        elif extension == ".xml" and content.lstrip().startswith(b"<") and b"<!DOCTYPE" not in content.upper() and b"<!ENTITY" not in content.upper():
            mime = "application/xml"
        else:
            raise ValueError("O arquivo precisa ser um PDF ou XML da nota emitida.")
        document_id = uuid.uuid4().hex
        with self.store.connect() as db:
            if not db.execute("SELECT id FROM quotes WHERE id=?", (quote_id,)).fetchone():
                raise PortalError("Proposta não encontrada.", 404)
            db.execute("INSERT INTO fiscal_documents VALUES(?,?,?,?,?,?)", (document_id, quote_id, number, mime, content, now()))
            request = db.execute("SELECT task_id FROM fiscal_requests WHERE quote_id=?", (quote_id,)).fetchone()
            if request and request["task_id"]:
                db.execute("UPDATE tasks SET state='done' WHERE id=? AND state='open'", (request["task_id"],))
            db.execute("INSERT INTO events(quote_id,description,created) VALUES(?,?,?)", (quote_id, "Documento fiscal anexado pelo responsável · número " + number, now()))
        return {"id": document_id}

    def download(self, quote_id, document_id):
        with self.store.connect() as db:
            row = db.execute("SELECT mime,content FROM fiscal_documents WHERE id=? AND quote_id=?", (document_id, quote_id)).fetchone()
        if not row:
            raise PortalError("Documento não encontrado.", 404)
        return bytes(row["content"]), row["mime"]
