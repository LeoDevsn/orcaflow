import hashlib
import hmac
import io
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from orca_flow.core import Store
from orca_flow.documents import Workspace, document
from orca_flow.payments import PaymentConfig, Payments, PortalError
from orca_flow.portal import Portal
from orca_flow.web import create_app


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="orcaflow-portal-test-")
        self.root = Path(self.temp.name)
        self.store = Store(self.root)
        self.portal = Portal(self.store)
        self.workspace = Workspace(self.store)
        customer = self.store.save_customer("Cliente fictício", email="cliente@example.com", notes="ANOTACAO-INTERNA")
        self.quote_id = self.store.save_quote(customer, "Serviço de exemplo", (date.today()+timedelta(days=10)).isoformat(),
                                             [{"description":"Projeto", "quantity":"1", "unit_price":"200"}])

    def tearDown(self):
        self.temp.cleanup()

    def test_link_freezes_snapshot_and_hides_internal_data(self):
        self.store.save_settings("Estúdio", "contato@example.com", entity_type="PF", legal_name="Prestador Exemplo", document="52998224725")
        created = self.portal.create(self.quote_id)
        view = self.portal.view(created["token"])
        self.assertEqual(self.store.quote(self.quote_id)["stage"], "Enviado")
        self.assertNotIn("events", view["proposal"])
        self.assertNotIn("email", view["proposal"]["customer"])
        self.assertNotIn("ANOTACAO-INTERNA", json.dumps(view))
        self.assertEqual(view["proposal"]["business"]["document"], "***.***.***-25")
        self.store.save_settings("Outro nome")
        self.assertEqual(self.portal.view(created["token"])["proposal"]["business"]["company"], "Estúdio")
        with self.store.connect() as db:
            row = db.execute("SELECT token_hash,snapshot FROM proposal_links").fetchone()
        self.assertEqual(row["token_hash"], hashlib.sha256(created["token"].encode()).hexdigest())
        self.assertNotIn(created["token"], row["snapshot"])

    def test_regenerating_and_revoking_invalidates_old_links(self):
        first = self.portal.create(self.quote_id)
        second = self.portal.create(self.quote_id)
        with self.assertRaises(PortalError):
            self.portal.view(first["token"])
        self.portal.revoke(self.quote_id, second["id"])
        with self.assertRaises(PortalError):
            self.portal.respond(second["token"], "approve", "Cliente", confirmed=True)

    def test_approval_idempotency_and_single_answer(self):
        created = self.portal.create(self.quote_id)
        response = self.portal.respond(created["token"], "approve", "Cliente", confirmed=True)
        self.assertFalse(response["duplicate"])
        self.assertEqual(self.store.quote(self.quote_id)["stage"], "Aprovado")
        self.assertEqual(self.store.tasks(), [])
        self.assertTrue(self.portal.respond(created["token"], "approve", "Cliente", confirmed=True)["duplicate"])
        with self.assertRaises(PortalError):
            self.portal.respond(created["token"], "decline", "Outra pessoa", confirmed=True)

    def test_changes_require_message_and_create_review_task(self):
        created = self.portal.create(self.quote_id)
        with self.assertRaises(ValueError):
            self.portal.respond(created["token"], "changes", "Cliente", confirmed=True)
        with self.assertRaises(ValueError):
            self.portal.respond(created["token"], "approve", "Cliente", confirmed=False)
        self.portal.respond(created["token"], "changes", "Cliente", "Rever o prazo", True)
        self.assertEqual(self.store.quote(self.quote_id)["stage"], "Negociação")
        self.assertTrue(any("Revisar ajustes" in t["title"] for t in self.store.tasks()))

    def test_restore_does_not_reactivate_old_link(self):
        backup = self.root / "backup.sqlite3"
        created = self.portal.create(self.quote_id)
        self.store.backup(backup)
        self.portal.revoke(self.quote_id, created["id"])
        self.store.restore(backup)
        with self.assertRaises(PortalError):
            self.portal.view(created["token"])

    def test_expired_link_and_unknown_token(self):
        created = self.portal.create(self.quote_id)
        with self.store.connect() as db:
            db.execute("UPDATE proposal_links SET expires='2000-01-01'")
        with self.assertRaises(PortalError):
            self.portal.view(created["token"])
        with self.assertRaises(PortalError):
            self.portal.view("invalid")

    def test_conversation_idempotency_requests_and_resolution(self):
        result = self.workspace.send(self.quote_id, "client", "Cliente", "Trocar a cor", "request", "test-message-00000001")
        self.assertEqual(len(self.store.tasks()), 1)
        self.assertTrue(self.workspace.send(self.quote_id, "client", "Cliente", "Trocar a cor", "request", "test-message-00000001")["duplicate"])
        self.workspace.send(self.quote_id, "owner", "Estúdio", "Vamos revisar", "message", "test-message-00000002")
        self.assertEqual(len(self.workspace.messages(self.quote_id)), 2)
        self.workspace.resolve(self.quote_id, result["id"])
        self.assertEqual(self.store.tasks(), [])
        self.assertEqual(self.workspace.messages(self.quote_id)[0]["state"], "done")

    def test_fiscal_request_masked_and_attachment_in_backup(self):
        self.workspace.request_invoice(self.quote_id, {"entity":"PF", "document":"52998224725", "name":"Cliente", "email":"cliente@example.com"})
        self.assertEqual(self.workspace.fiscal(self.quote_id)["request"]["document"], "***.***.***-25")
        self.assertEqual(self.workspace.fiscal(self.quote_id, True)["request"]["document"], "52998224725")
        payload = b"%PDF-1.4\nDocumento ficticio de teste\n%%EOF"
        attachment = self.workspace.attach_invoice(self.quote_id, "TESTE-1", payload, ".pdf")
        self.assertEqual(self.workspace.download(self.quote_id, attachment["id"])[0], payload)
        self.assertEqual(self.store.tasks(), [])
        backup = self.root / "backup-fiscal.sqlite3"
        self.store.backup(backup)
        self.assertIn(payload, backup.read_bytes())
        with self.assertRaises(PortalError):
            self.workspace.download(self.quote_id+1, attachment["id"])
        with self.assertRaises(PortalError):
            self.workspace.request_invoice(self.quote_id, {"entity":"PF", "document":"52998224725", "name":"Cliente", "email":"cliente@example.com"})

    def test_documents_validate_numeric_and_alphanumeric_cnpj(self):
        self.assertEqual(document("11.222.333/0001-81", "PJ"), "11222333000181")
        self.assertEqual(document("12.ABC.345/01DE-35", "PJ"), "12ABC34501DE35")
        with self.assertRaises(ValueError):
            document("00000000000", "PF")
        with self.assertRaises(ValueError):
            self.workspace.attach_invoice(self.quote_id, "Teste", b"<script>errado</script>", ".pdf")


class PaymentTests(unittest.TestCase):
    # Classe independente da rede: todas as chamadas ao provedor usam respostas fictícias.
    def setUp(self):
        PortalTests.setUp(self)
        self.config = PaymentConfig(self.root)
        with patch("orca_flow.payments.MercadoPago.request", return_value={"id":777,"nickname":"Conta fictícia"}):
            self.config.configure({"access_token":"TEST-credencial-ficticia", "webhook_secret":"segredo-ficticio-webhook", "public_url":"https://pagamentos.example.com", "mode":"sandbox", "enabled":True})
        self.payments = Payments(self.store, self.config)
        self.link = self.portal.create(self.quote_id)
        self.portal.respond(self.link["token"], "approve", "Cliente", confirmed=True)

    def tearDown(self):
        PortalTests.tearDown(self)

    def preference(self):
        snapshot = self.portal.view(self.link["token"], False)["proposal"]
        with patch("orca_flow.payments.MercadoPago.request", return_value={"id":"pref-test","sandbox_init_point":"https://sandbox.mercadopago.com.br/checkout/teste"}) as request:
            result = self.payments.checkout(self.quote_id, snapshot)
            payload = request.call_args.args[2]
        with self.store.connect() as db:
            order = dict(db.execute("SELECT * FROM payment_orders").fetchone())
        return result, payload, order

    def payment(self, order, **changes):
        result = {"id":123, "external_reference":order["id"], "transaction_amount":200,
                  "transaction_amount_refunded":0, "currency_id":"BRL", "collector_id":777,
                  "live_mode":False, "status":"approved", "date_last_updated":"2026-11-11T15:00:00+00:00"}
        result.update(changes)
        return result

    def signature(self, payment_id="123"):
        manifest = f"id:{payment_id};request-id:request-test;ts:1794409200;"
        value = hmac.new(b"segredo-ficticio-webhook", manifest.encode(), hashlib.sha256).hexdigest()
        return "ts=1794409200,v1=" + value

    def test_credentials_blank_by_default_and_not_in_business_backup(self):
        with tempfile.TemporaryDirectory() as other:
            status = PaymentConfig(Path(other)).status()
            self.assertFalse(status["configured"])
            self.assertEqual(status["public_url"], "")
        self.assertNotIn(b"TEST-credencial-ficticia", (self.root/".payments.enc").read_bytes())
        backup = self.root / "backup-business.sqlite3"
        self.store.backup(backup)
        self.assertNotIn(b"TEST-credencial-ficticia", backup.read_bytes())
        self.assertNotIn("access_token", self.config.status())

    def test_preference_amount_is_server_owned_and_return_is_not_receipt(self):
        result, payload, order = self.preference()
        self.assertTrue(result["test"])
        self.assertEqual(payload["items"][0]["unit_price"], 200)
        self.assertEqual(payload["external_reference"], order["id"])
        self.assertEqual(self.payments.summary(self.quote_id)["state"], "pending")
        with self.assertRaises(PortalError):
            self.payments.checkout(self.quote_id, self.portal.view(self.link["token"], False)["proposal"])

    def test_bad_signature_never_queries_provider(self):
        with patch("orca_flow.payments.MercadoPago.request") as request:
            with self.assertRaises(PortalError):
                self.payments.webhook("123", "request-test", "ts=1794409200,v1="+"0"*64)
            request.assert_not_called()

    def test_confirmed_payment_is_idempotent_and_refund_updates(self):
        _, _, order = self.preference()
        with patch("orca_flow.payments.MercadoPago.request", return_value=self.payment(order)):
            self.payments.webhook("123", "request-test", self.signature())
            self.assertTrue(self.payments.webhook("123", "request-test", self.signature())["duplicate"])
        self.assertEqual(self.payments.summary(self.quote_id)["state"], "approved")
        with patch("orca_flow.payments.MercadoPago.request", return_value=self.payment(order, status="refunded",transaction_amount_refunded=200,date_last_updated="2026-11-12T15:00:00+00:00")):
            self.payments.webhook("123", "request-test", self.signature())
        self.assertEqual(self.payments.summary(self.quote_id)["state"], "refunded")
        self.assertEqual(self.store.quote(self.quote_id)["stage"], "Aprovado")

    def test_wrong_amount_account_or_live_mode_cannot_mark_paid(self):
        _, _, order = self.preference()
        for changes in ({"transaction_amount":1},{"collector_id":999},{"live_mode":True},{"currency_id":"USD"}):
            with self.subTest(changes=changes), patch("orca_flow.payments.MercadoPago.request", return_value=self.payment(order, **changes)):
                with self.assertRaises(PortalError):
                    self.payments.webhook("123", "request-test", self.signature())
        self.assertEqual(self.payments.summary(self.quote_id)["state"], "pending")

    def test_two_approved_payments_are_flagged_for_review(self):
        _, _, order = self.preference()
        with patch("orca_flow.payments.MercadoPago.request", return_value=self.payment(order)):
            self.payments.webhook("123", "request-test", self.signature())
        with patch("orca_flow.payments.MercadoPago.request", return_value=self.payment(order, id=124)):
            self.payments.webhook("124", "request-test", self.signature("124"))
        self.assertEqual(self.payments.summary(self.quote_id)["state"], "review")


class PublicApiTests(unittest.TestCase):
    def test_owner_share_and_unprivileged_client_workflow(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(directory, testing=True)
            owner = app.test_client()
            csrf = owner.get('/api/session').get_json()['csrf']
            headers = {'X-CSRF-Token':csrf}
            owner.post('/api/setup',json={'name':'Dono','password':'senha-ficticia-123'},headers=headers)
            store = app.extensions['orca_store']
            customer = store.save_customer('Cliente exemplo')
            quote_id = store.save_quote(customer,'Projeto',(date.today()+timedelta(days=10)).isoformat(),[{'description':'Serviço','quantity':'1','unit_price':'100'}])
            share = owner.post(f'/api/quotes/{quote_id}/share',json={},headers=headers)
            self.assertEqual(share.status_code,200,share.get_json())
            self.assertFalse(share.get_json()['external_ready'])
            token = share.get_json()['url'].rsplit('/',1)[1]
            client = app.test_client()
            response = client.get('/api/public/proposals/'+token)
            public = response.get_json()
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers['Referrer-Policy'],'no-referrer')
            self.assertNotIn('quote_id',public)
            self.assertEqual(client.get('/api/data').status_code,401)
            c_headers={'X-CSRF-Token':public['csrf']}
            self.assertEqual(client.post(f'/api/public/proposals/{token}/reply',json={'action':'approve','name':'Cliente','confirmed':True},headers=c_headers).status_code,200)
            self.assertEqual(client.post(f'/api/public/proposals/{token}/checkout',json={},headers=c_headers).status_code,409)
            message=client.post(f'/api/public/proposals/{token}/messages',json={'name':'Cliente','body':'Uma dúvida','nonce':'client-message-001'},headers=c_headers)
            self.assertEqual(message.status_code,200,message.get_json())
            self.assertEqual(owner.get(f'/api/quotes/{quote_id}/workspace').get_json()['messages'][0]['body'],'Uma dúvida')
            request=client.post(f'/api/public/proposals/{token}/fiscal',json={'entity':'PF','name':'Cliente','document':'52998224725','email':'cliente@example.com'},headers=c_headers)
            self.assertEqual(request.status_code,200,request.get_json())
            pdf=b'%PDF-1.4\nArquivo ficticio para teste\n%%EOF'
            attached=owner.post(f'/api/quotes/{quote_id}/fiscal',data={'number':'TEST-1','issued':'yes','file':(io.BytesIO(pdf),'nota.pdf')},headers=headers)
            self.assertEqual(attached.status_code,200,attached.get_json())
            download=client.get(f"/api/public/proposals/{token}/fiscal/{attached.get_json()['id']}")
            self.assertEqual(download.data,pdf)
            self.assertIn('attachment',download.headers['Content-Disposition'])
            owner.post(f"/api/quotes/{quote_id}/share/{share.get_json()['id']}/revoke",json={},headers=headers)
            self.assertEqual(client.get('/api/public/proposals/'+token).status_code,410)

    def test_demo_cannot_configure_receiving_or_public_hosts(self):
        with tempfile.TemporaryDirectory() as directory:
            app=create_app(directory,testing=True)
            client=app.test_client()
            csrf=client.get('/api/session').get_json()['csrf']
            headers={'X-CSRF-Token':csrf}
            client.post('/api/demo',json={},headers=headers)
            self.assertEqual(client.post('/api/payment-config',json={},headers=headers).status_code,401)
            self.assertEqual(client.post('/api/portal-config',json={'public_url':'https://fake.example.com'},headers=headers).status_code,401)
            client.post('/api/demo/exit',json={},headers=headers)


if __name__ == '__main__':
    unittest.main()
