from airtable_handler import _valor_campo, get_now, parsear_fecha, parsear_numero
from repositories import default_finance_repository


def _filter_datetime(value):
    if not value:
        return None
    if value.tzinfo:
        return value.astimezone(get_now().tzinfo).replace(tzinfo=None)
    return value


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


def get_mobile_transactions(tenant_id, limit=50, offset=0, date_from=None, date_to=None, repository=None):
    repository = repository or default_finance_repository
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    rows = repository.list_transactions(tenant_id)
    from_dt = _filter_datetime(parsear_fecha(date_from)) if date_from else None
    to_dt = _filter_datetime(parsear_fecha(date_to)) if date_to else None

    if date_from and not from_dt:
        raise ValueError("from invalido. Usa YYYY-MM-DD o DD/MM/AAAA.")
    if date_to and not to_dt:
        raise ValueError("to invalido. Usa YYYY-MM-DD o DD/MM/AAAA.")

    if from_dt or to_dt:
        filtered = []
        for row in rows:
            fecha = _filter_datetime(parsear_fecha(row.get("Fecha", "")))
            if not fecha:
                continue
            if from_dt and fecha < from_dt:
                continue
            if to_dt and fecha >= to_dt:
                continue
            filtered.append(row)
        rows = filtered

    def sort_key(row):
        fecha = parsear_fecha(row.get("Fecha", ""))
        if not fecha:
            return 0
        return fecha.timestamp()

    rows = sorted(rows, key=sort_key, reverse=True)
    return [_transaction_to_payload(row) for row in rows[offset : offset + limit]]
