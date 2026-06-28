from typing import Any

from airtable_handler import (
    _cache_invalidate,
    _leer_records_cacheados,
    _row_with_tenant,
    add_transaction,
    categorias_ws,
    confirmar_movimiento_pendiente,
    descartar_movimiento_pendiente,
    editar_transaccion,
    eliminar_transaccion,
    generar_snapshot_saldos,
    listar_movimientos_pendientes,
    normalizar_texto,
    obtener_balance_mes,
    obtener_categorias,
    obtener_deudas_activas,
    obtener_resumen_cuentas,
    pagar_deuda,
    trans_ws,
)


class AirtableFinanceRepository:
    def get_accounts_summary(self, tenant_id: str) -> dict[str, Any]:
        return obtener_resumen_cuentas(tenant_id=tenant_id)

    def get_month_balance(self, month: int, year: int, tenant_id: str) -> dict[str, Any]:
        return obtener_balance_mes(month, year, tenant_id=tenant_id)

    def list_active_debts(self, tenant_id: str) -> list[dict[str, Any]]:
        return obtener_deudas_activas(tenant_id=tenant_id)

    def list_transactions(self, tenant_id: str) -> list[dict[str, Any]]:
        return _leer_records_cacheados(trans_ws, "transacciones_records", tenant_id=tenant_id)

    def list_categories(self, tenant_id: str, category_type: str | None = None) -> list[dict[str, Any]]:
        return obtener_categorias(category_type, tenant_id=tenant_id)

    def create_category_if_missing(self, tenant_id: str, name: str, category_type: str, subcategories: str = "") -> dict[str, Any]:
        existing = _leer_records_cacheados(categorias_ws, "categorias_records", tenant_id=tenant_id)
        key = (normalizar_texto(name), normalizar_texto(category_type))
        for row in existing:
            if (normalizar_texto(row.get("Nombre", "")), normalizar_texto(row.get("Tipo", ""))) == key:
                return {"nombre": str(row.get("Nombre", name)).strip(), "tipo": str(row.get("Tipo", category_type)).strip(), "created": False}

        categorias_ws.append_row(_row_with_tenant(categorias_ws, [name, category_type, subcategories], tenant_id), value_input_option="RAW")
        _cache_invalidate("categorias_records")
        return {"nombre": name, "tipo": category_type, "created": True}

    def list_pending_movements(self, tenant_id: str, limit: int = 50, include_resolved: bool = False) -> list[dict[str, Any]]:
        return listar_movimientos_pendientes(limit=limit, include_resueltos=include_resolved, tenant_id=tenant_id)

    def create_transaction(self, tenant_id: str, payload: dict[str, Any]) -> str:
        return add_transaction(tenant_id=tenant_id, **payload)

    def update_transaction(self, tenant_id: str, transaction_id: str, field: str, value: Any) -> Any:
        return editar_transaccion(transaction_id, field, value, tenant_id=tenant_id)

    def delete_transaction(self, tenant_id: str, transaction_id: str) -> Any:
        return eliminar_transaccion(transaction_id, tenant_id=tenant_id)

    def pay_debt(self, tenant_id: str, debt_id: str, payload: dict[str, Any]) -> Any:
        return pagar_deuda(deuda_id=debt_id, tenant_id=tenant_id, **payload)

    def confirm_pending_movement(self, tenant_id: str, pending_id: str, category: str, note: str = "") -> Any:
        return confirmar_movimiento_pendiente(pending_id, category, nota_extra=note, tenant_id=tenant_id)

    def discard_pending_movement(self, tenant_id: str, pending_id: str, reason: str = "") -> Any:
        return descartar_movimiento_pendiente(pending_id, motivo=reason, tenant_id=tenant_id)

    def create_snapshot(self, tenant_id: str, origin: str = "Mobile", date: Any = None) -> Any:
        return generar_snapshot_saldos(origen=origin, fecha=date, tenant_id=tenant_id)
