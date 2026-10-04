# Backend API

Auth: `Authorization: Bearer <supabase access token>` on REST. WS: first message `hello` with the token.

## REST (`/api`)
| Method | Path | Body → Result |
|---|---|---|
| GET | `/health` | `providers: {gpu: up\|down\|open\|off, llm_fallback: up\|open\|missing, sarvam: configured\|missing, tavily/sarvam_stt/sarvam_tts: up\|open\|missing}`, `packs: {usable, total}` (0 total on a deploy = `knowledge/` didn't ship), version, `llm: {primary: gpu\|fallback, active: gpu\|fallback\|none}`. No vendor calls (safe for a keep-warm pinger). |
| GET | `/api/me` | profile (masked) + assistant settings |
| POST | `/api/profile/confirm` | `{proposal_id, accept: bool, edits?}` → `{status: accepted\|rejected, saved}`. Own pending proposals only (else 404). `edits` may only touch proposed keys; `""` = don't save that field. Kept values get `source_type` = the proposal's evidence + `source_ref {proposal_id, message_id}`; corrected values get `manual`. Audit `profile.confirmed`/`profile.rejected` with field names only |
| PUT | `/api/assistant` | `{avatar_id, assistant_name, language, voice?}` |
| PUT | `/api/profile` | profile form values typed by the user (`profiles` columns, `""` = not provided; unknown keys → 422; `aadhaar_last4` only) → saved with `profile_field_sources.source_type='manual'` + audit `profile.edited {fields}` (names only). Conversation-derived values still go through proposals (`/api/profile/confirm`). |
| POST | `/api/sessions` | `{portal?, scheme_key?, portal_url?}` → session |
| GET | `/api/sessions/{id}` | phase, fields, flags, docs, research |
| POST | `/api/sessions/{id}/documents` | `{document_id, doc_type, mime, quality?}` after the client uploads to Storage `<uid>/<sid>/<document_id>.<ext>` → 202, pipeline runs in the background (`documents.status`: uploaded → processing → extracted\|failed, `error`: ocr_unavailable\|llm_unavailable\|internal). 400 if the object is missing; posting a `failed` document again retries it, otherwise 409. Each upload is checked against its slot (`verify/doctype.py`) and for file signals (`verify/integrity.py`): a possibly wrong document is not extracted and raises a blocking flag (see VERIFICATION.md step 3). There is no `/view` endpoint: the client reads `documents.ocr` (pages + lines with bbox) through RLS and signs `ocr.pages[].path` itself |
| POST | `/api/sessions/{id}/flags/{flag_id}/resolve` | `{candidate_id?, value?, reason (3–300)}` → `{flag_id, status}`. A candidate of this flag or a typed value (not both) → `resolved` + a confirmed `field_values` row; neither → `acknowledged`. Always `via=tap` (voice answers go through `resolve_flag` with their message id). 400 bad answer, 409 already answered |
| POST | `/api/sessions/{id}/flags/{flag_id}/acknowledge` | `{reason}` → keep as is (also for blocking flags: the reason is logged). Document checks (`doc_type_mismatch`, `income_is_a_limit`, `integrity_signal`) are answered this way only (`resolve` with a value → 400); acknowledging the first two reads the document again in the background, trusting its slot (the voice path does the same) |
| GET | `/api/sessions/{id}/readiness` | The `readiness` card payload (values the form will use + sources). The `/fill` page's field list |
| POST | `/api/consents` | `{scope: documents\|sensitive_profile, granted}` → the row (append-only; latest per scope wins; `explanation_version` set by the backend; audit `consent.recorded`). Gates in code: `POST …/documents` needs `documents`; saving `caste`/`religion` (`PUT /api/profile`, `/profile/confirm`) needs `sensitive_profile` → else **403 `consent_required:<scope>`** (the web opens the consent screen and retries once). The web reads consents via RLS |
| GET | `/api/sessions/{id}/audit` | `{events: [{id, actor, action, hash, payload, created_at}], verified, broken: [id]}` (own session only). The chain is recomputed on every call (`app/audit.py`; CLI: `uv run python -m app.audit [--user <id>]`, exit 1 if broken) |
| DELETE | `/api/me` | `{deleted, files}`: removes every Storage object under `<uid>/`, then the auth user (every table cascades, the audit trail included). Files left over → 500 and the account is kept |

## WebSocket `/ws/session/{session_id}`
Client → server (JSON unless noted):
| type | fields |
|---|---|
| `hello` | `token, lang` |
| `user_text` | `text` |
| `audio_start` | `mime, lang_hint?` → then ONE binary frame (audio, ≤ 2 MB) → `audio_end`. Errors: `bad_audio`, `no_speech`, `stt_unavailable` |
| `interrupt` | — cancels the running turn (LLM + TTS); server answers `agent_state idle` |
| `ui_event` | `name` (M3: `profile_confirmed {proposal_id}`, `profile_rejected {proposal_id}`, `form_selected {scheme_key, portal?}`; M6: `documents_requested` (eligibility card button → checklist card in code), `flag_resolved {flag_id}` (after a tap answer → thanks + next flag), `document_processed {document_id}` (still accepted, but the server now pushes it itself when the pipeline ends, so the client does not send it); M7: `screen_share_started` (`ready` → `form_fill` in code, audited; from any other phase → error `not_ready`)), `payload`. `form_selected` runs `set_form` → `get_knowledge_pack` → `check_eligibility` in code, not via the LLM; the LLM then only speaks the summary |
| `screen_frame` | `frame_id` (≤ 64), `reason: utterance\|change\|manual` → then ONE binary frame (JPEG ≤ 1.5 MB, else error `bad_frame`). Held in memory only (last 3 per connection), never written. Own limit: 30 frames/min, not counted in the 30 messages/min. Analysed only in `form_fill`, one at a time: `change` frames during an analysis or < 2 s apart are kept, not analysed; `manual` = Help/Done (spoken "Let me look…" first); `utterance` = sent with speech, used by that voice turn if ≤ 10 s old (the turn becomes a screen turn: the user's words go to the vision model as their question) |
| `ping` | — |

Server → client:
| type | fields |
|---|---|
| `ready` | `phase, assistant` |
| `agent_state` | `state: idle\|listening\|thinking\|speaking\|happy\|concerned`, `detail?` (tool label) |
| `transcript` | `text, lang, provider` (the user's words) |
| `assistant_delta` | `message_id, text` (streaming) |
| `assistant_message` | `message_id, text, lang` (final) |
| `tts_audio` | `message_id, seq, mime` + the next binary frame = audio |
| `tts_unavailable` | `message_id, seq, text, lang` (client uses speechSynthesis) |
| `turn_metrics` | `stt_ms, llm_first_token_ms, first_audio_ms, stt_provider` — voice turns, ms from the end of the utterance (dev overlay) |
| `tool_event` | `name, status: started\|done\|failed, label` |
| `card` | `card_id, kind, payload` |
| `phase` | `phase` |
| `guidance` | `{frame_id, page_kind, sensitive, page_title, instruction, lang, target: GuideField?, fields: [GuideField]}`; `GuideField = {label, field_key, filled, value, option_text, source, identifier, note}`. Post-processed in code (FORM_FILL.md): `value` is only ever a checked value of the user's; identifiers have `identifier: true` and no value; sensitive pages carry no values. A new `instruction` is also sent as `assistant_message` (+ TTS) and stored |
| `pause_guidance` | `reason` = the page kind (login, otp, captcha, payment, submit_confirm, review). The client sends no frames until the page clearly changes or the user taps Resume |
| `error` | `code, message` |
| `pong` | — |

Close codes (client must not retry): `4400` first message was not `hello`, `4401` bad token, `4404` session missing or not yours. Rate limit: 30 messages/min per connection (`error rate_limited`). A new session (no messages yet) gets a greeting turn right after `ready`.

Cards (`card.kind` → `payload`):
| kind | payload |
|---|---|
| `confirm_profile` | `{proposal_id, updates: {field_key: value}}` → answer via `POST /api/profile/confirm`, then `ui_event profile_confirmed/rejected`. Also sent in code after a flag on a profile field is resolved with a value that differs from the profile (one proposal per flag; `source_ref {flag_id, field_value_id}`) |
| `scheme_suggestions` | `{options: [{portal, scheme_key, name, draft, met, not_met, unknown}], note}` → tap sends `ui_event form_selected` |
| `eligibility` | `{scheme_key\|null, name, origin: pack\|live, draft, results: [{id, text, status: met\|not_met\|unknown, reason, source: {url, quote}, ask_field}], counts, deadlines: [{label, date, passed, source}], note}`. Shown again after a reload (from its tool row) |
| `document_checklist` | `{session_id, scheme, items: [{doc_type, label, required, source\|null, note, status: missing\|uploaded\|processing\|extracted\|failed, document_id}], others: [text], note}`. `source: null` = recommended by Aster (Aadhaar, 10th marksheet, passbook), not in the official list |
| `field_review` | `{document_id, doc_type, label, status, error, engine: pdf_text\|gpu_ocr\|vision_llm, pages: [{path, width, height}], fields: [{id, field_key, label, value, confidence, low_confidence, source: {document_id, doc_type, line_ids, page, bbox: [[x0,y0,x1,y1]\|null]}}], unreadable: [label]}`. bbox null = read by the vision fallback (no highlight) |
| `contradiction` / `missing_item` / `low_confidence` | one `FlagPayload`: `{flag_id, session_id, type: contradiction\|rule\|missing_doc\|low_confidence, severity, field_key, field_label, message (user's language), candidates: [{id, field_key, value, source_type, label, document_id, page, bbox, confidence}], can_pick, can_type, doc: {doc_type, label, source}\|null, status}`. The client re-reads the flag's status (RLS) and shows only the latest card per flag (a voice answer sends an updated card) |
| `readiness` | `{session_id, ready, open_block: [summary], open_warn: [summary], acknowledged: [summary + reason], documents: [label], fields: [{field_key, label, value, source, confirmed}], note}`. Shown by code when the phase becomes `ready` |
| `research_summary` | `{scheme, eligibility: [item], documents: [item], rejected, note}`, item = `{text, source_url, quote, content_id, site, fetched_on}` (all unverified) |
