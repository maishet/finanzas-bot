import argparse
from dataclasses import dataclass
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import config
from repositories.airtable_repository import AirtableFinanceRepository
from repositories.postgres_repository import PostgresFinanceRepository
from utils.finance_format import parse_number


@dataclass(frozen=True)
class ValidationSnapshot:
    accounts_count: int
    total_assets: float
    total_liabilities: float
    net_worth: float
    active_debts_count: int
    active_debts_total: float
    transactions_count: int
    pending_count: int
    expense_categories_count: int
    income_categories_count: int


def snapshot(repository, tenant_id):
    accounts_summary = repository.get_accounts_summary(tenant_id)
    debts = repository.list_active_debts(tenant_id)
    transactions = repository.list_transactions(tenant_id)
    pending = repository.list_pending_movements(tenant_id, limit=200, include_resolved=False)
    expense_categories = repository.list_categories(tenant_id, category_type="Gasto")
    income_categories = repository.list_categories(tenant_id, category_type="Ingreso")

    return ValidationSnapshot(
        accounts_count=len(accounts_summary.get("cuentas", [])),
        total_assets=round(parse_number(accounts_summary.get("total_activos", 0)), 2),
        total_liabilities=round(parse_number(accounts_summary.get("total_pasivos", 0)), 2),
        net_worth=round(parse_number(accounts_summary.get("patrimonio", 0)), 2),
        active_debts_count=len(debts),
        active_debts_total=round(sum(parse_number(item.get("pendiente", 0)) for item in debts), 2),
        transactions_count=len(transactions),
        pending_count=len(pending),
        expense_categories_count=len(expense_categories),
        income_categories_count=len(income_categories),
    )


def main():
    parser = argparse.ArgumentParser(description="Compare Airtable and Postgres migration totals for a tenant.")
    parser.add_argument("--tenant-id", required=True, help="Tenant ID to validate.")
    parser.add_argument("--database-url", default=config.SUPABASE_DATABASE_URL, help="Postgres connection URL. Defaults to SUPABASE_DATABASE_URL/DATABASE_URL.")
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("SUPABASE_DATABASE_URL or DATABASE_URL is required.")

    airtable = snapshot(AirtableFinanceRepository(), args.tenant_id)
    postgres = snapshot(PostgresFinanceRepository(database_url=args.database_url), args.tenant_id)

    print("metric,airtable,postgres,match")
    for field in airtable.__dataclass_fields__:
        left = getattr(airtable, field)
        right = getattr(postgres, field)
        print(f"{field},{left},{right},{left == right}")


if __name__ == "__main__":
    main()
