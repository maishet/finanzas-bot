from datetime import datetime

import config
from domain.finance_models import AccountRecord
from repositories import default_finance_repository
from utils.finance_format import parse_number


def get_mobile_accounts(tenant_id, repository=None):
    repository = repository or default_finance_repository
    resumen = repository.get_accounts_summary(tenant_id)
    return [AccountRecord.from_legacy(item).to_mobile_payload() for item in resumen.get("cuentas", [])]


def get_mobile_summary(tenant_id, repository=None):
    repository = repository or default_finance_repository
    resumen = repository.get_accounts_summary(tenant_id)
    ahora = datetime.now()
    balance = repository.get_month_balance(ahora.month, ahora.year, tenant_id)
    deudas = repository.list_active_debts(tenant_id)
    total_deuda_pendiente = round(sum(parse_number(d.get("pendiente", 0)) for d in deudas), 2)

    return {
        "tenant_id": tenant_id,
        "base_currency": config.BASE_CURRENCY,
        "accounts": {
            "total_activos": round(parse_number(resumen.get("total_activos", 0)), 2),
            "total_pasivos": round(parse_number(resumen.get("total_pasivos", 0)), 2),
            "patrimonio": round(parse_number(resumen.get("patrimonio", 0)), 2),
            "count": len(resumen.get("cuentas", [])),
        },
        "month": {
            "mes": balance.get("mes"),
            "anio": balance.get("año"),
            "ingresos": round(parse_number(balance.get("ingresos", 0)), 2),
            "gastos": round(parse_number(balance.get("gastos", 0)), 2),
            "ahorro": round(parse_number(balance.get("ahorro", 0)), 2),
        },
        "debts": {
            "active_count": len(deudas),
            "pending_total": total_deuda_pendiente,
        },
    }
