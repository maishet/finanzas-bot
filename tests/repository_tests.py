import unittest
from unittest.mock import Mock, patch

from repositories.airtable_repository import AirtableFinanceRepository
from repositories.postgres_repository import PostgresFinanceRepository


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.current = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=()):
        self.connection.executed.append((sql, params))
        self.current = self.connection.responses.pop(0) if self.connection.responses else []

    def fetchall(self):
        return self.current

    def fetchone(self):
        return self.current[0] if self.current else None


class FakeConnection:
    def __init__(self, responses):
        self.responses = list(responses)
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        pass


class RepositoryTests(unittest.TestCase):
    def test_create_category_returns_existing_with_normalized_match(self):
        repository = AirtableFinanceRepository()
        with patch("repositories.airtable_repository._leer_records_cacheados", return_value=[{"Nombre": "Alimentación", "Tipo": "Gasto"}]):
            result = repository.create_category_if_missing("TEN_TEST", "Alimentacion", "Gasto")

        self.assertEqual(result, {"nombre": "Alimentación", "tipo": "Gasto", "created": False})

    def test_create_category_appends_missing_category(self):
        repository = AirtableFinanceRepository()
        worksheet = Mock()
        with patch("repositories.airtable_repository._leer_records_cacheados", return_value=[]), \
             patch("repositories.airtable_repository.categorias_ws", worksheet), \
             patch("repositories.airtable_repository._row_with_tenant", return_value=["TEN_TEST", "Viajes", "Gasto", ""]), \
             patch("repositories.airtable_repository._cache_invalidate") as cache_invalidate:
            result = repository.create_category_if_missing("TEN_TEST", "Viajes", "Gasto")

        self.assertEqual(result, {"nombre": "Viajes", "tipo": "Gasto", "created": True})
        worksheet.append_row.assert_called_once_with(["TEN_TEST", "Viajes", "Gasto", ""], value_input_option="RAW")
        cache_invalidate.assert_called_once_with("categorias_records")

    def test_transaction_actions_delegate_to_airtable_adapter(self):
        repository = AirtableFinanceRepository()
        with patch("repositories.airtable_repository.add_transaction", return_value="TX00001") as add_transaction:
            result = repository.create_transaction("TEN_TEST", {"tipo": "Gasto", "monto": 10})

        self.assertEqual(result, "TX00001")
        add_transaction.assert_called_once_with(tenant_id="TEN_TEST", tipo="Gasto", monto=10)

    def test_postgres_list_categories_maps_to_mobile_contract(self):
        connection = FakeConnection([
            [("tenant-uuid",)],
            [("Sueldo", "income", "briefcase-outline")],
        ])
        repository = PostgresFinanceRepository(connection_factory=lambda: connection)

        result = repository.list_categories("TEN_TEST", category_type="Ingreso")

        self.assertEqual(result, [{"original": "Sueldo", "tipo": "Ingreso", "subcategorias": "", "icono": "briefcase-outline"}])

    def test_postgres_accounts_summary_maps_totals(self):
        connection = FakeConnection([
            [("tenant-uuid",)],
            [("BCP", "bank_account", "PEN", 100), ("Visa", "credit_card", "PEN", -30)],
        ])
        repository = PostgresFinanceRepository(connection_factory=lambda: connection)

        result = repository.get_accounts_summary("TEN_TEST")

        self.assertEqual(result["total_activos"], 100)
        self.assertEqual(result["total_pasivos"], 0.0)
        self.assertEqual(result["patrimonio"], 100.0)

    def test_postgres_create_transaction_updates_account_and_audit(self):
        connection = FakeConnection([
            [("tenant-uuid",)],
            [("account-uuid",)],
            [("category-uuid",)],
            [("transaction-uuid",)],
        ])
        repository = PostgresFinanceRepository(connection_factory=lambda: connection)

        result = repository.create_transaction("TEN_TEST", {"tipo": "Gasto", "monto": 10, "categoria": "Food", "cuenta": "BCP", "moneda": "PEN"})

        self.assertEqual(result, "transaction-uuid")
        executed_sql = "\n".join(sql for sql, _ in connection.executed)
        self.assertIn("insert into transactions", executed_sql)
        self.assertIn("update accounts set current_balance", executed_sql)
        self.assertIn("insert into audit_logs", executed_sql)

    def test_postgres_snapshot_is_disabled(self):
        repository = PostgresFinanceRepository(connection_factory=lambda: FakeConnection([]))

        self.assertEqual(repository.create_snapshot("TEN_TEST"), {"created": False, "reason": "snapshots_disabled"})


if __name__ == "__main__":
    unittest.main()
