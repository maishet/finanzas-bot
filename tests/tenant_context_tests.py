import unittest

from tenant_context import tenant_id_for_telegram, user_id_for_telegram


class TenantContextTests(unittest.TestCase):
    def test_tenant_id_for_telegram_is_stable(self):
        self.assertEqual(tenant_id_for_telegram("123"), "TEN_TG_123")

    def test_user_id_for_telegram_is_stable(self):
        self.assertEqual(user_id_for_telegram("123"), "USR_TG_123")


if __name__ == "__main__":
    unittest.main()
