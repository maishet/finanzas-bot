import unittest
from unittest.mock import patch

from api.mobile_service import (
    create_transaction_action,
    get_accounts_payload,
    get_pending_movements_payload,
    get_summary_payload,
)


class MobileServiceFacadeTests(unittest.TestCase):
    def test_read_facade_delegates_to_read_service(self):
        with patch("api.mobile_service.get_accounts", return_value=[{"nombre": "BCP"}]) as accounts:
            self.assertEqual(get_accounts_payload("TEN_TEST"), [{"nombre": "BCP"}])
        with patch("api.mobile_service.get_summary", return_value={"tenant_id": "TEN_TEST"}) as summary:
            self.assertEqual(get_summary_payload("TEN_TEST"), {"tenant_id": "TEN_TEST"})
        with patch("api.mobile_service.get_pending_movements", return_value=[]) as pending:
            self.assertEqual(get_pending_movements_payload("TEN_TEST", limit=10), [])

        accounts.assert_called_once_with("TEN_TEST")
        summary.assert_called_once_with("TEN_TEST")
        pending.assert_called_once_with("TEN_TEST", limit=10)

    def test_action_facade_delegates_to_action_service(self):
        with patch("api.mobile_service.create_transaction", return_value={"id": "TX00001"}) as create:
            self.assertEqual(create_transaction_action("TEN_TEST", {"tipo": "Gasto"}), {"id": "TX00001"})

        create.assert_called_once_with("TEN_TEST", {"tipo": "Gasto"})


if __name__ == "__main__":
    unittest.main()
