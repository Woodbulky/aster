-- How a stored page was found: 'search' (a search engine ranked it, via research_scheme) or
-- 'link' (a URL the model or the user named: fetch_url / read_pdf). Only items quoted from
-- 'search' pages are shared across students (research_cache), so a link one student pastes can
-- never put "rules" in front of another (/guardrails, guardrail 8). Additive; old rows = 'link'.
alter table public.fetched_content
  add column via text not null default 'link' check (via in ('search', 'link'));
