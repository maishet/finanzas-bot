drop index if exists idx_balance_snapshots_tenant_date;
drop table if exists balance_snapshots;

alter table connected_sources
  add column if not exists user_id uuid references users(id) on delete set null,
  add column if not exists email_address text,
  add column if not exists label_ids text[] not null default array['INBOX']::text[],
  add column if not exists allowed_senders text[] not null default '{}'::text[],
  add column if not exists filter_config jsonb not null default '{}'::jsonb,
  add column if not exists watch_history_id text,
  add column if not exists watch_expires_at timestamptz;

create table if not exists connected_source_filters (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  connected_source_id uuid not null references connected_sources(id) on delete cascade,
  filter_type text not null check (filter_type in ('sender_email', 'subject_contains', 'body_contains', 'account_hint', 'currency_hint')),
  filter_value text not null,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_connected_sources_tenant_type_status on connected_sources(tenant_id, source_type, status);
create index if not exists idx_connected_source_filters_source_active on connected_source_filters(connected_source_id, is_active);
create unique index if not exists idx_connected_source_filters_unique_value on connected_source_filters(connected_source_id, filter_type, lower(filter_value));

alter table tenants enable row level security;
alter table users enable row level security;
alter table tenant_memberships enable row level security;
alter table accounts enable row level security;
alter table categories enable row level security;
alter table debts enable row level security;
alter table connected_sources enable row level security;
alter table connected_source_filters enable row level security;
alter table pending_movements enable row level security;
alter table transactions enable row level security;
alter table debt_payments enable row level security;
alter table auth_codes enable row level security;
alter table audit_logs enable row level security;

do $$
declare
  table_name text;
begin
  foreach table_name in array array[
    'tenants', 'users', 'tenant_memberships', 'accounts', 'categories', 'debts',
    'connected_sources', 'connected_source_filters', 'pending_movements',
    'transactions', 'debt_payments', 'auth_codes', 'audit_logs'
  ] loop
    execute format('drop policy if exists backend_service_all on %I', table_name);
    execute format('create policy backend_service_all on %I for all to service_role using (true) with check (true)', table_name);
  end loop;
end $$;
