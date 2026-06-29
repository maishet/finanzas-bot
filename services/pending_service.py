from domain.finance_models import PendingMovementRecord
from repositories import default_finance_repository


def get_mobile_pending_movements(tenant_id, limit=50, repository=None):
    repository = repository or default_finance_repository
    limit = max(1, min(int(limit or 50), 200))
    rows = repository.list_pending_movements(tenant_id, limit=limit, include_resolved=False)
    return [PendingMovementRecord.from_legacy(row).to_mobile_payload() for row in rows]
