from airtable_handler import parsear_numero
from repositories import default_finance_repository


def get_mobile_pending_movements(tenant_id, limit=50, repository=None):
    repository = repository or default_finance_repository
    limit = max(1, min(int(limit or 50), 200))
    rows = repository.list_pending_movements(tenant_id, limit=limit, include_resolved=False)
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
