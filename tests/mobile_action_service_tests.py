import unittest
from unittest.mock import Mock

from services.mobile_action_service import (
    confirm_pending_movement,
    create_snapshot,
    create_transaction,
    delete_transaction,
    discard_pending_movement,
    pay_debt,
    update_transaction,
)


class MobileActionServiceTests(unittest.TestCase):
    def test_create_transaction_action_delegates_to_business_logic(self):
        repository = Mock()
        repository.create_transaction.return_value = "TX00099"
        result = create_transaction("TEN_TEST", {"tipo": "Gasto", "monto": 12.5, "categoria": "Comida"}, repository=repository)

        self.assertEqual(result, {"id": "TX00099"})
        repository.create_transaction.assert_called_once()
        self.assertEqual(repository.create_transaction.call_args.args[0], "TEN_TEST")

    def test_update_transaction_action_requires_field(self):
        with self.assertRaises(ValueError):
            update_transaction("TEN_TEST", "TX00001", {"valor": "Comida"})

    def test_update_transaction_action_delegates(self):
        expected = {"id": "TX00001", "campo": "nota"}
        repository = Mock()
        repository.update_transaction.return_value = expected
        result = update_transaction("TEN_TEST", "TX00001", {"campo": "nota", "valor": "ok"}, repository=repository)

        self.assertEqual(result, expected)
        repository.update_transaction.assert_called_once_with("TEN_TEST", "TX00001", "nota", "ok")

    def test_delete_transaction_action_delegates(self):
        expected = {"id": "TX00001"}
        repository = Mock()
        repository.delete_transaction.return_value = expected
        result = delete_transaction("TEN_TEST", "TX00001", repository=repository)

        self.assertEqual(result, expected)
        repository.delete_transaction.assert_called_once_with("TEN_TEST", "TX00001")

    def test_pay_debt_action_delegates(self):
        expected = {"deuda_id": "D00001", "trans_id": "TX00002"}
        repository = Mock()
        repository.pay_debt.return_value = expected
        result = pay_debt("TEN_TEST", "D00001", {"monto": 50, "moneda": "PEN", "cuenta": "BCP"}, repository=repository)

        self.assertEqual(result, expected)
        repository.pay_debt.assert_called_once()
        self.assertEqual(repository.pay_debt.call_args.args[0], "TEN_TEST")

    def test_confirm_pending_requires_category(self):
        with self.assertRaises(ValueError):
            confirm_pending_movement("TEN_TEST", "PM00001", {})

    def test_confirm_and_discard_pending_delegate(self):
        repository = Mock()
        repository.confirm_pending_movement.return_value = {"tx_id": "TX00003"}
        repository.discard_pending_movement.return_value = {"pendiente_id": "PM00002"}
        confirm_result = confirm_pending_movement("TEN_TEST", "PM00001", {"categoria": "Transporte", "nota": "taxi"}, repository=repository)
        discard_result = discard_pending_movement("TEN_TEST", "PM00002", {"motivo": "duplicado"}, repository=repository)

        self.assertEqual(confirm_result, {"tx_id": "TX00003"})
        self.assertEqual(discard_result, {"pendiente_id": "PM00002"})
        repository.confirm_pending_movement.assert_called_once_with("TEN_TEST", "PM00001", "Transporte", note="taxi")
        repository.discard_pending_movement.assert_called_once_with("TEN_TEST", "PM00002", reason="duplicado")

    def test_create_snapshot_action_delegates(self):
        expected = {"snapshot_id": "SNAP00001"}
        repository = Mock()
        repository.create_snapshot.return_value = expected
        result = create_snapshot("TEN_TEST", {"origen": "Mobile"}, repository=repository)

        self.assertEqual(result, expected)
        repository.create_snapshot.assert_called_once_with("TEN_TEST", origin="Mobile", date=None)


if __name__ == "__main__":
    unittest.main()
