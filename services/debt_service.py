from domain.finance_models import DebtRecord
from repositories import default_finance_repository


def get_mobile_debts(tenant_id, repository=None):
    repository = repository or default_finance_repository
    return [DebtRecord.from_legacy(item).to_mobile_payload() for item in repository.list_active_debts(tenant_id)]
