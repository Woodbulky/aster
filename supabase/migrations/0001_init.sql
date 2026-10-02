-- Aster initial schema. Apply via Supabase MCP apply_migration (name: 0001_init).
create extension if not exists pgcrypto with schema extensions;

-- ---------- helpers ----------
create or replace function public.set_updated_at() returns trigger
language plpgsql set search_path = '' as $$
begin new.updated_at := now(); return new; end $$;

-- ---------- profile ----------
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  full_name text,
  full_name_local text,
  dob date,
  gender text,
  mobile text,
  preferred_language text not null default 'mr' check (preferred_language in ('mr','hi','en')),
  domicile_state text,
  district text,
  taluka text,
  category text,
  caste text,
  religion text,
  annual_family_income numeric,
  ssc_board text, ssc_year int, ssc_percentage numeric,
  hsc_board text, hsc_year int, hsc_percentage numeric,
  current_course text, current_year int, institute_name text,
  aadhaar_last4 text check (aadhaar_last4 ~ '^[0-9]{4}$'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create trigger profiles_updated before update on public.profiles for each row execute function public.set_updated_at();

create table public.profile_field_sources (
  user_id uuid not null references auth.users(id) on delete cascade,
  field_key text not null,
  source_type text not null check (source_type in ('voice','text','document','aadhaar_qr','manual')),
  source_ref jsonb not null default '{}',
  confirmed_at timestamptz not null default now(),
  primary key (user_id, field_key)
);

create table public.assistant_settings (
  user_id uuid primary key references auth.users(id) on delete cascade,
  avatar_id text not null default 'aster',
  assistant_name text not null default 'Aster',
  language text not null default 'mr' check (language in ('mr','hi','en')),
  voice text,
  updated_at timestamptz not null default now()
);
create trigger assistant_updated before update on public.assistant_settings for each row execute function public.set_updated_at();

create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  insert into public.profiles (id, email) values (new.id, new.email) on conflict do nothing;
  insert into public.assistant_settings (user_id) values (new.id) on conflict do nothing;
  return new;
end $$;
create trigger on_auth_user_created after insert on auth.users for each row execute function public.handle_new_user();

-- ---------- sessions & conversation ----------
create table public.form_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  portal text,
  scheme_key text,
  portal_url text,
  phase text not null default 'onboarding' check (phase in ('onboarding','choose_form','research','eligibility','documents','verification','ready','form_fill','done')),
  status text not null default 'active' check (status in ('active','done','abandoned')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create trigger sessions_updated before update on public.form_sessions for each row execute function public.set_updated_at();

create table public.messages (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.form_sessions(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('user','assistant','tool','system')),
  content text,
  lang text,
  input_mode text check (input_mode in ('voice','text','ui')),
  provider text,
  tool_name text,
  tool_payload jsonb,
  created_at timestamptz not null default now()
);

create table public.profile_proposals (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  session_id uuid references public.form_sessions(id) on delete cascade,
  updates jsonb not null,
  evidence text not null check (evidence in ('voice','text','document')),
  message_id uuid references public.messages(id) on delete set null,
  status text not null default 'pending' check (status in ('pending','accepted','rejected')),
  created_at timestamptz not null default now()
);

-- ---------- research ----------
create table public.fetched_content (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.form_sessions(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  url text not null,
  title text,
  text text not null,
  fetched_at timestamptz not null default now()
);

create table public.research_results (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.form_sessions(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  kind text not null check (kind in ('eligibility','documents')),
  origin text not null check (origin in ('pack','live')),
  items jsonb not null,
  created_at timestamptz not null default now()
);

-- ---------- documents & fields ----------
create table public.documents (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.form_sessions(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  doc_type text check (doc_type in ('aadhaar','ssc_marksheet','hsc_marksheet','income_certificate','caste_certificate','caste_validity','domicile_certificate','bank_passbook','fee_receipt','admission_letter','gap_certificate','other')),
  storage_path text not null,
  mime text,
  sha256 text,
  page_count int,
  status text not null default 'uploaded' check (status in ('uploaded','processing','extracted','failed')),
  quality jsonb,
  ocr jsonb,
  error text,
  created_at timestamptz not null default now()
);

create table public.flags (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.form_sessions(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  type text not null check (type in ('contradiction','missing_doc','low_confidence','rule')),
  severity text not null check (severity in ('block','warn')),
  field_key text,
  reason_code text not null,
  details jsonb not null default '{}',
  status text not null default 'open' check (status in ('open','resolved','acknowledged')),
  resolution jsonb,
  created_at timestamptz not null default now(),
  resolved_at timestamptz
);

create table public.field_values (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.form_sessions(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  field_key text not null,
  value text,
  value_normalized text,
  source_type text not null check (source_type in ('document','voice','text','profile','aadhaar_qr','resolution')),
  source_ref jsonb not null default '{}',
  confidence numeric,
  status text not null default 'candidate' check (status in ('candidate','confirmed','rejected')),
  resolves_flag_id uuid references public.flags(id) on delete set null,
  resolution_reason text,
  created_at timestamptz not null default now()
);

create table public.rule_evaluations (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.form_sessions(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  rule_id text not null,
  rule_version text not null,
  inputs jsonb not null,
  result boolean not null,
  created_at timestamptz not null default now()
);

-- ---------- consent & audit ----------
create table public.consents (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  scope text not null,
  granted boolean not null,
  explanation_version text not null,
  created_at timestamptz not null default now()
);

create table public.audit_events (
  id bigserial primary key,
  user_id uuid references auth.users(id) on delete cascade,
  session_id uuid references public.form_sessions(id) on delete cascade,
  actor text not null,          -- 'user' | 'agent' | 'system'
  action text not null,
  payload jsonb,
  prev_hash text,
  hash text,
  created_at timestamptz not null default now()
);

create or replace function public.audit_chain() returns trigger
language plpgsql set search_path = '' as $$
declare v_prev text;
begin
  select a.hash into v_prev from public.audit_events a
   where a.session_id is not distinct from new.session_id and a.user_id is not distinct from new.user_id
   order by a.id desc limit 1;
  new.prev_hash := coalesce(v_prev, 'GENESIS');
  new.hash := encode(extensions.digest(
    new.prev_hash || '|' || new.actor || '|' || new.action || '|' || coalesce(new.payload::text,'') || '|' || new.created_at::text,
    'sha256'), 'hex');
  return new;
end $$;
create trigger audit_chain_trg before insert on public.audit_events for each row execute function public.audit_chain();

-- ---------- indexes ----------
create index on public.form_sessions (user_id);
create index on public.messages (session_id, created_at);
create index on public.documents (session_id);
create index on public.field_values (session_id, field_key);
create index on public.flags (session_id, status);
create index on public.rule_evaluations (session_id);
create index on public.research_results (session_id);
create index on public.fetched_content (session_id);
create index on public.audit_events (session_id, id);
create index on public.profile_proposals (user_id, status);

-- ---------- RLS: clients READ own rows; all writes go through the backend (service key) ----------
do $$
declare t text;
begin
  foreach t in array array['profiles','profile_field_sources','assistant_settings','form_sessions','messages',
    'profile_proposals','fetched_content','research_results','documents','flags','field_values',
    'rule_evaluations','consents','audit_events']
  loop
    execute format('alter table public.%I enable row level security', t);
  end loop;
end $$;

create policy "own profile read" on public.profiles for select to authenticated using (id = (select auth.uid()));
create policy "own sources read" on public.profile_field_sources for select to authenticated using (user_id = (select auth.uid()));
create policy "own assistant read" on public.assistant_settings for select to authenticated using (user_id = (select auth.uid()));
create policy "own sessions read" on public.form_sessions for select to authenticated using (user_id = (select auth.uid()));
create policy "own messages read" on public.messages for select to authenticated using (user_id = (select auth.uid()));
create policy "own proposals read" on public.profile_proposals for select to authenticated using (user_id = (select auth.uid()));
create policy "own fetched read" on public.fetched_content for select to authenticated using (user_id = (select auth.uid()));
create policy "own research read" on public.research_results for select to authenticated using (user_id = (select auth.uid()));
create policy "own documents read" on public.documents for select to authenticated using (user_id = (select auth.uid()));
create policy "own flags read" on public.flags for select to authenticated using (user_id = (select auth.uid()));
create policy "own fields read" on public.field_values for select to authenticated using (user_id = (select auth.uid()));
create policy "own rule evals read" on public.rule_evaluations for select to authenticated using (user_id = (select auth.uid()));
create policy "own consents read" on public.consents for select to authenticated using (user_id = (select auth.uid()));
create policy "own audit read" on public.audit_events for select to authenticated using (user_id = (select auth.uid()));

-- ---------- storage ----------
insert into storage.buckets (id, name, public) values ('documents', 'documents', false) on conflict (id) do nothing;
create policy "own docs upload" on storage.objects for insert to authenticated
  with check (bucket_id = 'documents' and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy "own docs read" on storage.objects for select to authenticated
  using (bucket_id = 'documents' and (storage.foldername(name))[1] = (select auth.uid())::text);

-- ---------- endpoint discovery (GPU worker + phone API) ----------
create table if not exists public.gpu_endpoints (
  name text primary key,
  url text not null,
  models jsonb,
  last_seen timestamptz default now()
);
create table if not exists public.gpu_secrets (id int primary key default 1, secret text not null);
create table if not exists public.public_endpoints (
  name text primary key,
  url text not null,
  last_seen timestamptz default now()
);
alter table public.gpu_endpoints enable row level security;     -- backend (service key) only
alter table public.gpu_secrets enable row level security;       -- nobody via API
alter table public.public_endpoints enable row level security;
create policy "anyone reads public endpoints" on public.public_endpoints for select to anon, authenticated using (true);

create or replace function public.register_gpu(p_secret text, p_name text, p_url text, p_models jsonb)
returns void language plpgsql security definer set search_path = public as $$
begin
  if p_secret is distinct from (select secret from public.gpu_secrets where id = 1) then
    raise exception 'unauthorized';
  end if;
  insert into public.gpu_endpoints (name, url, models, last_seen) values (p_name, p_url, p_models, now())
  on conflict (name) do update set url = excluded.url, models = excluded.models, last_seen = now();
end $$;

create or replace function public.register_public_endpoint(p_secret text, p_name text, p_url text)
returns void language plpgsql security definer set search_path = public as $$
begin
  if p_secret is distinct from (select secret from public.gpu_secrets where id = 1) then
    raise exception 'unauthorized';
  end if;
  insert into public.public_endpoints (name, url, last_seen) values (p_name, p_url, now())
  on conflict (name) do update set url = excluded.url, last_seen = now();
end $$;

grant execute on function public.register_gpu(text, text, text, jsonb) to anon;
grant execute on function public.register_public_endpoint(text, text, text) to anon;
-- NOTE: set the shared secret manually in the SQL editor (never commit it):
--   insert into public.gpu_secrets (id, secret) values (1, '<GPU_REGISTER_SECRET>')
--   on conflict (id) do update set secret = excluded.secret;
