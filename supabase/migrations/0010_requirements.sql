-- Scheme requirements tracked one by one (app/verify/requirements.py).
-- documents.requirement_id: the requirement an upload is for, so two "other" documents (a hostel
--   certificate and a family declaration) are two tracked requirements, not one slot.
-- form_sessions.academic_year: the cycle the application is for ("2026-27"), fixed when the
--   scheme is chosen; knowledge packs and shared research are per cycle.
alter table public.documents
  add column requirement_id text check (requirement_id ~ '^[a-z0-9_]{1,64}$');

alter table public.form_sessions
  add column academic_year text check (academic_year ~ '^[0-9]{4}-[0-9]{2}$');
