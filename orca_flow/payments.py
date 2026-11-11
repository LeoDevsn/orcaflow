"""Checkout hospedado. O aplicativo nunca recebe número de cartão ou CVV."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, quote
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet, InvalidToken

from .core import now
from .portal import PortalError

LABELS = {"not_started": "Não iniciado", "pending": "Aguardando confirmação", "approved": "Pagamento confirmado",
          "rejected": "Pagamento não aprovado", "cancelled": "Pagamento cancelado", "refunded": "Reembolsado",
          "charged_back": "Pagamento contestado", "partially_refunded": "Reembolso parcial", "review": "Conferência necessária"}


def public_origin(value):
    value = str(value or "").strip().rstrip("/")
    parsed = urlparse(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
        raise ValueError("Informe o endereço público HTTPS do OrçaFlow, sem caminhos. Ex.: https://orcaflow.suaempresa.com.br")
    return value


class PaymentConfig:
    def __init__(self, directory):
        self.directory = directory
        self.path = directory / ".payments.enc"
        self.key_path = directory / ".payments-key"

    def read(self):
        if not self.path.exists():
            return {}
        try:
            data = Fernet(self.key_path.read_bytes()).decrypt(self.path.read_bytes())
            return json.loads(data)
        except (OSError, InvalidToken, ValueError):
            raise ValueError("Não foi possível ler a configuração de recebimentos. Cadastre as credenciais novamente neste servidor.") from None

    def write(self, data):
        try:
            with self.key_path.open("xb") as stream:
                stream.write(Fernet.generate_key())
        except FileExistsError:
            pass
        encrypted = Fernet(self.key_path.read_bytes()).encrypt(json.dumps(data).encode())
        temporary = self.directory / f".payments-{uuid.uuid4().hex}.tmp"
        with temporary.open("xb") as stream:
            stream.write(encrypted)
        temporary.replace(self.path)

    def status(self):
        try:
            data = self.read()
        except ValueError:
            return {"configured": False, "enabled": False, "mode": "sandbox", "public_url": "", "account": "", "error": "Cadastre novamente as credenciais neste servidor."}
        return {"configured": bool(data.get("access_token") and data.get("webhook_secret") and data.get("merchant_id")),
                "enabled": bool(data.get("enabled")), "mode": data.get("mode", "sandbox"),
                "public_url": data.get("public_url", ""), "account": data.get("account", "")}

    def configure(self, values):
        try:
            old = self.read()
        except ValueError:
            if values.get("access_token") and values.get("webhook_secret"):
                old = {}
            else:
                raise
        data = {"access_token": values.get("access_token") or old.get("access_token", ""),
                "webhook_secret": values.get("webhook_secret") or old.get("webhook_secret", ""),
                "public_url": public_origin(values.get("public_url", "")),
                "mode": values.get("mode", "sandbox"), "enabled": values.get("enabled") is True}
        if data["mode"] not in {"sandbox", "production"}:
            raise ValueError("Escolha o modo de teste ou produção.")
        for key in ("access_token", "webhook_secret"):
            if not isinstance(data[key], str) or not 8 <= len(data[key]) <= 1000:
                raise ValueError("Preencha o Access Token e a assinatura secreta dos Webhooks da sua conta Mercado Pago.")
        user = MercadoPago(data).request("/users/me")
        if not user.get("id"):
            raise ValueError("Não foi possível identificar a conta recebedora.")
        data.update(merchant_id=str(user["id"]), account=str(user.get("nickname") or user["id"]), verified=now())
        self.write(data)
        return self.status()


class MercadoPago:
    def __init__(self, config):
        self.config = config

    def request(self, path, method="GET", data=None, key=None):
        # Destino fixo: nenhuma URL recebida do navegador é usada como API.
        headers = {"Authorization": "Bearer " + self.config["access_token"], "Accept": "application/json",
                   "Content-Type": "application/json", "User-Agent": "OrcaFlow/2.1"}
        if key:
            headers["X-Idempotency-Key"] = key
        request = Request("https://api.mercadopago.com" + path, method=method, headers=headers,
                          data=json.dumps(data).encode() if data is not None else None)
        try:
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read(2 * 1024 * 1024))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            raise PortalError("O Mercado Pago não respondeu como esperado. Confira as credenciais ou tente novamente em instantes.", 502) from None


class Payments:
    def __init__(self, store, config):
        self.store, self.config = store, config
        self.ensure_schema()

    def ensure_schema(self):
        with self.store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS payment_orders (
                    id TEXT PRIMARY KEY, quote_id INTEGER NOT NULL UNIQUE REFERENCES quotes(id),
                    amount_cents INTEGER NOT NULL, mode TEXT NOT NULL, merchant_id TEXT NOT NULL,
                    preference_id TEXT, checkout_url TEXT, state TEXT NOT NULL DEFAULT 'not_started',
                    created TEXT NOT NULL, updated TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS payment_receipts (
                    payment_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES payment_orders(id),
                    state TEXT NOT NULL, refunded_cents INTEGER NOT NULL DEFAULT 0,
                    provider_updated TEXT NOT NULL, updated TEXT NOT NULL
                );
            """)

    def summary(self, quote_id):
        with self.store.connect() as db:
            row = db.execute("SELECT amount_cents,mode,state,updated FROM payment_orders WHERE quote_id=?", (quote_id,)).fetchone()
        result = dict(row) if row else {"state": "not_started", "mode": self.config.status()["mode"]}
        result["label"] = LABELS.get(result["state"], "Aguardando confirmação")
        result["test"] = result["mode"] != "production"
        return result

    def summaries(self):
        with self.store.connect() as db:
            ids = [r[0] for r in db.execute("SELECT quote_id FROM payment_orders")]
        return {str(quote_id): self.summary(quote_id) for quote_id in ids}

    def checkout(self, quote_id, snapshot, permitted=True):
        config = self.config.read()
        if not config.get("enabled") or not config.get("merchant_id"):
            raise PortalError("O responsável ainda não habilitou os recebimentos. Entre em contato para combinar o pagamento.", 409)
        if not permitted:
            raise PortalError("Aprove esta proposta antes de iniciar o pagamento.", 409)
        if snapshot["total"] <= 0:
            raise PortalError("Esta proposta não tem um valor a cobrar.")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM payment_orders WHERE quote_id=?", (quote_id,)).fetchone()
            if row:
                if row["amount_cents"] != snapshot["total"] or row["merchant_id"] != config["merchant_id"] or row["mode"] != config["mode"]:
                    raise PortalError("A configuração desta cobrança mudou. Peça ao responsável para conferir o pagamento.", 409)
                if row["state"] in {"approved", "pending", "refunded", "charged_back", "partially_refunded", "review"}:
                    raise PortalError("Este pagamento já foi iniciado ou concluído. Confira o status antes de tentar novamente.", 409)
                if row["checkout_url"]:
                    return {"url": row["checkout_url"], "test": config["mode"] != "production"}
                order_id = row["id"]
            else:
                order_id = "orcaflow-" + uuid.uuid4().hex
                db.execute("INSERT INTO payment_orders(id,quote_id,amount_cents,mode,merchant_id,created,updated) VALUES(?,?,?,?,?,?,?)",
                           (order_id, quote_id, snapshot["total"], config["mode"], config["merchant_id"], now(), now()))
            base = public_origin(config["public_url"])
            return_url = base + "/pagamento/retorno"
            # O identificador sobrevive a timeouts, para manter a referência nas tentativas.
            db.commit()
            preference = MercadoPago(config).request("/checkout/preferences", "POST", {
                "items": [{"id": snapshot["number"], "title": snapshot["title"], "quantity": 1,
                           "currency_id": "BRL", "unit_price": float(Decimal(snapshot["total"]) / 100)}],
                "external_reference": order_id, "notification_url": base + "/api/payments/webhook",
                "back_urls": {"success": return_url, "pending": return_url, "failure": return_url},
                "auto_return": "approved", "payment_methods": {"excluded_payment_types": [{"id": "ticket"}, {"id": "atm"}]}
            }, key=order_id)
            url = preference.get("sandbox_init_point" if config["mode"] == "sandbox" else "init_point", "")
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname not in {"www.mercadopago.com.br", "mercadopago.com.br", "sandbox.mercadopago.com.br"} or not preference.get("id"):
                raise PortalError("Não foi possível preparar um checkout válido. Tente novamente.", 502)
            db.execute("UPDATE payment_orders SET preference_id=?,checkout_url=?,state='pending',updated=? WHERE id=?", (str(preference["id"]), url, now(), order_id))
        return {"url": url, "test": config["mode"] != "production"}

    @staticmethod
    def signature(secret, payment_id, request_id, signature):
        try:
            parts = dict(item.strip().split("=", 1) for item in signature.split(","))
            timestamp, supplied = parts["ts"], parts["v1"]
            if not timestamp.isdigit() or not request_id or len(request_id) > 200 or not re.fullmatch(r"[0-9a-fA-F]{64}", supplied):
                return False
            manifest = f"id:{payment_id.lower()};request-id:{request_id};ts:{timestamp};"
            expected = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
            return hmac.compare_digest(expected, supplied.lower())
        except (ValueError, KeyError, AttributeError):
            return False

    def webhook(self, payment_id, request_id, signature):
        config = self.config.read()
        if not config.get("webhook_secret"):
            raise PortalError("Recebimentos ainda não configurados.", 503)
        if not re.fullmatch(r"\d{1,30}", str(payment_id)) or not self.signature(config["webhook_secret"], str(payment_id), request_id, signature):
            raise PortalError("Notificação de pagamento não autenticada.", 401)
        payment = MercadoPago(config).request("/v1/payments/" + str(payment_id))
        return self._apply(payment, str(payment_id))

    def refresh(self, quote_id):
        config = self.config.read()
        with self.store.connect() as db:
            order = db.execute("SELECT * FROM payment_orders WHERE quote_id=?", (quote_id,)).fetchone()
        if not order:
            return self.summary(quote_id)
        if str(config.get("merchant_id")) != order["merchant_id"]:
            raise PortalError("A conta recebedora mudou. O proprietário precisa conferir esta cobrança.", 409)
        results = MercadoPago(config).request("/v1/payments/search?external_reference=" + quote(order["id"], safe="") + "&sort=date_created&criteria=desc&limit=20")
        payments = results.get("results", [])
        if not isinstance(payments, list):
            raise PortalError("Não foi possível conferir o pagamento neste momento.", 502)
        for candidate in payments[:20]:
            payment_id = str(candidate.get("id", ""))
            if re.fullmatch(r"\d{1,30}", payment_id):
                payment = MercadoPago(config).request("/v1/payments/" + payment_id)
                self._apply(payment, payment_id)
        if not payments and order["state"] == "pending":
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(order["updated"])).total_seconds()
            if elapsed > 120:
                with self.store.connect() as db:
                    db.execute("UPDATE payment_orders SET state='not_started',updated=? WHERE id=? AND state='pending' AND NOT EXISTS(SELECT 1 FROM payment_receipts WHERE order_id=?)", (now(), order["id"], order["id"]))
        return self.summary(quote_id)

    def _apply(self, payment, payment_id):
        reference = payment.get("external_reference", "")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            order = db.execute("SELECT * FROM payment_orders WHERE id=?", (reference,)).fetchone()
            if not order:
                return {"ok": True, "ignored": True}
            try:
                amount = Decimal(str(payment["transaction_amount"])) * 100
                refunded = Decimal(str(payment.get("transaction_amount_refunded", 0))) * 100
                updated = datetime.fromisoformat(payment["date_last_updated"].replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
                if (not amount.is_finite() or amount != order["amount_cents"] or not refunded.is_finite()
                        or refunded < 0 or refunded > amount or refunded != refunded.to_integral_value()):
                    raise ValueError
            except (KeyError, InvalidOperation, ValueError, TypeError):
                raise PortalError("Valor ou data da confirmação não confere com esta cobrança.", 422) from None
            if (payment.get("currency_id") != "BRL" or str(payment.get("collector_id")) != order["merchant_id"]
                    or str(payment.get("id")) != str(payment_id) or payment.get("live_mode") is not (order["mode"] == "production")):
                raise PortalError("A confirmação não corresponde à conta e ao ambiente desta cobrança.", 422)
            status = payment.get("status")
            status = "pending" if status in {"in_process", "in_mediation", "authorized"} else status
            if status not in {"pending", "approved", "rejected", "cancelled", "refunded", "charged_back"}:
                raise PortalError("Status de pagamento não reconhecido.", 422)
            previous = db.execute("SELECT * FROM payment_receipts WHERE payment_id=?", (str(payment_id),)).fetchone()
            if previous and previous["order_id"] != order["id"]:
                raise PortalError("Este pagamento já está vinculado a outra cobrança.", 422)
            if previous and previous["provider_updated"] >= updated:
                return {"ok": True, "duplicate": True}
            db.execute("""INSERT INTO payment_receipts VALUES(?,?,?,?,?,?) ON CONFLICT(payment_id) DO UPDATE SET
                state=excluded.state,refunded_cents=excluded.refunded_cents,provider_updated=excluded.provider_updated,updated=excluded.updated""",
                       (str(payment_id), order["id"], status, int(refunded), updated, now()))
            receipts = db.execute("SELECT state,refunded_cents FROM payment_receipts WHERE order_id=?", (order["id"],)).fetchall()
            approved = [r for r in receipts if r["state"] == "approved"]
            net = sum(order["amount_cents"] - r["refunded_cents"] for r in approved)
            aggregate = ("review" if net > order["amount_cents"] else "charged_back" if any(r["state"] == "charged_back" for r in receipts)
                         else "approved" if net == order["amount_cents"] else "partially_refunded" if net > 0
                         else "refunded" if any(r["state"] == "refunded" or r["refunded_cents"] for r in receipts)
                         else "pending" if any(r["state"] == "pending" for r in receipts) else status)
            db.execute("UPDATE payment_orders SET state=?,updated=? WHERE id=?", (aggregate, now(), order["id"]))
            if order["state"] != aggregate:
                db.execute("INSERT INTO events(quote_id,description,created) VALUES(?,?,?)", (order["quote_id"],
                           ("Teste · " if order["mode"] == "sandbox" else "") + "Mercado Pago: " + LABELS[aggregate], now()))
        return {"ok": True}
