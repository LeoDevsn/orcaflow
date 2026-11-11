import io
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from orca_flow.web import create_app


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="orcaflow-web-test-")
        self.app = create_app(Path(self.temp.name), testing=True)
        self.client = self.app.test_client()
        self.csrf = self.client.get("/api/session").get_json()["csrf"]

    def tearDown(self):
        self.client.post("/api/demo/exit", json={}, headers={"X-CSRF-Token": self.csrf})
        self.temp.cleanup()

    def post(self, path, data=None):
        return self.client.post(path, json=data or {}, headers={"X-CSRF-Token": self.csrf})

    def setup_owner(self):
        result = self.post("/api/setup", {"name": "Pessoa de exemplo", "password": "senha-exemplo-123"})
        self.assertEqual(result.status_code, 200, result.get_json())

    def test_private_data_requires_session(self):
        self.assertEqual(self.client.get("/api/data").status_code, 401)
        self.assertEqual(self.client.get("/api/export/backup").status_code, 401)
        self.assertEqual(self.post("/api/customers", {"name": "Pessoa"}).status_code, 401)

    def test_setup_login_and_logout(self):
        self.assertFalse(self.client.get("/api/session").get_json()["configured"])
        self.assertEqual(self.post("/api/setup", {"name": "Pessoa", "password": "curta"}).status_code, 400)
        self.setup_owner()
        self.assertTrue(self.client.get("/api/session").get_json()["authenticated"])
        self.assertEqual(self.post("/api/setup", {"name": "Outra", "password": "outra-senha-123"}).status_code, 400)
        self.post("/api/logout")
        self.csrf = self.client.get("/api/session").get_json()["csrf"]
        self.assertEqual(self.post("/api/login", {"password": "errada"}).status_code, 401)
        self.assertEqual(self.post("/api/login", {"password": "senha-exemplo-123"}).status_code, 200)

    def test_csrf_and_unknown_hosts_are_rejected(self):
        self.assertEqual(self.client.post("/api/demo", json={}).status_code, 403)
        self.assertEqual(self.client.get("/api/session", base_url="http://host-invasor.example").status_code, 400)
        self.assertEqual(self.post("/api/demo").status_code, 200)

    def test_demo_is_isolated_from_real_data_and_other_browsers(self):
        self.setup_owner()
        self.post("/api/customers", {"name": "Registro real de teste"})
        self.post("/api/demo")
        self.assertEqual(len(self.client.get("/api/data").get_json()["customers"]), 3)
        self.post("/api/customers", {"name": "Só na demo"})
        second = self.app.test_client()
        second_csrf = second.get("/api/session").get_json()["csrf"]
        second.post("/api/demo", json={}, headers={"X-CSRF-Token": second_csrf})
        self.assertEqual(len(second.get("/api/data").get_json()["customers"]), 3)
        second.post("/api/demo/exit", json={}, headers={"X-CSRF-Token": second_csrf})
        self.post("/api/demo/exit")
        data = self.client.get("/api/data").get_json()
        self.assertEqual([c["name"] for c in data["customers"]], ["Registro real de teste"])

    def test_customer_quote_stage_and_task_roundtrip(self):
        self.setup_owner()
        customer_id = self.post("/api/customers", {"name": "Cliente", "email": "cliente@example.com"}).get_json()["id"]
        quote_id = self.post("/api/quotes", {"customer_id": customer_id, "title": "Projeto", "expires": (date.today()+timedelta(days=10)).isoformat(),
                                            "items": [{"description": "Serviço", "quantity": "1,5", "unit_price": "100"}]}).get_json()["id"]
        self.assertEqual(self.post(f"/api/quotes/{quote_id}/stage", {"stage": "Enviado"}).status_code, 200)
        data = self.client.get("/api/data").get_json()
        self.assertEqual(data["quotes"][0]["total"], 15000)
        self.assertEqual(len(data["tasks"]), 1)
        task_id = data["tasks"][0]["id"]
        self.assertEqual(self.post(f"/api/tasks/{task_id}/complete").status_code, 200)
        proposal = self.client.get(f"/api/quotes/{quote_id}/proposal")
        self.assertEqual(proposal.status_code, 200)
        self.assertIn("attachment", proposal.headers["Content-Disposition"])
        self.assertIn(b"R$ 150,00", proposal.data)

    def test_password_change_invalidates_other_sessions(self):
        self.setup_owner()
        second = self.app.test_client()
        token = second.get("/api/session").get_json()["csrf"]
        second.post("/api/login", json={"password": "senha-exemplo-123"}, headers={"X-CSRF-Token": token})
        self.assertEqual(second.get("/api/data").status_code, 200)
        self.assertEqual(self.post("/api/password", {"current": "senha-exemplo-123", "password": "nova-senha-456"}).status_code, 200)
        self.assertEqual(second.get("/api/data").status_code, 401)
        self.assertEqual(self.client.get("/api/data").status_code, 200)

    def test_backup_restore_keeps_login_separate(self):
        self.setup_owner()
        self.post("/api/customers", {"name": "Cliente antes"})
        backup = self.client.get("/api/export/backup")
        self.assertEqual(backup.status_code, 200)
        self.post("/api/customers", {"name": "Cliente depois"})
        response = self.client.post("/api/import/backup", data={"file": (io.BytesIO(backup.data), "backup.sqlite3")},
                                    headers={"X-CSRF-Token": self.csrf}, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(self.client.get("/api/session").get_json()["authenticated"])
        self.assertEqual(len(self.client.get("/api/data").get_json()["customers"]), 1)

    def test_security_headers_and_error_messages(self):
        response = self.client.get("/health")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(self.post("/api/login", {"password": "nunca configurada"}).status_code, 401)
        self.assertNotIn("Traceback", self.client.get("/api/unknown").get_data(as_text=True))

    def test_first_setup_must_be_local(self):
        response = self.client.post("/api/setup", json={"name": "Pessoa", "password": "senha-exemplo-123"},
                                    headers={"X-CSRF-Token": self.csrf}, environ_overrides={"REMOTE_ADDR": "192.0.2.5"})
        self.assertEqual(response.status_code, 403)

    def test_frontend_assets_and_template_are_served(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'lang="pt-BR"', response.data)
        response.close()
        for path in ("/static/style.css", "/static/app.js", "/static/fonts/public-sans-400.ttf"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            response.close()
        self.assertEqual(self.client.get("/api/template/customers").status_code, 401)
        self.setup_owner()
        self.assertEqual(self.client.get("/api/template/customers").status_code, 200)


if __name__ == "__main__":
    unittest.main()
