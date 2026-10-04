-- M8: serialise inserts per chain. Two concurrent inserts into one chain (the document pipeline
-- and the WS turn both audit the same session) could read the same last hash and fork the chain.
create or replace function public.audit_chain() returns trigger
language plpgsql set search_path = '' as $$
declare v_prev text;
begin
  perform pg_advisory_xact_lock(hashtextextended(
    coalesce(new.session_id::text, '') || '|' || coalesce(new.user_id::text, ''), 0));
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
