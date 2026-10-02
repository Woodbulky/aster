-- Fixes from the Supabase advisors after 0001_init. Apply via MCP apply_migration (name: 0002_advisor_fixes).

-- SECURITY: trigger / platform helper functions must not be callable via /rest/v1/rpc.
-- (Triggers still fire; EXECUTE is not checked for trigger invocation.)
revoke execute on function public.handle_new_user() from public, anon, authenticated;
do $$
begin
  if to_regprocedure('public.rls_auto_enable()') is not null then
    revoke execute on function public.rls_auto_enable() from public, anon, authenticated;
  end if;
end $$;
-- Accepted risk: register_gpu / register_public_endpoint stay anon-callable (Kaggle + phone register
-- with the anon key); both check the shared secret in gpu_secrets.

-- PERFORMANCE: cover foreign keys.
create index if not exists audit_events_user_id_idx on public.audit_events (user_id);
create index if not exists consents_user_id_idx on public.consents (user_id);
create index if not exists documents_user_id_idx on public.documents (user_id);
create index if not exists fetched_content_user_id_idx on public.fetched_content (user_id);
create index if not exists field_values_resolves_flag_id_idx on public.field_values (resolves_flag_id);
create index if not exists field_values_user_id_idx on public.field_values (user_id);
create index if not exists flags_user_id_idx on public.flags (user_id);
create index if not exists messages_user_id_idx on public.messages (user_id);
create index if not exists profile_proposals_message_id_idx on public.profile_proposals (message_id);
create index if not exists profile_proposals_session_id_idx on public.profile_proposals (session_id);
create index if not exists research_results_user_id_idx on public.research_results (user_id);
create index if not exists rule_evaluations_user_id_idx on public.rule_evaluations (user_id);
