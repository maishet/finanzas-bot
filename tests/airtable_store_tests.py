import unittest

from storage.airtable_store import TenantStoreError, build_formula, require_tenant_id


class AirtableStoreTests(unittest.TestCase):
    def test_require_tenant_id_rejects_empty(self):
        with self.assertRaises(TenantStoreError):
            require_tenant_id("")

    def test_build_formula_combines_tenant_and_filter(self):
        formula = build_formula({"TenantID": "TEN00001", "ID": "TX00001"})
        self.assertEqual(formula, "AND({TenantID}='TEN00001',{ID}='TX00001')")

    def test_build_formula_escapes_quotes(self):
        formula = build_formula({"Nombre": "O'Brien"})
        self.assertEqual(formula, "{Nombre}='O\\'Brien'")


if __name__ == "__main__":
    unittest.main()
