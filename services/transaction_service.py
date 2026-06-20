from airtable_handler import _leer_records_cacheados, _valor_campo, parsear_fecha, parsear_numero, trans_ws


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


def get_mobile_transactions(tenant_id, limit=50):
    limit = max(1, min(int(limit or 50), 200))
    rows = _leer_records_cacheados(trans_ws, "transacciones_records", tenant_id=tenant_id)

    def sort_key(row):
        fecha = parsear_fecha(row.get("Fecha", ""))
        if not fecha:
            return 0
        return fecha.timestamp()

    rows = sorted(rows, key=sort_key, reverse=True)
    return [_transaction_to_payload(row) for row in rows[:limit]]
