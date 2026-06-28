import unittest
from unittest.mock import Mock, patch

from repositories.airtable_repository import AirtableFinanceRepository


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


if __name__ == "__main__":
    unittest.main()
