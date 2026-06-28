from repositories import default_finance_repository
from utils.finance_format import parse_number


def create_transaction(tenant_id, payload, repository=None):
    repository = repository or default_finance_repository
    payload = payload or {}
    trans_id = repository.create_transaction(tenant_id, {
        "tipo": str(payload.get("tipo", "")).strip(),
        "monto": parse_number(payload.get("monto", 0)),
        "moneda": str(payload.get("moneda", "PEN")).strip().upper() or "PEN",
        "categoria_input": str(payload.get("categoria", "")).strip(),
        "subcategoria": str(payload.get("subcategoria", "")).strip(),
        "cuenta": str(payload.get("cuenta", "Efectivo")).strip() or "Efectivo",
        "metodo": str(payload.get("metodo", "Efectivo")).strip() or "Efectivo",
        "nota": str(payload.get("nota", "")).strip(),
        "fecha": payload.get("fecha"),
    })
    return {"id": trans_id}


def update_transaction(tenant_id, trans_id, payload, repository=None):
    repository = repository or default_finance_repository
    payload = payload or {}
    campo = str(payload.get("campo", "")).strip()
    if not campo:
        raise ValueError("campo es obligatorio.")
    return repository.update_transaction(tenant_id, trans_id, campo, payload.get("valor"))


def delete_transaction(tenant_id, trans_id, repository=None):
    repository = repository or default_finance_repository
    return repository.delete_transaction(tenant_id, trans_id)


def pay_debt(tenant_id, debt_id, payload, repository=None):
    repository = repository or default_finance_repository
    payload = payload or {}
    return repository.pay_debt(tenant_id, debt_id, {
        "monto": parse_number(payload.get("monto", 0)),
        "moneda_pago": str(payload.get("moneda", "PEN")).strip().upper() or "PEN",
        "cuenta_banco": str(payload.get("cuenta", "")).strip(),
        "nota": str(payload.get("nota", "")).strip(),
    })


def confirm_pending_movement(tenant_id, pending_id, payload, repository=None):
    repository = repository or default_finance_repository
    payload = payload or {}
    categoria = str(payload.get("categoria", "")).strip()
    if not categoria:
        raise ValueError("categoria es obligatoria.")
    return repository.confirm_pending_movement(tenant_id, pending_id, categoria, note=str(payload.get("nota", "")).strip())


def discard_pending_movement(tenant_id, pending_id, payload, repository=None):
    repository = repository or default_finance_repository
    payload = payload or {}
    return repository.discard_pending_movement(tenant_id, pending_id, reason=str(payload.get("motivo", "")).strip())


def create_snapshot(tenant_id, payload, repository=None):
    repository = repository or default_finance_repository
    payload = payload or {}
    return repository.create_snapshot(tenant_id, origin=str(payload.get("origen", "Mobile")).strip() or "Mobile", date=payload.get("fecha"))
