-- Live research shared across students: the quote-checked rules and documents found for a scheme
-- (public web facts only: no user data, no user_id). A second student choosing the same scheme
-- gets them at once instead of 4-6 LLM rounds. Items keep their source URL, quote, site and the
-- date the page was read; the UI still labels them "Unverified".
-- RLS on with no policies: only the backend (service key) reads or writes it.
create table public.research_cache (
  scheme_norm text primary key check (char_length(scheme_norm) between 1 and 200),
  scheme_name text not null check (char_length(scheme_name) <= 200),
  items jsonb not null,
  saved_at timestamptz not null default now(),
  expires_at timestamptz not null
);

alter table public.research_cache enable row level security;
