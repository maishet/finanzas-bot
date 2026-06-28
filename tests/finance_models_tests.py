import unittest

from domain.finance_models import AccountRecord, PendingMovementRecord, TransactionRecord, normalize_transaction_type
from utils.finance_format import get_field, normalize_text, parse_date, parse_number


class FinanceModelsTests(unittest.TestCase):
    def test_format_utils_parse_legacy_values(self):
        self.assertEqual(normalize_text("Alimentación"), "alimentacion")
        self.assertEqual(parse_number("S/ 1.234,56"), 1234.56)
        self.assertEqual(parse_number("1,234.56"), 1234.56)
        self.assertIsNotNone(parse_date("2026-06-28T12:30:00Z"))
        self.assertEqual(get_field({"Categoría": "Food"}, "Categoria", "Categoría"), "Food")

    def test_normalizes_transaction_type_to_english(self):
        self.assertEqual(normalize_transaction_type("Ingreso"), "income")
        self.assertEqual(normalize_transaction_type("Gasto"), "expense")

    def test_transaction_keeps_mobile_payload_compatible(self):
        record = TransactionRecord.from_legacy({
            "ID": "TX00001",
            "Fecha": "2026-06-28",
            "Tipo": "Ingreso",
            "Monto": "1.250,50",
            "Moneda": "pen",
            "Categoría": "Sueldo",
            "Cuenta": "BCP",
        })

        self.assertEqual(record.transaction_type, "income")
        self.assertEqual(record.amount, 1250.50)
        self.assertEqual(record.to_mobile_payload()["tipo"], "Ingreso")

    def test_account_and_pending_records_are_normalized_internally(self):
        account = AccountRecord.from_legacy({"nombre": "Efectivo", "tipo": "Efectivo", "saldo": "100", "moneda": "PEN"})
        pending = PendingMovementRecord.from_legacy({"ID": "PM1", "Tipo": "Gasto", "Monto": "42.5", "Estado": "Pendiente"})

        self.assertEqual(account.account_type, "cash")
        self.assertEqual(pending.transaction_type, "expense")
        self.assertEqual(pending.status, "pending")
        self.assertEqual(pending.to_mobile_payload()["tipo"], "Gasto")


if __name__ == "__main__":
    unittest.main()
