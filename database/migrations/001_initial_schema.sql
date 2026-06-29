create extension if not exists pgcrypto;

create table if not exists tenants (
  id uuid primary key default gen_random_uuid(),
  legacy_tenant_id text unique,
  name text not null,
  base_currency text not null default 'PEN',
  status text not null default 'active' check (status in ('active', 'suspended', 'deleted')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  telegram_user_id text unique,
  email text unique,
  display_name text,
  status text not null default 'active' check (status in ('active', 'disabled', 'pending')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists tenant_memberships (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  user_id uuid not null references users(id) on delete cascade,
  role text not null default 'owner' check (role in ('owner', 'admin', 'member', 'viewer')),
  status text not null default 'active' check (status in ('active', 'disabled', 'pending')),
  created_at timestamptz not null default now(),
  unique (tenant_id, user_id)
);

create table if not exists accounts (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  legacy_account_id text,
  name text not null,
  account_type text not null default 'bank_account' check (account_type in ('cash', 'bank_account', 'credit_card', 'loan', 'investment', 'other')),
  currency text not null default 'PEN',
  current_balance numeric(14,2) not null default 0,
  status text not null default 'active' check (status in ('active', 'inactive', 'closed', 'deleted')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, name)
);

create table if not exists categories (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  legacy_category_id text,
  name text not null,
  transaction_type text not null check (transaction_type in ('income', 'expense')),
  icon text,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists debts (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  account_id uuid references accounts(id) on delete set null,
  legacy_debt_id text,
  description text not null,
  original_amount numeric(14,2) not null default 0,
  outstanding_amount numeric(14,2) not null default 0,
  currency text not null default 'PEN',
  due_date date,
  statement_date date,
  debt_type text not null default 'other' check (debt_type in ('credit_card', 'loan', 'service', 'installment', 'other')),
  status text not null default 'active' check (status in ('active', 'paid', 'overdue', 'cancelled')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, legacy_debt_id)
);

create table if not exists connected_sources (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  source_type text not null check (source_type in ('gmail', 'outlook', 'telegram', 'manual', 'bank_integration')),
  provider text,
  external_account_id text,
  status text not null default 'active' check (status in ('active', 'paused', 'error', 'revoked')),
  last_sync_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, source_type, external_account_id)
);

create table if not exists pending_movements (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  connected_source_id uuid references connected_sources(id) on delete set null,
  confirmed_transaction_id uuid,
  legacy_pending_id text,
  detected_at timestamptz not null default now(),
  source_reference text,
  account_hint text,
  transaction_type text not null check (transaction_type in ('income', 'expense')),
  amount numeric(14,2) not null,
  currency text not null default 'PEN',
  description text,
  confidence_score numeric(5,2),
  status text not null default 'pending' check (status in ('pending', 'confirmed', 'discarded')),
  observation text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, legacy_pending_id)
);

create table if not exists transactions (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  account_id uuid references accounts(id) on delete set null,
  category_id uuid references categories(id) on delete set null,
  debt_id uuid references debts(id) on delete set null,
  pending_movement_id uuid references pending_movements(id) on delete set null,
  legacy_transaction_id text,
  transaction_date date not null default current_date,
  transaction_type text not null check (transaction_type in ('income', 'expense', 'transfer', 'debt_payment', 'adjustment')),
  amount numeric(14,2) not null,
  currency text not null default 'PEN',
  payment_method text,
  note text,
  status text not null default 'posted' check (status in ('posted', 'voided', 'pending_review')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, legacy_transaction_id)
);

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'pending_movements_confirmed_transaction_id_fkey'
  ) then
    alter table pending_movements
      add constraint pending_movements_confirmed_transaction_id_fkey
      foreign key (confirmed_transaction_id) references transactions(id) on delete set null;
  end if;
end $$;

create table if not exists debt_payments (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  debt_id uuid not null references debts(id) on delete cascade,
  account_id uuid references accounts(id) on delete set null,
  transaction_id uuid references transactions(id) on delete set null,
  amount numeric(14,2) not null,
  currency text not null default 'PEN',
  payment_date date not null default current_date,
  note text,
  created_at timestamptz not null default now()
);

create table if not exists balance_snapshots (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  snapshot_date date not null default current_date,
  total_assets numeric(14,2) not null default 0,
  total_liabilities numeric(14,2) not null default 0,
  net_worth numeric(14,2) not null default 0,
  origin text not null default 'manual',
  created_at timestamptz not null default now()
);

create table if not exists auth_codes (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  user_id uuid references users(id) on delete cascade,
  code_hash text not null,
  expires_at timestamptz not null,
  used_at timestamptz,
  attempts int not null default 0,
  created_at timestamptz not null default now()
);

create table if not exists audit_logs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  user_id uuid references users(id) on delete set null,
  action text not null,
  entity_type text not null,
  entity_id uuid,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_accounts_tenant_status on accounts(tenant_id, status);
create unique index if not exists idx_categories_tenant_lower_name_type on categories(tenant_id, lower(name), transaction_type);
create index if not exists idx_categories_tenant_type_active on categories(tenant_id, transaction_type, is_active);
create index if not exists idx_transactions_tenant_date on transactions(tenant_id, transaction_date desc);
create index if not exists idx_transactions_tenant_category on transactions(tenant_id, category_id);
create index if not exists idx_debts_tenant_status_due on debts(tenant_id, status, due_date);
create index if not exists idx_pending_movements_tenant_status on pending_movements(tenant_id, status, detected_at desc);
create index if not exists idx_balance_snapshots_tenant_date on balance_snapshots(tenant_id, snapshot_date desc);
create index if not exists idx_audit_logs_tenant_created on audit_logs(tenant_id, created_at desc);
