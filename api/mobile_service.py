from services.mobile_action_service import (
    confirm_pending_movement,
    create_snapshot,
    create_transaction,
    delete_transaction,
    discard_pending_movement,
    pay_debt,
    update_transaction,
)
from services.mobile_read_service import (
    get_accounts,
    get_debts,
    get_me,
    get_pending_movements,
    get_summary,
    get_transactions,
    get_version,
)


def get_version_payload():
    return get_version()


def get_me_payload(tenant_id):
    return get_me(tenant_id)


def get_accounts_payload(tenant_id):
    return get_accounts(tenant_id)


def get_summary_payload(tenant_id):
    return get_summary(tenant_id)


def get_transactions_payload(tenant_id, limit=50, date_from=None, date_to=None):
    return get_transactions(tenant_id, limit=limit, date_from=date_from, date_to=date_to)


def get_debts_payload(tenant_id):
    return get_debts(tenant_id)


def get_pending_movements_payload(tenant_id, limit=50):
    return get_pending_movements(tenant_id, limit=limit)


def create_transaction_action(tenant_id, payload):
    return create_transaction(tenant_id, payload)


def update_transaction_action(tenant_id, trans_id, payload):
    return update_transaction(tenant_id, trans_id, payload)


def delete_transaction_action(tenant_id, trans_id):
    return delete_transaction(tenant_id, trans_id)


def pay_debt_action(tenant_id, debt_id, payload):
    return pay_debt(tenant_id, debt_id, payload)


def confirm_pending_movement_action(tenant_id, pending_id, payload):
    return confirm_pending_movement(tenant_id, pending_id, payload)


def discard_pending_movement_action(tenant_id, pending_id, payload):
    return discard_pending_movement(tenant_id, pending_id, payload)


def create_snapshot_action(tenant_id, payload):
    return create_snapshot(tenant_id, payload)
