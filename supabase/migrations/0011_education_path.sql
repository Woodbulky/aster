-- Education path facts (app/agent/phases.py, app/agent/tools/eligibility.py). Stable across
-- applications, so they live on the profile; asked only when a scheme needs them (never upfront
-- beyond entry_qualification).
-- entry_qualification: what the current course was joined after. ssc = after 10th (diploma, ITI,
--   11th-12th), hsc = after 12th, diploma = after a diploma (lateral entry), graduation = after a
--   degree. It decides whether 12th details apply at all.
-- admission_year: the calendar year the current course was joined (2026 for the 2026-27 cycle).
-- course_mode: regular, part_time, distance (incl. correspondence / open university) or online.
alter table public.profiles
  add column entry_qualification text check (entry_qualification in ('ssc','hsc','diploma','graduation')),
  add column admission_year int check (admission_year between 2000 and 2100),
  add column course_mode text check (course_mode in ('regular','part_time','distance','online'));
