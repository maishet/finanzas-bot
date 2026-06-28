from airtable_handler import parsear_numero
from repositories import default_finance_repository


def get_mobile_debts(tenant_id, repository=None):
    repository = repository or default_finance_repository
    debts = []
    for item in repository.list_active_debts(tenant_id):
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
