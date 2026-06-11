import unittest
from unittest.mock import patch

from tenant_setup_service import _create_record_allowing_generated_id, _next_numeric_id, _next_prefixed_id


class FakeStore:
    def __init__(self):
        self.calls = []

    def create_record(self, table_name, tenant_id, fields):
        self.calls.append((table_name, tenant_id, dict(fields)))
        if "ID" in fields:
            raise RuntimeError('HTTP Error 422: Unprocessable Entity. Field "ID" cannot accept the provided value')
        return {"fields": {"ID": "7", **fields}}


class TenantSetupServiceTests(unittest.TestCase):
    def test_next_prefixed_id(self):
        self.assertEqual(_next_prefixed_id([{"ID": "CTA00009"}], "ID", "CTA"), "CTA00010")

    def test_next_numeric_id(self):
        self.assertEqual(_next_numeric_id([{"ID": "7"}], "ID"), "8")

    def test_next_numeric_id_accepts_airtable_number_text(self):
        self.assertEqual(_next_numeric_id([{"ID": "7.0"}], "ID"), "8")

    def test_create_record_retries_without_generated_id(self):
        store = FakeStore()
        with patch("tenant_setup_service._store", return_value=store):
            created = _create_record_allowing_generated_id(
                "Cuentas",
                "TEN_TEST",
                {"ID": "CTA00001", "Nombre": "BCP"},
            )

        self.assertEqual(created["ID"], "7")
        self.assertEqual(created["Nombre"], "BCP")
        self.assertEqual(len(store.calls), 2)
        self.assertIn("ID", store.calls[0][2])
        self.assertNotIn("ID", store.calls[1][2])


if __name__ == "__main__":
    unittest.main()
