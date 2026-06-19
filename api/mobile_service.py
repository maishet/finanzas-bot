from datetime import datetime

import config
from airtable_handler import (
    _leer_records_cacheados,
    _valor_campo,
    listar_movimientos_pendientes,
    obtener_balance_mes,
    obtener_deudas_activas,
    obtener_resumen_cuentas,
    parsear_fecha,
    parsear_numero,
    trans_ws,
)
from tenant_context import list_users


API_VERSION = "0.1.0"


def get_version_payload():
    return {
        "ok": True,
        "name": "finanzas-bot-mobile-api",
        "version": API_VERSION,
        "phase": "phase-2-otp-jwt",
        "auth": "telegram-otp-jwt",
    }


def get_me_payload(tenant_id):
    tenant_id = str(tenant_id or "").strip()
    for user in list_users():
        if str(user.get("tenant_id", "")).strip() == tenant_id:
            return {
                "tenant_id": tenant_id,
                "telegram_user_id": user.get("telegram_user_id", ""),
                "nombre": user.get("nombre", ""),
                "estado": user.get("estado", ""),
                "rol": user.get("rol", ""),
                "setup_completo": bool(user.get("setup_completo")),
                "gmail_enabled": bool(user.get("gmail_enabled")),
                "voice_enabled": bool(user.get("voice_enabled")),
            }

    if tenant_id == str(config.SYSTEM_TENANT_ID or "").strip():
        return {
            "tenant_id": tenant_id,
            "telegram_user_id": str(config.ADMIN_TELEGRAM_USER_ID),
            "nombre": "Admin principal",
            "estado": "Activo",
            "rol": "Admin",
            "setup_completo": True,
            "gmail_enabled": bool(config.GMAIL_PUSH_ENABLED),
            "voice_enabled": bool(config.VOICE_ENABLED),
        }

    return {
        "tenant_id": tenant_id,
        "telegram_user_id": "",
        "nombre": "",
        "estado": "Desconocido",
        "rol": "",
        "setup_completo": False,
        "gmail_enabled": False,
        "voice_enabled": False,
    }


def get_accounts_payload(tenant_id):
    resumen = obtener_resumen_cuentas(tenant_id=tenant_id)
    accounts = []
    for item in resumen.get("cuentas", []):
        accounts.append({
            "nombre": item.get("nombre", ""),
            "tipo": item.get("tipo", ""),
            "saldo": round(parsear_numero(item.get("saldo", 0)), 2),
            "moneda": item.get("moneda", "PEN"),
        })
    return accounts


def get_summary_payload(tenant_id):
    resumen = obtener_resumen_cuentas(tenant_id=tenant_id)
    ahora = datetime.now()
    balance = obtener_balance_mes(ahora.month, ahora.year, tenant_id=tenant_id)
    deudas = obtener_deudas_activas(tenant_id=tenant_id)
    total_deuda_pendiente = round(sum(parsear_numero(d.get("pendiente", 0)) for d in deudas), 2)

    return {
        "tenant_id": tenant_id,
        "base_currency": config.BASE_CURRENCY,
        "accounts": {
            "total_activos": round(parsear_numero(resumen.get("total_activos", 0)), 2),
            "total_pasivos": round(parsear_numero(resumen.get("total_pasivos", 0)), 2),
            "patrimonio": round(parsear_numero(resumen.get("patrimonio", 0)), 2),
            "count": len(resumen.get("cuentas", [])),
        },
        "month": {
            "mes": balance.get("mes"),
            "anio": balance.get("año"),
            "ingresos": round(parsear_numero(balance.get("ingresos", 0)), 2),
            "gastos": round(parsear_numero(balance.get("gastos", 0)), 2),
            "ahorro": round(parsear_numero(balance.get("ahorro", 0)), 2),
        },
        "debts": {
            "active_count": len(deudas),
            "pending_total": total_deuda_pendiente,
        },
    }


def _transaction_to_payload(row):
    fecha_raw = row.get("Fecha", "")
    fecha_dt = parsear_fecha(fecha_raw)
    return {
        "id": str(row.get("ID", "")).strip(),
        "fecha": fecha_dt.isoformat(timespec="seconds") if fecha_dt else str(fecha_raw or ""),
        "tipo": str(row.get("Tipo", "")).strip(),
        "monto": round(parsear_numero(row.get("Monto", 0)), 2),
        "moneda": str(row.get("Moneda", "PEN")).strip().upper() or "PEN",
        "categoria": str(_valor_campo(row, "Categoría", "Categoria", default="")).strip(),
        "subcategoria": str(_valor_campo(row, "Subcategoría", "Subcategoria", default="")).strip(),
        "cuenta": str(row.get("Cuenta", "")).strip(),
        "metodo": str(_valor_campo(row, "Método", "Metodo", default="")).strip(),
        "nota": str(row.get("Nota", "")).strip(),
        "deuda_id": str(row.get("DeudaID", "")).strip(),
    }


def get_transactions_payload(tenant_id, limit=50):
    limit = max(1, min(int(limit or 50), 200))
    rows = _leer_records_cacheados(trans_ws, "transacciones_records", tenant_id=tenant_id)

    def sort_key(row):
        fecha = parsear_fecha(row.get("Fecha", ""))
        if not fecha:
            return 0
        return fecha.timestamp()

    rows = sorted(
        rows,
        key=sort_key,
        reverse=True,
    )
    return [_transaction_to_payload(row) for row in rows[:limit]]


def get_debts_payload(tenant_id):
    debts = []
    for item in obtener_deudas_activas(tenant_id=tenant_id):
        debts.append({
            "id": item.get("id", ""),
            "descripcion": item.get("descripcion", ""),
            "pendiente": round(parsear_numero(item.get("pendiente", 0)), 2),
            "moneda": item.get("moneda", "PEN"),
            "vencimiento": item.get("vencimiento", ""),
            "cuenta": item.get("cuenta", ""),
            "estado": item.get("estado", ""),
        })
    return debts


def get_pending_movements_payload(tenant_id, limit=50):
    limit = max(1, min(int(limit or 50), 200))
    rows = listar_movimientos_pendientes(limit=limit, include_resueltos=False, tenant_id=tenant_id)
    payload = []
    for row in rows:
        payload.append({
            "id": str(row.get("ID", "")).strip(),
            "fecha_detectada": str(row.get("FechaDetectada", "")).strip(),
            "fuente": str(row.get("Fuente", "")).strip(),
            "cuenta": str(row.get("Cuenta", "")).strip(),
            "tipo": str(row.get("Tipo", "")).strip(),
            "monto": round(parsear_numero(row.get("Monto", 0)), 2),
            "moneda": str(row.get("Moneda", "PEN")).strip().upper() or "PEN",
            "descripcion": str(row.get("Descripcion", "")).strip(),
            "referencia": str(row.get("Referencia", "")).strip(),
            "estado": str(row.get("Estado", "")).strip(),
            "confianza": str(row.get("Confianza", "")).strip(),
            "txid": str(row.get("TXID", "")).strip(),
            "observacion": str(row.get("Observacion", "")).strip(),
        })
    return payload
