import unittest

from tenant_setup_service import _next_numeric_id, _next_prefixed_id


class TenantSetupServiceTests(unittest.TestCase):
    def test_next_prefixed_id(self):
        self.assertEqual(_next_prefixed_id([{"ID": "CTA00009"}], "ID", "CTA"), "CTA00010")

    def test_next_numeric_id(self):
        self.assertEqual(_next_numeric_id([{"ID": "7"}], "ID"), "8")


if __name__ == "__main__":
    unittest.main()
