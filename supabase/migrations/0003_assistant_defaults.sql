-- Drift fix: the live DB had assistant_settings defaults 'sathi'/'Sathi' (pre-rename), while 0001_init
-- says 'aster'/'Aster'. Align the defaults and backfill rows that still hold the old default
-- (no client write path existed yet, so these are never user choices).
alter table public.assistant_settings alter column avatar_id set default 'aster';
alter table public.assistant_settings alter column assistant_name set default 'Aster';
update public.assistant_settings set avatar_id = 'aster', assistant_name = 'Aster'
 where avatar_id = 'sathi' and assistant_name = 'Sathi';
