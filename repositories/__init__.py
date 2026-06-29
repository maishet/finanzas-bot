import config


def build_finance_repository(backend="airtable"):
    if str(backend or "airtable").lower() in {"postgres", "supabase"}:
        from repositories.postgres_repository import PostgresFinanceRepository
        return PostgresFinanceRepository()
    from repositories.airtable_repository import AirtableFinanceRepository
    return AirtableFinanceRepository()


default_finance_repository = build_finance_repository(config.FINANCE_REPOSITORY_BACKEND)
