import unittest
from unittest.mock import patch

from api.mobile_service import (
    confirm_pending_movement_action,
    create_snapshot_action,
    create_transaction_action,
    delete_transaction_action,
    discard_pending_movement_action,
    pay_debt_action,
    update_transaction_action,
)


class MobileActionServiceTests(unittest.TestCase):
    def test_create_transaction_action_delegates_to_business_logic(self):
        with patch("api.mobile_service.add_transaction", return_value="TX00099") as add_transaction:
            result = create_transaction_action("TEN_TEST", {"tipo": "Gasto", "monto": 12.5, "categoria": "Comida"})

        self.assertEqual(result, {"id": "TX00099"})
        add_transaction.assert_called_once()
        self.assertEqual(add_transaction.call_args.kwargs["tenant_id"], "TEN_TEST")

    def test_update_transaction_action_requires_field(self):
        with self.assertRaises(ValueError):
            update_transaction_action("TEN_TEST", "TX00001", {"valor": "Comida"})

    def test_update_transaction_action_delegates(self):
        expected = {"id": "TX00001", "campo": "nota"}
        with patch("api.mobile_service.editar_transaccion", return_value=expected) as editar:
            result = update_transaction_action("TEN_TEST", "TX00001", {"campo": "nota", "valor": "ok"})

        self.assertEqual(result, expected)
        editar.assert_called_once_with("TX00001", "nota", "ok", tenant_id="TEN_TEST")

    def test_delete_transaction_action_delegates(self):
        expected = {"id": "TX00001"}
        with patch("api.mobile_service.eliminar_transaccion", return_value=expected) as eliminar:
            result = delete_transaction_action("TEN_TEST", "TX00001")

        self.assertEqual(result, expected)
        eliminar.assert_called_once_with("TX00001", tenant_id="TEN_TEST")

    def test_pay_debt_action_delegates(self):
        expected = {"deuda_id": "D00001", "trans_id": "TX00002"}
        with patch("api.mobile_service.pagar_deuda", return_value=expected) as pagar:
            result = pay_debt_action("TEN_TEST", "D00001", {"monto": 50, "moneda": "PEN", "cuenta": "BCP"})

        self.assertEqual(result, expected)
        pagar.assert_called_once()
        self.assertEqual(pagar.call_args.kwargs["tenant_id"], "TEN_TEST")

    def test_confirm_pending_requires_category(self):
        with self.assertRaises(ValueError):
            confirm_pending_movement_action("TEN_TEST", "PM00001", {})

    def test_confirm_and_discard_pending_delegate(self):
        with patch("api.mobile_service.confirmar_movimiento_pendiente", return_value={"tx_id": "TX00003"}) as confirmar:
            confirm_result = confirm_pending_movement_action("TEN_TEST", "PM00001", {"categoria": "Transporte", "nota": "taxi"})
        with patch("api.mobile_service.descartar_movimiento_pendiente", return_value={"pendiente_id": "PM00002"}) as descartar:
            discard_result = discard_pending_movement_action("TEN_TEST", "PM00002", {"motivo": "duplicado"})

        self.assertEqual(confirm_result, {"tx_id": "TX00003"})
        self.assertEqual(discard_result, {"pendiente_id": "PM00002"})
        confirmar.assert_called_once_with("PM00001", "Transporte", nota_extra="taxi", tenant_id="TEN_TEST")
        descartar.assert_called_once_with("PM00002", motivo="duplicado", tenant_id="TEN_TEST")

    def test_create_snapshot_action_delegates(self):
        expected = {"snapshot_id": "SNAP00001"}
        with patch("api.mobile_service.generar_snapshot_saldos", return_value=expected) as snapshot:
            result = create_snapshot_action("TEN_TEST", {"origen": "Mobile"})

        self.assertEqual(result, expected)
        snapshot.assert_called_once_with(origen="Mobile", fecha=None, tenant_id="TEN_TEST")


if __name__ == "__main__":
    unittest.main()
