import argparse
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import config
from domain.finance_models import AccountRecord, DebtRecord, PendingMovementRecord, TransactionRecord
from repositories.airtable_repository import AirtableFinanceRepository


def connect(database_url):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("Install psycopg to run Postgres migrations: pip install psycopg[binary]") from exc
    return psycopg.connect(database_url)


def fetch_one(cursor, sql, params):
    cursor.execute(sql, params)
    return cursor.fetchone()


def ensure_tenant(cursor, tenant_id):
    row = fetch_one(cursor, "select id from tenants where legacy_tenant_id = %s or id::text = %s", (tenant_id, tenant_id))
    if row:
        return row[0]
    row = fetch_one(cursor, "insert into tenants (legacy_tenant_id, name, base_currency) values (%s, %s, %s) returning id", (tenant_id, tenant_id, config.BASE_CURRENCY))
    return row[0]


def ensure_category(cursor, tenant_uuid, name, transaction_type):
    row = fetch_one(cursor, "select id from categories where tenant_id = %s and lower(name) = lower(%s) and transaction_type = %s", (tenant_uuid, name, transaction_type))
    if row:
        cursor.execute("update categories set is_active = true, updated_at = now() where id = %s", (row[0],))
        return row[0]
    row = fetch_one(cursor, "insert into categories (tenant_id, name, transaction_type, is_active) values (%s, %s, %s, true) returning id", (tenant_uuid, name, transaction_type))
    return row[0]


def ensure_account(cursor, tenant_uuid, account):
    row = fetch_one(
        cursor,
        """
        insert into accounts (tenant_id, name, account_type, currency, current_balance, status)
        values (%s, %s, %s, %s, %s, 'active')
        on conflict (tenant_id, name)
        do update set account_type = excluded.account_type, currency = excluded.currency, current_balance = excluded.current_balance, status = 'active', updated_at = now()
        returning id
        """,
        (tenant_uuid, account.name, account.account_type, account.currency, account.balance),
    )
    return row[0]


def migrate_tenant(tenant_id, database_url, apply=False):
    source = AirtableFinanceRepository()
    accounts_summary = source.get_accounts_summary(tenant_id)
    accounts = [AccountRecord.from_legacy(row) for row in accounts_summary.get("cuentas", [])]
    expense_categories = source.list_categories(tenant_id, category_type="Gasto")
    income_categories = source.list_categories(tenant_id, category_type="Ingreso")
    transactions = [TransactionRecord.from_legacy(row) for row in source.list_transactions(tenant_id)]
    debts = [DebtRecord.from_legacy(row) for row in source.list_active_debts(tenant_id)]
    pending = [PendingMovementRecord.from_legacy(row) for row in source.list_pending_movements(tenant_id, limit=200, include_resolved=False)]

    print(f"tenant={tenant_id}")
    print(f"accounts={len(accounts)}")
    print(f"expense_categories={len(expense_categories)}")
    print(f"income_categories={len(income_categories)}")
    print(f"transactions={len(transactions)}")
    print(f"active_debts={len(debts)}")
    print(f"pending_movements={len(pending)}")

    if not apply:
        print("dry_run=true")
        return

    with connect(database_url) as conn:
        with conn.cursor() as cursor:
            tenant_uuid = ensure_tenant(cursor, tenant_id)
            account_ids = {account.name: ensure_account(cursor, tenant_uuid, account) for account in accounts}

            for item in expense_categories:
                ensure_category(cursor, tenant_uuid, item["original"], "expense")
            for item in income_categories:
                ensure_category(cursor, tenant_uuid, item["original"], "income")

            for debt in debts:
                cursor.execute(
                    """
                    insert into debts (tenant_id, legacy_debt_id, account_id, description, original_amount, outstanding_amount, currency, due_date, status)
                    values (%s, %s, %s, %s, %s, %s, %s, nullif(%s, '')::date, %s)
                    on conflict (tenant_id, legacy_debt_id)
                    do update set account_id = excluded.account_id, description = excluded.description, outstanding_amount = excluded.outstanding_amount, status = excluded.status, updated_at = now()
                    """,
                    (tenant_uuid, debt.debt_id, account_ids.get(debt.account), debt.description, debt.outstanding_amount, debt.outstanding_amount, debt.currency, debt.due_date, debt.status),
                )

            for transaction in transactions:
                category_id = ensure_category(cursor, tenant_uuid, transaction.category or "Other", transaction.transaction_type)
                cursor.execute(
                    """
                    insert into transactions (tenant_id, legacy_transaction_id, account_id, category_id, transaction_date, transaction_type, amount, currency, payment_method, note, status)
                    values (%s, %s, %s, %s, coalesce(nullif(%s, '')::date, current_date), %s, %s, %s, %s, %s, 'posted')
                    on conflict (tenant_id, legacy_transaction_id)
                    do update set account_id = excluded.account_id, category_id = excluded.category_id, amount = excluded.amount, note = excluded.note, updated_at = now()
                    """,
                    (tenant_uuid, transaction.transaction_id, account_ids.get(transaction.account), category_id, transaction.transaction_date[:10], transaction.transaction_type, transaction.amount, transaction.currency, transaction.payment_method, transaction.note),
                )

            for item in pending:
                cursor.execute(
                    """
                    insert into pending_movements (tenant_id, legacy_pending_id, detected_at, source_reference, account_hint, transaction_type, amount, currency, description, confidence_score, status, observation)
                    values (%s, %s, coalesce(nullif(%s, '')::timestamptz, now()), %s, %s, %s, %s, %s, %s, nullif(%s, '')::numeric, %s, %s)
                    on conflict (tenant_id, legacy_pending_id)
                    do update set status = excluded.status, observation = excluded.observation, updated_at = now()
                    """,
                    (tenant_uuid, item.pending_id, item.detected_at, item.reference, item.account, item.transaction_type, item.amount, item.currency, item.description, item.confidence, item.status, item.observation),
                )
        conn.commit()

    print("dry_run=false")
    print("migration_applied=true")


def main():
    parser = argparse.ArgumentParser(description="Migrate one tenant from Airtable to Postgres.")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--database-url", default=config.SUPABASE_DATABASE_URL)
    parser.add_argument("--apply", action="store_true", help="Write to Postgres. Without this flag, only prints counts.")
    args = parser.parse_args()

    if args.apply and not args.database_url:
        raise SystemExit("SUPABASE_DATABASE_URL or DATABASE_URL is required when using --apply.")

    migrate_tenant(args.tenant_id, args.database_url, apply=args.apply)


if __name__ == "__main__":
    main()
