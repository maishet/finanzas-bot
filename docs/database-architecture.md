# Fint Database Architecture

This document defines the target relational model for the future Supabase/Postgres migration. The current Airtable storage remains operational, but new repository boundaries and future migrations must use this model as the reference.

## Naming Rules

- Table names use English, plural, snake_case: `transactions`, `pending_movements`.
- Column names use English, snake_case: `tenant_id`, `created_at`, `due_date`.
- Enum/default values use English lowercase snake_case: `active`, `expense`, `credit_card`.
- API responses can keep Spanish fields temporarily for mobile compatibility, but repositories and database models should map to normalized English internally.
- Every financial table must include `tenant_id` and must be scoped by tenant in repositories.
- Money values should use `numeric(14,2)` or stricter decimal types, never float.
- Timestamps should be `timestamptz`; date-only business fields should be `date`.
- Prefer soft state transitions over physical deletion for user-owned finance records.

## Entity Relationship Diagram

```mermaid
erDiagram
  tenants ||--o{ tenant_memberships : owns
  users ||--o{ tenant_memberships : joins
  tenants ||--o{ accounts : has
  tenants ||--o{ categories : has
  tenants ||--o{ transactions : has
  tenants ||--o{ debts : has
  tenants ||--o{ pending_movements : has
  tenants ||--o{ balance_snapshots : has
  tenants ||--o{ auth_codes : has
  tenants ||--o{ connected_sources : has
  tenants ||--o{ audit_logs : has

  accounts ||--o{ transactions : records
  categories ||--o{ transactions : classifies
  debts ||--o{ transactions : generates
  debts ||--o{ debt_payments : receives
  accounts ||--o{ debt_payments : pays_from
  pending_movements ||--o| transactions : confirms_into
  connected_sources ||--o{ pending_movements : detects

  tenants {
    uuid id PK
    text name
    text base_currency
    text status
    timestamptz created_at
    timestamptz updated_at
  }

  users {
    uuid id PK
    text telegram_user_id
    text email
    text display_name
    text status
    timestamptz created_at
    timestamptz updated_at
  }

  tenant_memberships {
    uuid id PK
    uuid tenant_id FK
    uuid user_id FK
    text role
    text status
    timestamptz created_at
  }

  accounts {
    uuid id PK
    uuid tenant_id FK
    text name
    text account_type
    text currency
    numeric current_balance
    text status
    timestamptz created_at
    timestamptz updated_at
  }

  categories {
    uuid id PK
    uuid tenant_id FK
    text name
    text transaction_type
    text icon
    boolean is_active
    timestamptz created_at
    timestamptz updated_at
  }

  transactions {
    uuid id PK
    uuid tenant_id FK
    uuid account_id FK
    uuid category_id FK
    uuid debt_id FK
    uuid pending_movement_id FK
    date transaction_date
    text transaction_type
    numeric amount
    text currency
    text payment_method
    text note
    text status
    timestamptz created_at
    timestamptz updated_at
  }

  debts {
    uuid id PK
    uuid tenant_id FK
    uuid account_id FK
    text description
    numeric original_amount
    numeric outstanding_amount
    text currency
    date due_date
    date statement_date
    text debt_type
    text status
    timestamptz created_at
    timestamptz updated_at
  }

  debt_payments {
    uuid id PK
    uuid tenant_id FK
    uuid debt_id FK
    uuid account_id FK
    uuid transaction_id FK
    numeric amount
    text currency
    date payment_date
    text note
    timestamptz created_at
  }

  pending_movements {
    uuid id PK
    uuid tenant_id FK
    uuid connected_source_id FK
    uuid confirmed_transaction_id FK
    timestamptz detected_at
    text source_reference
    text account_hint
    text transaction_type
    numeric amount
    text currency
    text description
    numeric confidence_score
    text status
    text observation
    timestamptz created_at
    timestamptz updated_at
  }

  connected_sources {
    uuid id PK
    uuid tenant_id FK
    text source_type
    text provider
    text external_account_id
    text status
    timestamptz last_sync_at
    timestamptz created_at
    timestamptz updated_at
  }

  balance_snapshots {
    uuid id PK
    uuid tenant_id FK
    date snapshot_date
    numeric total_assets
    numeric total_liabilities
    numeric net_worth
    text origin
    timestamptz created_at
  }

  auth_codes {
    uuid id PK
    uuid tenant_id FK
    uuid user_id FK
    text code_hash
    timestamptz expires_at
    timestamptz used_at
    int attempts
    timestamptz created_at
  }

  audit_logs {
    uuid id PK
    uuid tenant_id FK
    uuid user_id FK
    text action
    text entity_type
    uuid entity_id
    jsonb metadata
    timestamptz created_at
  }
```

## Core Enums

- `tenant.status`: `active`, `suspended`, `deleted`
- `user.status`: `active`, `disabled`, `pending`
- `tenant_membership.role`: `owner`, `admin`, `member`, `viewer`
- `account.account_type`: `cash`, `bank_account`, `credit_card`, `loan`, `investment`, `other`
- `category.transaction_type`: `income`, `expense`
- `transaction.transaction_type`: `income`, `expense`, `transfer`, `debt_payment`, `adjustment`
- `transaction.status`: `posted`, `voided`, `pending_review`
- `debt.debt_type`: `credit_card`, `loan`, `service`, `installment`, `other`
- `debt.status`: `active`, `paid`, `overdue`, `cancelled`
- `pending_movement.status`: `pending`, `confirmed`, `discarded`
- `connected_source.source_type`: `gmail`, `outlook`, `telegram`, `manual`, `bank_integration`
- `connected_source.status`: `active`, `paused`, `error`, `revoked`

## Migration Notes From Airtable

- Airtable `TenantID` maps to `tenants.id` or a temporary `legacy_tenant_id` during migration.
- Airtable Spanish values such as `Gasto`, `Ingreso`, `Activo`, `Efectivo` must be mapped to English enum values at repository/migration boundaries.
- Historical categories must not be physically deleted. Used categories should be marked with `is_active = false` when hidden from selectors.
- Existing API payloads can remain Spanish during the mobile transition, but the repository should return normalized internal records once Postgres is introduced.
- Balance-changing actions must write `audit_logs` when Postgres becomes the primary store.

## Repository Boundary

Application services should depend on repository interfaces, not on Airtable or Supabase directly.

```text
api handlers
  -> services: validation, business rules, API payload mapping
  -> repositories: persistence abstraction
  -> storage adapters: Airtable now, Postgres later
```

The current Python phase introduces the boundary incrementally. The future TypeScript backend should keep the same separation with typed schemas and database migrations.

## Phase 6 Implementation Status

- `repositories/` contains the persistence boundary and the current Airtable adapter.
- `domain/finance_models.py` contains normalized internal records with English field names and enum values.
- `utils/finance_format.py` contains reusable parsing/normalization helpers independent from Airtable.
- Mobile API payloads remain backward-compatible while services map internal normalized records to current response shapes.
- Direct repository tests cover idempotent category creation and adapter delegation.
