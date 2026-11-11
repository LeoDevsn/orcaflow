"""Regras de negócio e persistência. Valores em centavos, quantidades em milésimos."""

from __future__ import annotations

import csv
import html
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

STAGES = ("Rascunho", "Enviado", "Negociação", "Aprovado", "Recusado", "Arquivado")
TERMINAL = {"Aprovado", "Recusado", "Arquivado"}


def data_directory() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "OrcaFlow"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def text(value, label: str, required=False, limit=2000) -> str:
    value = "" if value is None else str(value).strip()
    if required and not value:
        raise ValueError(f"Preencha {label}.")
    if len(value) > limit:
        raise ValueError(f"{label} aceita até {limit} caracteres.")
    return value


def number(value, label: str, places: int, maximum: Decimal, positive=False) -> int:
    raw = str(value).strip().replace(" ", "")
    # Entrada brasileira: 1.250,50. Com ponto isolado: separador decimal.
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif places == 2 and re.fullmatch(r"\d{1,3}(?:\.\d{3})+", raw):
        raise ValueError("Valor ambíguo: use 1.250,00 ou 1250 para mil duzentos e cinquenta reais.")
    try:
        parsed = Decimal(raw)
        if not parsed.is_finite() or parsed < 0 or parsed > maximum or (positive and parsed == 0):
            raise ValueError
        scale = Decimal(10) ** places
        if parsed * scale != (parsed * scale).to_integral_value():
            raise ValueError
        return int(parsed * scale)
    except (InvalidOperation, ValueError, OverflowError):
        raise ValueError(f"{label}: informe um número {'positivo' if positive else 'não negativo'} com até {places} casas decimais.") from None


def cents(value) -> int:
    return number(value, "Valor", 2, Decimal("999999999.99"))


def quantity(value) -> int:
    return number(value, "Quantidade", 3, Decimal("999999"), positive=True)


def line_total(qty_milli: int, unit_cents: int) -> int:
    return int((Decimal(qty_milli) * unit_cents / 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money(value: int) -> str:
    sign = "-" if value < 0 else ""
    units, decimals = divmod(abs(value), 100)
    return f"{sign}R$ {units:,}".replace(",", ".") + f",{decimals:02d}"


def decimal_quantity(value: int) -> str:
    return format(Decimal(value) / 1000, "f").rstrip("0").rstrip(".") if value % 1000 else str(value // 1000)


def valid_date(value: str) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise ValueError("Informe uma data no formato AAAA-MM-DD.") from None


class Store:
    def __init__(self, directory: Path | str | None = None):
        self.directory = Path(directory) if directory else data_directory()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "orcaflow.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, company TEXT NOT NULL DEFAULT '',
                    email TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '', created TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS customers_email
                    ON customers(lower(email)) WHERE email != '';
                CREATE TABLE IF NOT EXISTS quotes (
                    id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id),
                    customer_snapshot TEXT NOT NULL, title TEXT NOT NULL, stage TEXT NOT NULL,
                    expires TEXT NOT NULL, discount_cents INTEGER NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, updated TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS lines (
                    id INTEGER PRIMARY KEY, quote_id INTEGER NOT NULL REFERENCES quotes(id),
                    description TEXT NOT NULL, qty_milli INTEGER NOT NULL CHECK(qty_milli > 0),
                    unit_cents INTEGER NOT NULL CHECK(unit_cents >= 0)
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY, quote_id INTEGER REFERENCES quotes(id),
                    title TEXT NOT NULL, due TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'open',
                    automatic INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS automatic_followup
                    ON tasks(quote_id) WHERE state = 'open' AND automatic = 1;
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, quote_id INTEGER NOT NULL REFERENCES quotes(id),
                    description TEXT NOT NULL, created TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                PRAGMA user_version = 1;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def customers(self, query="") -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM customers ORDER BY name COLLATE NOCASE").fetchall()
        query = query.casefold()
        return [dict(row) for row in rows if query in " ".join(str(v) for v in row).casefold()]

    def customer(self, customer_id: int) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
        if not row:
            raise ValueError("Cliente não encontrado.")
        return dict(row)

    def save_customer(self, name, company="", email="", phone="", notes="", customer_id=None) -> int:
        fields = (text(name, "nome", True, 150), text(company, "empresa", limit=150),
                  text(email, "e-mail", limit=254).lower(), text(phone, "telefone", limit=60),
                  text(notes, "observações", limit=4000))
        if fields[2] and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", fields[2]):
            raise ValueError("Informe um e-mail válido ou deixe o campo vazio.")
        try:
            with self.connect() as db:
                if customer_id:
                    result = db.execute("UPDATE customers SET name=?, company=?, email=?, phone=?, notes=? WHERE id=?",
                                        (*fields, customer_id))
                    if not result.rowcount:
                        raise ValueError("Cliente não encontrado.")
                    return customer_id
                return db.execute("INSERT INTO customers (name,company,email,phone,notes,created) VALUES (?,?,?,?,?,?)",
                                  (*fields, now())).lastrowid
        except sqlite3.IntegrityError:
            raise ValueError("Já existe um cliente com este e-mail.") from None

    def import_customers(self, path: Path | str) -> dict:
        """Importação inteira em uma transação: uma linha inválida não deixa dados parciais."""
        with Path(path).open(encoding="utf-8-sig", newline="") as stream:
            sample = stream.read(4096)
            stream.seek(0)
            delimiter = ";" if sample.splitlines() and ";" in sample.splitlines()[0] else ","
            reader = csv.DictReader(stream, delimiter=delimiter)
            if not reader.fieldnames or "nome" not in reader.fieldnames:
                raise ValueError("CSV deve ter cabeçalho nome;empresa;email;telefone;observacoes.")
            rows = list(reader)
        if len(rows) > 10000:
            raise ValueError("Importe até 10.000 clientes por arquivo.")
        added, skipped = 0, 0
        with self.connect() as db:
            for index, row in enumerate(rows, 2):
                name = text(row.get("nome", ""), f"nome na linha {index}", True, 150)
                email = text(row.get("email") or "", "e-mail", limit=254).lower()
                if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
                    raise ValueError(f"E-mail inválido na linha {index}.")
                if email and db.execute("SELECT id FROM customers WHERE lower(email)=?", (email,)).fetchone():
                    skipped += 1
                    continue
                db.execute("INSERT INTO customers(name,company,email,phone,notes,created) VALUES(?,?,?,?,?,?)",
                           (name, text(row.get("empresa") or "", "empresa", limit=150), email,
                            text(row.get("telefone") or "", "telefone", limit=60),
                            text(row.get("observacoes") or "", "observações", limit=4000), now()))
                added += 1
        return {"added": added, "skipped": skipped}

    def save_quote(self, customer_id: int, title: str, expires: str, items: list[dict],
                   discount="0", notes="", quote_id: int | None = None, expected_updated: str | None = None) -> int:
        title, notes = text(title, "título", True, 200), text(notes, "condições", limit=6000)
        expires = valid_date(expires)
        discount_cents = cents(discount)
        if not items or len(items) > 500:
            raise ValueError("Inclua entre 1 e 500 itens no orçamento.")
        validated = [(text(i["description"], "descrição do item", True, 500), quantity(i["quantity"]), cents(i["unit_price"])) for i in items]
        subtotal = sum(line_total(q, p) for _, q, p in validated)
        if discount_cents > subtotal:
            raise ValueError("O desconto não pode ser maior que o subtotal.")
        customer = self.customer(customer_id)
        snapshot = json.dumps({key: customer[key] for key in ("name", "company", "email", "phone")}, ensure_ascii=False)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if quote_id:
                old = db.execute("SELECT stage,updated FROM quotes WHERE id=?", (quote_id,)).fetchone()
                if not old:
                    raise ValueError("Orçamento não encontrado.")
                if old["stage"] != "Rascunho":
                    raise ValueError("Edite somente rascunhos. Duplique para criar uma nova proposta.")
                if expected_updated and old["updated"] != expected_updated:
                    raise ValueError("Este rascunho foi atualizado em outro acesso. Reabra a proposta para conferir a versão mais recente.")
                db.execute("UPDATE quotes SET customer_id=?,customer_snapshot=?,title=?,expires=?,discount_cents=?,notes=?,updated=? WHERE id=?",
                           (customer_id, snapshot, title, expires, discount_cents, notes, now(), quote_id))
                db.execute("DELETE FROM lines WHERE quote_id=?", (quote_id,))
            else:
                quote_id = db.execute("""INSERT INTO quotes(customer_id,customer_snapshot,title,stage,expires,discount_cents,notes,created,updated)
                    VALUES(?,?,?,'Rascunho',?,?,?,?,?)""", (customer_id, snapshot, title, expires, discount_cents, notes, now(), now())).lastrowid
            db.executemany("INSERT INTO lines(quote_id,description,qty_milli,unit_cents) VALUES(?,?,?,?)",
                           [(quote_id, *line) for line in validated])
            db.execute("INSERT INTO events(quote_id,description,created) VALUES(?,?,?)", (quote_id, "Rascunho salvo", now()))
        return quote_id

    def quote(self, quote_id: int) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM quotes WHERE id=?", (quote_id,)).fetchone()
            if not row:
                raise ValueError("Orçamento não encontrado.")
            result = dict(row)
            result["items"] = [dict(r) for r in db.execute("SELECT * FROM lines WHERE quote_id=? ORDER BY id", (quote_id,))]
            result["events"] = [dict(r) for r in db.execute("SELECT * FROM events WHERE quote_id=? ORDER BY id DESC", (quote_id,))]
        result["customer"] = json.loads(result["customer_snapshot"])
        result["number"] = f"ORC-{result['created'][:4]}-{quote_id:05d}"
        result["subtotal"] = sum(line_total(i["qty_milli"], i["unit_cents"]) for i in result["items"])
        result["total"] = result["subtotal"] - result["discount_cents"]
        result["expired"] = result["expires"] < date.today().isoformat() and result["stage"] not in TERMINAL
        return result

    def quotes(self, query="", stage="Todos") -> list[dict]:
        with self.connect() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM quotes ORDER BY id DESC")]
        result = []
        for quote_id in ids:
            item = self.quote(quote_id)
            if stage != "Todos" and item["stage"] != stage:
                continue
            if query.casefold() in f"{item['number']} {item['title']} {item['customer']['name']} {item['customer']['company']}".casefold():
                result.append(item)
        return result

    def set_stage(self, quote_id: int, stage: str) -> None:
        if stage not in STAGES:
            raise ValueError("Etapa inválida.")
        with self.connect() as db:
            old = db.execute("SELECT stage,title FROM quotes WHERE id=?", (quote_id,)).fetchone()
            if not old:
                raise ValueError("Orçamento não encontrado.")
            if old["stage"] == stage:
                return
            if stage == "Rascunho" and old["stage"] != "Rascunho":
                raise ValueError("Use Duplicar para criar uma nova versão editável.")
            db.execute("UPDATE quotes SET stage=?,updated=? WHERE id=?", (stage, now(), quote_id))
            db.execute("INSERT INTO events(quote_id,description,created) VALUES(?,?,?)", (quote_id, f"{old['stage']} → {stage}", now()))
            if stage in TERMINAL:
                db.execute("UPDATE tasks SET state='cancelled' WHERE quote_id=? AND state='open' AND automatic=1", (quote_id,))
            elif stage in {"Enviado", "Negociação"}:
                due = (date.today() + timedelta(days=3 if stage == "Enviado" else 2)).isoformat()
                exists = db.execute("SELECT id FROM tasks WHERE quote_id=? AND automatic=1 AND state='open'", (quote_id,)).fetchone()
                if exists:
                    db.execute("UPDATE tasks SET due=? WHERE id=?", (due, exists["id"]))
                else:
                    db.execute("INSERT INTO tasks(quote_id,title,due,automatic,created) VALUES(?,?,?,1,?)", (quote_id, f"Retornar contato: {old['title']}", due, now()))

    def duplicate_quote(self, quote_id: int) -> int:
        quote = self.quote(quote_id)
        items = [{"description": i["description"], "quantity": decimal_quantity(i["qty_milli"]),
                  "unit_price": str(Decimal(i["unit_cents"]) / 100)} for i in quote["items"]]
        return self.save_quote(quote["customer_id"], quote["title"], (date.today() + timedelta(days=15)).isoformat(),
                               items, str(Decimal(quote["discount_cents"]) / 100), quote["notes"])

    def add_task(self, title: str, due: str, quote_id=None) -> int:
        with self.connect() as db:
            if quote_id and not db.execute("SELECT id FROM quotes WHERE id=?", (quote_id,)).fetchone():
                raise ValueError("Orçamento não encontrado.")
            return db.execute("INSERT INTO tasks(quote_id,title,due,created) VALUES(?,?,?,?)",
                              (quote_id, text(title, "tarefa", True, 250), valid_date(due), now())).lastrowid

    def tasks(self, include_closed=False) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("""SELECT t.*,q.title AS quote_title FROM tasks t
                LEFT JOIN quotes q ON q.id=t.quote_id WHERE (? OR t.state='open') ORDER BY t.due,t.id""", (include_closed,))]

    def complete_task(self, task_id: int) -> None:
        with self.connect() as db:
            result = db.execute("UPDATE tasks SET state='done' WHERE id=? AND state='open'", (task_id,))
            if not result.rowcount:
                raise ValueError("Tarefa não está aberta ou não foi encontrada.")

    def settings(self) -> dict:
        with self.connect() as db:
            return dict(db.execute("SELECT key,value FROM settings"))

    def save_settings(self, company="", email="", phone="", footer=""):
        values = {"company": text(company, "empresa", limit=150), "email": text(email, "e-mail", limit=254),
                  "phone": text(phone, "telefone", limit=60), "footer": text(footer, "rodapé", limit=2000)}
        with self.connect() as db:
            db.executemany("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", values.items())

    def dashboard(self) -> dict:
        quotes = self.quotes()
        tasks = self.tasks()
        return {"customers": len(self.customers()), "quotes": len(quotes),
                "pipeline": sum(q["total"] for q in quotes if q["stage"] in {"Enviado", "Negociação"}),
                "approved": sum(q["total"] for q in quotes if q["stage"] == "Aprovado"),
                "overdue": sum(t["due"] < date.today().isoformat() for t in tasks),
                "stages": {stage: sum(q["stage"] == stage for q in quotes) for stage in STAGES},
                "expired": sum(q["expired"] for q in quotes)}

    def message(self, quote_id: int) -> str:
        q = self.quote(quote_id)
        return (f"Olá, {q['customer']['name']}! Tudo bem?\n\nGostaria de saber se conseguiu avaliar a proposta "
                f"{q['number']} — {q['title']}, no valor de {money(q['total'])}.\n"
                "Fico à disposição para esclarecer dúvidas e combinar os próximos passos.")

    def backup(self, target: Path | str) -> None:
        target = Path(target)
        # Reserva exclusiva para nunca sobrescrever outro banco ou documento.
        with target.open("xb"):
            pass
        try:
            with self.connect() as source:
                destination = sqlite3.connect(target)
                try:
                    source.backup(destination)
                    if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise ValueError("Não foi possível validar o backup.")
                finally:
                    destination.close()
        except BaseException:
            target.unlink(missing_ok=True)
            raise

    def export_quotes(self, target: Path | str):
        def safe(value):
            value = str(value)
            return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else value
        with Path(target).open("x", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream, delimiter=";")
            writer.writerow(["numero", "cliente", "titulo", "etapa", "validade", "total_centavos"])
            for quote in self.quotes():
                writer.writerow([safe(quote["number"]), safe(quote["customer"]["name"]), safe(quote["title"]),
                                 quote["stage"], quote["expires"], quote["total"]])

    def export_proposal(self, quote_id: int, target: Path | str) -> None:
        q = self.quote(quote_id)
        settings = self.settings()
        escape = lambda value: html.escape(str(value), quote=True)
        rows = "".join(f"<tr><td>{escape(i['description'])}</td><td class='num'>{decimal_quantity(i['qty_milli'])}</td>"
                       f"<td class='num'>{money(i['unit_cents'])}</td><td class='num'>{money(line_total(i['qty_milli'],i['unit_cents']))}</td></tr>" for i in q["items"])
        document = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>Proposta {escape(q['number'])}</title><style>
*{{box-sizing:border-box}} body{{font:15px/1.6 'Segoe UI',Arial,sans-serif;color:#20273e;background:#f2f3f8;margin:0;padding:40px}}
main{{max-width:900px;margin:auto;background:white;padding:55px;border-top:8px solid #6653c7}}
header{{display:flex;justify-content:space-between;gap:30px;border-bottom:1px solid #ddd;padding-bottom:28px}}
h1{{font-size:32px;line-height:1.2;margin:30px 0 8px}}h2{{font-size:16px;color:#6653c7;margin:30px 0 8px}}
p{{margin:6px 0}}.muted{{color:#6b7280}}.badge{{font-size:12px;background:#eeeafa;padding:7px 12px;color:#50409d}}
table{{width:100%;border-collapse:collapse;margin-top:30px}}th{{background:#f2effa;text-align:left;font-size:12px;color:#554989}}
td,th{{padding:13px 10px;border-bottom:1px solid #e6e5ee;vertical-align:top}}td:first-child{{overflow-wrap:anywhere;max-width:350px}}
thead{{display:table-header-group}}tr{{break-inside:avoid}}.num{{text-align:right;white-space:nowrap}}
.totals{{margin:20px 0 0 auto;width:310px}}.totals p{{display:flex;justify-content:space-between}}.total{{font-size:22px;color:#50409d;border-top:2px solid #6653c7;padding-top:10px}}
.notes{{white-space:pre-wrap;overflow-wrap:anywhere}}footer{{border-top:1px solid #ddd;margin-top:40px;padding-top:18px;font-size:12px;color:#6b7280}}
@page{{size:A4;margin:15mm}}@media print{{body{{background:white;padding:0}}main{{padding:15px;max-width:none}}header{{break-inside:avoid}}}}
</style></head><body><main><header><div><strong>{escape(settings.get('company') or 'Proposta comercial')}</strong>
<p class="muted">{escape(settings.get('email',''))}<br>{escape(settings.get('phone',''))}</p></div>
<div><span class="badge">{escape(q['number'])}</span><p class="muted">Validade: {escape(q['expires'])}</p></div></header>
<h1>{escape(q['title'])}</h1><p class="muted">Proposta preparada para {escape(q['customer']['name'])}</p>
<h2>CLIENTE</h2><p><strong>{escape(q['customer']['name'])}</strong><br>{escape(q['customer']['company'])}
<br>{escape(q['customer']['email'])} · {escape(q['customer']['phone'])}</p>
<table><thead><tr><th>Descrição</th><th class="num">Qtd.</th><th class="num">Valor unitário</th><th class="num">Total</th></tr></thead><tbody>{rows}</tbody></table>
<div class="totals"><p><span>Subtotal</span><span>{money(q['subtotal'])}</span></p><p><span>Desconto</span><span>{money(q['discount_cents'])}</span></p>
<p class="total"><strong>Total</strong><strong>{money(q['total'])}</strong></p></div>
<h2>CONDIÇÕES E ESCOPO</h2><p class="notes">{escape(q['notes'] or 'Condições a combinar entre as partes.')}</p>
<footer><p class="notes">{escape(settings.get('footer',''))}</p><p>Gerado com OrçaFlow · Documento de proposta, sem valor fiscal.</p></footer>
</main></body></html>"""
        with Path(target).open("x", encoding="utf-8") as stream:
            stream.write(document)

    def restore(self, backup: Path | str) -> Path:
        backup = Path(backup).resolve(strict=True)
        if backup == self.path.resolve():
            raise ValueError("Escolha um backup diferente do banco em uso.")
        source = sqlite3.connect(backup.as_uri() + "?mode=ro", uri=True)
        try:
            if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup com erro de integridade.")
            if source.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValueError("Versão de backup incompatível.")
            expected = {"customers": "id,name,company,email,phone,notes,created",
                        "quotes": "id,customer_id,customer_snapshot,title,stage,expires,discount_cents,notes,created,updated",
                        "lines": "id,quote_id,description,qty_milli,unit_cents",
                        "tasks": "id,quote_id,title,due,state,automatic,created",
                        "events": "id,quote_id,description,created", "settings": "key,value"}
            for table, columns in expected.items():
                source.execute(f"SELECT {columns} FROM {table} LIMIT 0")
            if source.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Backup contém referências inválidas.")
            safety = self.directory / f"antes-restauracao-{uuid.uuid4().hex[:10]}.sqlite3"
            self.backup(safety)
            with self.connect() as destination:
                source.backup(destination)
            return safety
        except sqlite3.DatabaseError:
            raise ValueError("O arquivo não é um backup válido do OrçaFlow.") from None
        finally:
            source.close()


def seed_demo(store: Store):
    if store.customers() or store.quotes():
        raise ValueError("A demonstração exige uma base vazia.")
    store.save_settings("Estúdio Aurora · Demonstração", "contato@example.com", "(00) 00000-0000", "Valores e clientes fictícios para demonstração.")
    a = store.save_customer("Marina Costa (exemplo)", "Café Horizonte", "marina@example.com", "(00) 00000-0001")
    b = store.save_customer("Rafael Lima (exemplo)", "Oficina Norte", "rafael@example.com", "(00) 00000-0002")
    c = store.save_customer("Ana Reis (exemplo)", "Clínica Jardim", "ana@example.com", "(00) 00000-0003")
    expires = (date.today() + timedelta(days=15)).isoformat()
    for customer_id, title, stage, price in ((a, "Identidade visual do café", "Negociação", "1800"),
                                             (b, "Site institucional", "Enviado", "3200"),
                                             (c, "Fotografia de ambientes", "Aprovado", "950"),
                                             (a, "Materiais para redes sociais", "Rascunho", "650")):
        quote_id = store.save_quote(customer_id, title, expires,
                                   [{"description": title, "quantity": "1", "unit_price": price}],
                                   notes="Prazo de entrega: 15 dias úteis após aprovação.\nPagamento: 50% no início e 50% na entrega.")
        if stage != "Rascunho":
            store.set_stage(quote_id, stage)
    store.add_task("Conferir briefing do café (exemplo)", date.today().isoformat(), 1)
    store.add_task("Revisar portfólio antes do contato (exemplo)", (date.today() - timedelta(days=1)).isoformat())
