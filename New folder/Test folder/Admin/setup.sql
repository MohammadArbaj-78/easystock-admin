-- Supabase SQL Editor me EK BAAR chalao.
create table if not exists public.api_usage_log (
    id               bigint generated always as identity primary key,
    store_id         bigint not null,
    api_name         text   not null,                 -- jaise 'gemini_invoice_scan'
    status           text   not null,                 -- 'success' ya 'error'
    model            text,
    duration_seconds double precision,
    error_message    text,
    created_at       timestamptz not null default now()
);

create index if not exists idx_api_usage_log_created_at on public.api_usage_log (created_at);
create index if not exists idx_api_usage_log_store_created on public.api_usage_log (store_id, created_at);

alter table public.api_usage_log enable row level security;

-- Main app (anon key) sirf LIKH sakti hai, padh nahi sakti.
-- Admin dashboard service_role key se padhta hai (wo RLS ko bypass karti hai).
create policy api_usage_log_insert_only
    on public.api_usage_log
    for insert
    to anon, authenticated
    with check (true);
