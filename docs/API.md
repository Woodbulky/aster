# Backend API

Auth: `Authorization: Bearer <supabase access token>` on REST. WS: first message `hello` with the token.

## REST (`/api`)
| Method | Path | Body → Result |
|---|---|---|
| GET | `/health` | `providers: {gpu: up\|down\|open\|off, llm_fallback: up\|open\|missing, sarvam/bhashini/tavily: configured\|missing}`, version, `llm: {primary: gpu\|fallback, active: gpu\|fallback\|none}`. No vendor calls (safe for a keep-warm pinger). |
| GET | `/api/me` | profile (masked) + assistant settings |
| POST | `/api/profile/confirm` | `{proposal_id, accept: bool, edits?}` → `{status: accepted\|rejected, saved}`. Own pending proposals only (else 404). `edits` may only touch proposed keys; `""` = don't save that field. Kept values get `source_type` = the proposal's evidence + `source_ref {proposal_id, message_id}`; corrected values get `manual`. Audit `profile.confirmed`/`profile.rejected` with field names only |
| PUT | `/api/assistant` | `{avatar_id, assistant_name, language, voice?}` |
| PUT | `/api/profile` | profile form values typed by the user (`profiles` columns, `""` = not provided; unknown keys → 422; `aadhaar_last4` only) → saved with `profile_field_sources.source_type='manual'`. Conversation-derived values still go through proposals (`/api/profile/confirm`). |
| POST | `/api/sessions` | `{portal?, scheme_key?, portal_url?}` → session |
| GET | `/api/sessions/{id}` | phase, fields, flags, docs, research |
| POST | `/api/sessions/{id}/documents` | `{document_id, doc_type?}` after a client Storage upload → starts the pipeline |
| GET | `/api/sessions/{id}/documents/{doc_id}/view` | signed URL + OCR lines (for highlighting) |
| POST | `/api/sessions/{id}/flags/{flag_id}/resolve` | `{candidate_id? , value?, reason, via: tap\|voice}` |
| POST | `/api/sessions/{id}/flags/{flag_id}/acknowledge` | `{reason}` |
| POST | `/api/consents` | `{scope, granted}` |
| GET | `/api/sessions/{id}/audit` | audit events (own session only) |
| DELETE | `/api/me` | delete the user's data (documents, sessions, profile) |

## WebSocket `/ws/session/{session_id}`
Client → server (JSON unless noted):
| type | fields |
|---|---|
| `hello` | `token, lang` |
| `user_text` | `text` |
| `audio_start` | `mime, lang_hint` → then ONE binary frame (audio) → `audio_end` |
| `interrupt` | — |
| `ui_event` | `name` (M3: `profile_confirmed {proposal_id}`, `profile_rejected {proposal_id}`, `form_selected {portal, scheme_key?}`; later: `flag_resolved`, `document_uploaded`, `screen_share_started/stopped`), `payload`. `form_selected` calls `set_form` in code, not via the LLM |
| `screen_frame` | `frame_id, reason` → then ONE binary frame (JPEG) |
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
| `tool_event` | `name, status: started\|done\|failed, label` |
| `card` | `card_id, kind, payload` |
| `phase` | `phase` |
| `guidance` | analyze_screen result after post-processing |
| `pause_guidance` | `reason` |
| `error` | `code, message` |
| `pong` | — |

Close codes (client must not retry): `4400` first message was not `hello`, `4401` bad token, `4404` session missing or not yours. Rate limit: 30 messages/min per connection (`error rate_limited`). A new session (no messages yet) gets a greeting turn right after `ready`.

Cards (`card.kind` → `payload`):
| kind | payload |
|---|---|
| `confirm_profile` | `{proposal_id, updates: {field_key: value}}` → answer via `POST /api/profile/confirm`, then `ui_event profile_confirmed/rejected` |
| `scheme_suggestions` | `{options: [{portal, scheme_key\|null, name}], note}` → tap sends `ui_event form_selected` |
