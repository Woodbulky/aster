# Backend API

Auth: `Authorization: Bearer <supabase access token>` on REST. WS: first message `hello` with the token.

## REST (`/api`)
| Method | Path | Body → Result |
|---|---|---|
| GET | `/health` | provider states (gpu, llm_fallback, sarvam, bhashini, tavily), version, `llm: {primary: gpu|fallback, active: gpu|fallback|none}` |
| GET | `/api/me` | profile (masked) + assistant settings |
| POST | `/api/profile/confirm` | `{proposal_id, accept: bool, edits?}` → saves confirmed values (+ audit) |
| PUT | `/api/assistant` | `{avatar_id, assistant_name, language, voice?}` |
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
| `ui_event` | `name` (e.g. `profile_confirmed`, `flag_resolved`, `document_uploaded`, `screen_share_started/stopped`), `payload` |
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
