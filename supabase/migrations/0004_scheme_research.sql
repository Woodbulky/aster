-- M5: any scholarship, not only packs.
-- form_sessions.scheme_name: the scheme the user named when there is no knowledge pack
--   (live research). scheme_key stays the pack key.
-- research_results.scheme: which scheme the research is about (scheme_key, or scheme_name for
--   live research), so switching schemes sends the session back to research.
alter table public.form_sessions
  add column scheme_name text check (char_length(scheme_name) <= 200);

alter table public.research_results
  add column scheme text check (char_length(scheme) <= 200);
