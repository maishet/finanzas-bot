from domain.finance_models import TransactionRecord
from repositories import default_finance_repository
from utils.finance_format import get_now, parse_date


def _filter_datetime(value):
    if not value:
        return None
    if value.tzinfo:
        return value.astimezone(get_now().tzinfo).replace(tzinfo=None)
    return value


def get_mobile_transactions(tenant_id, limit=50, offset=0, date_from=None, date_to=None, repository=None):
    repository = repository or default_finance_repository
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    rows = repository.list_transactions(tenant_id)
    from_dt = _filter_datetime(parse_date(date_from)) if date_from else None
    to_dt = _filter_datetime(parse_date(date_to)) if date_to else None

    if date_from and not from_dt:
        raise ValueError("from invalido. Usa YYYY-MM-DD o DD/MM/AAAA.")
    if date_to and not to_dt:
        raise ValueError("to invalido. Usa YYYY-MM-DD o DD/MM/AAAA.")

    if from_dt or to_dt:
        filtered = []
        for row in rows:
            fecha = _filter_datetime(parse_date(row.get("Fecha", "")))
            if not fecha:
                continue
            if from_dt and fecha < from_dt:
                continue
            if to_dt and fecha >= to_dt:
                continue
            filtered.append(row)
        rows = filtered

    def sort_key(row):
        fecha = parse_date(row.get("Fecha", ""))
        if not fecha:
            return 0
        return fecha.timestamp()

    rows = sorted(rows, key=sort_key, reverse=True)
    return [TransactionRecord.from_legacy(row).to_mobile_payload() for row in rows[offset : offset + limit]]
