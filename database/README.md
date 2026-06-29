# Database

This folder contains the target Supabase/Postgres schema for Fint.

## Order

1. Apply migrations in `database/migrations/` in lexical order.
2. Keep Airtable as the active store until migration validation reports match per tenant.
3. Switch repositories only after read totals and action flows are validated.

## Naming

- Tables and columns are English `snake_case`.
- Internal enum/default values are English lowercase `snake_case`.
- Current mobile API payloads can remain compatible while repositories map to normalized records.

## Initial Migration

- `001_initial_schema.sql` creates tenants, users, memberships, accounts, categories, transactions, debts, debt payments, pending movements, connected sources, auth codes, and audit logs.
- `002_cutover_supabase_actions_and_gmail_sources.sql` removes historical snapshots, adds Gmail source filters, and enables defensive RLS policies for backend service access.
