-- M8: a profile proposal made from a resolved flag points at its evidence (the flag + the confirmed
-- field_values row, which points at the document lines). Confirming copies it into
-- profile_field_sources.source_ref (guardrail 2).
alter table public.profile_proposals add column source_ref jsonb not null default '{}';
