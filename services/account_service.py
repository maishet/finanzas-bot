from datetime import datetime

import config
from airtable_handler import obtener_balance_mes, obtener_deudas_activas, obtener_resumen_cuentas, parsear_numero


def get_mobile_accounts(tenant_id):
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


def get_mobile_summary(tenant_id):
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
