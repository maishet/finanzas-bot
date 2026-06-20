from airtable_handler import obtener_deudas_activas, parsear_numero


def get_mobile_debts(tenant_id):
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
