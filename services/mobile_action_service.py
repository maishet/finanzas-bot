from airtable_handler import (
    add_transaction,
    confirmar_movimiento_pendiente,
    descartar_movimiento_pendiente,
    editar_transaccion,
    eliminar_transaccion,
    generar_snapshot_saldos,
    pagar_deuda,
    parsear_numero,
)


def create_transaction(tenant_id, payload):
    payload = payload or {}
    trans_id = add_transaction(
        tipo=str(payload.get("tipo", "")).strip(),
        monto=parsear_numero(payload.get("monto", 0)),
        moneda=str(payload.get("moneda", "PEN")).strip().upper() or "PEN",
        categoria_input=str(payload.get("categoria", "")).strip(),
        subcategoria=str(payload.get("subcategoria", "")).strip(),
        cuenta=str(payload.get("cuenta", "Efectivo")).strip() or "Efectivo",
        metodo=str(payload.get("metodo", "Efectivo")).strip() or "Efectivo",
        nota=str(payload.get("nota", "")).strip(),
        fecha=payload.get("fecha"),
        tenant_id=tenant_id,
    )
    return {"id": trans_id}


def update_transaction(tenant_id, trans_id, payload):
    payload = payload or {}
    campo = str(payload.get("campo", "")).strip()
    if not campo:
        raise ValueError("campo es obligatorio.")
    return editar_transaccion(trans_id, campo, payload.get("valor"), tenant_id=tenant_id)


def delete_transaction(tenant_id, trans_id):
    return eliminar_transaccion(trans_id, tenant_id=tenant_id)


def pay_debt(tenant_id, debt_id, payload):
    payload = payload or {}
    return pagar_deuda(
        deuda_id=debt_id,
        monto=parsear_numero(payload.get("monto", 0)),
        moneda_pago=str(payload.get("moneda", "PEN")).strip().upper() or "PEN",
        cuenta_banco=str(payload.get("cuenta", "")).strip(),
        nota=str(payload.get("nota", "")).strip(),
        tenant_id=tenant_id,
    )


def confirm_pending_movement(tenant_id, pending_id, payload):
    payload = payload or {}
    categoria = str(payload.get("categoria", "")).strip()
    if not categoria:
        raise ValueError("categoria es obligatoria.")
    return confirmar_movimiento_pendiente(
        pending_id,
        categoria,
        nota_extra=str(payload.get("nota", "")).strip(),
        tenant_id=tenant_id,
    )


def discard_pending_movement(tenant_id, pending_id, payload):
    payload = payload or {}
    return descartar_movimiento_pendiente(
        pending_id,
        motivo=str(payload.get("motivo", "")).strip(),
        tenant_id=tenant_id,
    )


def create_snapshot(tenant_id, payload):
    payload = payload or {}
    return generar_snapshot_saldos(
        origen=str(payload.get("origen", "Mobile")).strip() or "Mobile",
        fecha=payload.get("fecha"),
        tenant_id=tenant_id,
    )
