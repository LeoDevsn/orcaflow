import csv
from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from orca_flow.core import Store, cents, decimal_quantity, line_total, money, quantity, seed_demo


class NumericTests(unittest.TestCase):
    def test_exact_brazilian_money(self):
        self.assertEqual(cents("1.234,56"), 123456)
        self.assertEqual(cents("12.34"), 1234)
        self.assertEqual(cents("0,01"), 1)
        self.assertEqual(money(123456), "R$ 1.234,56")

    def test_reject_invalid_numeric_values(self):
        for value in ("NaN", "Infinity", "-1", "1,001", "", "9999999999", "1.250"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                cents(value)
        with self.assertRaises(ValueError):
            quantity("0")

    def test_fractional_quantity_rounds_half_up_per_line(self):
        self.assertEqual(quantity("1,125"), 1125)
        self.assertEqual(line_total(1125, 100), 113)
        self.assertEqual(decimal_quantity(1250), "1.25")
        self.assertEqual(decimal_quantity(1000), "1")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="orcaflow-test-")
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "dados")
        self.customer_id = self.store.save_customer("Ana", "Estúdio", "ana@example.com")
        self.expires = (date.today() + timedelta(days=15)).isoformat()

    def tearDown(self):
        self.temp.cleanup()

    def quote(self, **kwargs):
        values = dict(customer_id=self.customer_id, title="Projeto exemplo", expires=self.expires,
                      items=[{"description": "Desenvolvimento", "quantity": "1,5", "unit_price": "100,10"}],
                      discount="0,15", notes="Escopo definido.")
        values.update(kwargs)
        return self.store.save_quote(**values)

    def test_create_quote_exact_total_and_customer_snapshot(self):
        quote_id = self.quote()
        self.store.save_customer("Ana alterada", email="novo@example.com", customer_id=self.customer_id)
        quote = self.store.quote(quote_id)
        self.assertEqual(quote["total"], 15000)
        self.assertEqual(quote["subtotal"], 15015)
        self.assertEqual(quote["customer"]["name"], "Ana")
        self.assertEqual(quote["stage"], "Rascunho")
        self.assertTrue(quote["number"].endswith("00001"))

    def test_invalid_quote_cannot_leave_partial_records(self):
        with self.assertRaises(ValueError):
            self.quote(discount="500")
        with self.assertRaises(ValueError):
            self.quote(items=[])
        with self.assertRaises(ValueError):
            self.quote(expires="data incorreta")
        self.assertEqual(self.store.quotes(), [])

    def test_customer_validation_and_case_insensitive_email(self):
        with self.assertRaises(ValueError):
            self.store.save_customer("Outra", email="ANA@example.com")
        with self.assertRaises(ValueError):
            self.store.save_customer("", email="x@example.com")
        with self.assertRaises(ValueError):
            self.store.save_customer("Ana", email="invalido")

    def test_stages_schedule_one_followup_and_close_on_approval(self):
        quote_id = self.quote()
        self.store.set_stage(quote_id, "Enviado")
        tasks = self.store.tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["due"], (date.today() + timedelta(days=3)).isoformat())
        self.store.set_stage(quote_id, "Enviado")
        self.store.set_stage(quote_id, "Negociação")
        tasks = self.store.tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["due"], (date.today() + timedelta(days=2)).isoformat())
        self.store.set_stage(quote_id, "Aprovado")
        self.assertEqual(self.store.tasks(), [])
        self.assertEqual(self.store.tasks(True)[0]["state"], "cancelled")
        self.assertEqual(self.store.dashboard()["approved"], 15000)

    def test_sent_quote_is_immutable_and_can_be_duplicated(self):
        quote_id = self.quote()
        self.store.set_stage(quote_id, "Enviado")
        with self.assertRaises(ValueError):
            self.quote(quote_id=quote_id)
        with self.assertRaises(ValueError):
            self.store.set_stage(quote_id, "Rascunho")
        new_id = self.store.duplicate_quote(quote_id)
        self.assertNotEqual(new_id, quote_id)
        duplicate = self.store.quote(new_id)
        self.assertEqual(duplicate["stage"], "Rascunho")
        self.assertEqual(duplicate["total"], self.store.quote(quote_id)["total"])

    def test_task_completion_and_dashboard_overdue(self):
        task_id = self.store.add_task("Retornar contato", (date.today()-timedelta(days=1)).isoformat())
        self.assertEqual(self.store.dashboard()["overdue"], 1)
        self.store.complete_task(task_id)
        self.assertEqual(self.store.dashboard()["overdue"], 0)
        with self.assertRaises(ValueError):
            self.store.complete_task(task_id)

    def test_customer_import_deduplicates_and_is_atomic(self):
        source = self.root / "clientes.csv"
        source.write_text("nome;email\nOutro;ana@example.com\nBia;bia@example.com\n", encoding="utf-8")
        self.assertEqual(self.store.import_customers(source), {"added": 1, "skipped": 1})
        source.write_text("nome;email\nCarlos;carlos@example.com\nDora;invalido\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.import_customers(source)
        self.assertEqual(len(self.store.customers()), 2)

    def test_web_draft_rejects_overwriting_a_newer_version(self):
        quote_id = self.quote()
        original = self.store.quote(quote_id)
        self.quote(quote_id=quote_id, title="Atualizado em outro navegador")
        with self.assertRaisesRegex(ValueError, "outro acesso"):
            self.quote(quote_id=quote_id, expected_updated=original["updated"])
        self.assertEqual(self.store.quote(quote_id)["title"], "Atualizado em outro navegador")

    def test_backup_restore_roundtrip_preserves_previous_database(self):
        self.quote()
        backup = self.root / "backup.sqlite3"
        self.store.backup(backup)
        self.store.save_customer("Nova pessoa")
        self.assertEqual(len(self.store.customers()), 2)
        safety = self.store.restore(backup)
        self.assertEqual(len(self.store.customers()), 1)
        self.assertEqual(len(self.store.quotes()), 1)
        self.assertTrue(safety.is_file())
        with closing(sqlite3.connect(safety)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM customers").fetchone()[0], 2)
        with self.assertRaises(FileExistsError):
            self.store.backup(backup)

    def test_invalid_restore_does_not_change_current_database(self):
        bad = self.root / "bad.sqlite3"
        bad.write_text("Não é um banco", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.restore(bad)
        self.assertEqual(len(self.store.customers()), 1)
        with self.assertRaises(ValueError):
            self.store.restore(self.store.path)

    def test_exported_proposal_escapes_untrusted_text_and_never_overwrites(self):
        quote_id = self.quote(title='<script>alert("x")</script>')
        target = self.root / "proposta.html"
        self.store.export_proposal(quote_id, target)
        content = target.read_text(encoding="utf-8")
        self.assertIn("&lt;script&gt;", content)
        self.assertNotIn("<script>", content)
        self.assertIn("R$ 150,00", content)
        self.assertIn("Content-Security-Policy", content)
        with self.assertRaises(FileExistsError):
            self.store.export_proposal(quote_id, target)

    def test_quote_csv_and_message(self):
        quote_id = self.quote(title="=formula")
        target = self.root / "orcamentos.csv"
        self.store.export_quotes(target)
        content = target.read_text(encoding="utf-8-sig")
        self.assertIn("'=formula", content)
        self.assertIn("15000", content)
        self.assertIn("R$ 150,00", self.store.message(quote_id))
        self.assertIn("Ana", self.store.message(quote_id))

    def test_demo_is_repeat_guarded_and_uses_fictitious_data(self):
        demo = Store(self.root / "demo")
        seed_demo(demo)
        self.assertEqual(len(demo.quotes()), 4)
        self.assertEqual(demo.dashboard()["approved"], 95000)
        self.assertEqual(demo.dashboard()["pipeline"], 500000)
        self.assertEqual(len(self.store.customers()), 1)
        with self.assertRaises(ValueError):
            seed_demo(demo)

    def test_expired_quote_flag_and_stage_filter(self):
        quote_id = self.quote(expires=(date.today()-timedelta(days=1)).isoformat())
        self.assertTrue(self.store.quote(quote_id)["expired"])
        self.assertEqual(len(self.store.quotes(query="ana", stage="Rascunho")), 1)
        self.store.set_stage(quote_id, "Recusado")
        self.assertFalse(self.store.quote(quote_id)["expired"])
        self.assertEqual(self.store.quotes(stage="Rascunho"), [])


if __name__ == "__main__":
    unittest.main()
