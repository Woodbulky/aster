-- M8: with 0005's lock, the id default (taken before the lock) can be lower than the id of a row
-- that committed first, so `order by id desc` would pick the wrong chain head and fork the chain.
-- Take the id after the lock: the lock is held until commit, so ids follow the chain order.
create or replace function public.audit_chain() returns trigger
language plpgsql set search_path = '' as $$
declare v_prev text;
begin
  perform pg_advisory_xact_lock(hashtextextended(
    coalesce(new.session_id::text, '') || '|' || coalesce(new.user_id::text, ''), 0));
  new.id := nextval('public.audit_events_id_seq');
  select a.hash into v_prev from public.audit_events a
   where a.session_id is not distinct from new.session_id and a.user_id is not distinct from new.user_id
   order by a.id desc limit 1;
  new.prev_hash := coalesce(v_prev, 'GENESIS');
  -- created_at::text depends on the TimeZone of the writing connection (PostgREST: UTC);
  -- app/audit.py reads it back with the same cast.
  new.hash := encode(extensions.digest(
    new.prev_hash || '|' || new.actor || '|' || new.action || '|' || coalesce(new.payload::text,'') || '|' || new.created_at::text,
    'sha256'), 'hex');
  return new;
end $$;
