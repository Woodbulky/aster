# Guided form filling (screen share)

## UX
- Desktop Chrome only (Android Chrome has no `getDisplayMedia`). On mobile, `/fill` shows "Open Aster on a laptop" + the page link with Copy (no QR code: it would need a dependency).
- The user opens the portal in a tab and logs in **themselves**. For practice and the demo: `web/public/mock-portal/` (login → OTP → form → review & Final Submit; plain HTML, labelled MOCK, nothing typed leaves the browser; its options include the demo account's values).
- Entry points: the readiness card ("Start guided filling" when ready), or the `start_form_fill` tool's `start_screen_share` card.
- In `/fill/[sessionId]`: "Share the portal tab" → `getDisplayMedia({video: {displaySurface: "browser"}, selfBrowserSurface: "exclude", surfaceSwitching: "include"})` → `screen_share_started` (`ready` → `form_fill`, in code) → "Float Aster above the portal" opens a **Document Picture-in-Picture** window (`documentPictureInPicture.requestWindow`, stylesheets copied once, the same React panel through a portal): avatar, instruction, the field value with Copy (the PiP window's own clipboard) and its source, Done, Help, mic, Private mode.
- If Document PiP is unsupported → "put this window and the portal side by side"; the page shows the same panel.
- **Private mode** (big button, page header and PiP): nothing is sent from that moment (a frame in flight is dropped), Aster stops talking. Tap again to resume.

## Frame policy (client, `web/src/lib/screen.ts`)
- Video → canvas, max 1280 px wide, JPEG q=0.7, in memory. (960 px / q0.6 was tried: no faster on the fallback, which is rate-limited not size-limited, and the model missed 2 of 12 fields.)
- Send a frame only: (a) with each user utterance, (b) when the screen changed (dHash distance > 10 vs the last sent frame), checked every 1.5 s, max 1 frame / 3 s, (c) on "Help with this page" or "Done".
- Paused (`pause_guidance`): no frames at all — not even with speech — until a clearly different page (dHash > 24 vs the paused page) or "I'm past this page".
- WS: `{"type":"screen_frame","frame_id":"…","reason":"utterance|change|manual"}` + a binary JPEG (≤ 1.5 MB).

## Backend (`app/agent/screen.py`, in code — no LLM tool loop)
Two steps (seen live: one 8B vision call that both read the page and wrote the guidance took ~28 s a turn and answered Marathi in English):
- **Reader** (vision; GPU first, fallback second; `prompts/screen_reader.md`, `sensitive_kind="screen_frame"`): the page only. A JSON schema keeps it on one line and caps it; fields are compact strings (`"Gender|radio|0|Male/Female"` = label|type|filled|choices; JSON keys on every field doubled the output, 247 vs 140 tokens, ~5 s on the T4). Max 8 fields from the first empty one. Never what a box contains.
```json
{"page_kind": "login|otp|captcha|form|review|submit_confirm|payment|other", "page_title": "≤ 5 words",
 "fields": ["Is this a Renewal Application?|radio|0", "Annual Family Income|text|0"], "buttons": ["Save", "Cancel"]}
```
- **Reading cache** (`Reader`, per connection, in memory): a `change` (dHash) or `manual` frame starts a read in the background at once; a newer page while one is read is read next (only the newest). A question about an unchanged page uses the cached reading: no vision call, no "Let me look…". The client sends its utterance frame as `change` when the page changed since the last frame, so the read overlaps speech-to-text. The checked values are reloaded with each read.
- **Writer** (text; Groq first, GPU second via `chat_stream(prefer="fallback")`; `prompts/screen_writer.md`, `sensitive_kind="screen_text"`, so each Groq call writes `llm.sensitive_fallback` `{"provider": "groq", "kind": "screen_text"}`): the reading (labels, types, options, filled), the checked values (identifiers left out), the last 10 messages, the user's words. No image, no box contents. `reasoning_effort: "none"` (Groq Qwen). JSON `{field_label, field_key, answer_source, value, instruction}`; `answer_source` (`checked_value` / `student_said` / `not_known`) is decided before the instruction: without it the model told every student "this is a new application, choose No". For a field with no value it explains the question and asks. mr/hi replies must be Devanagari, else one retry, else nothing.
- Frames: last 3 per connection, in memory (`Frames`), never written to disk, DB or logs. Own rate limit (30/min). Read only in `form_fill`; `change` frames < 2 s apart are kept, not read.

Post-processing on the writer's output (code, tested in `tests/test_screen.py`):
- **Sensitive pages** — `page_kind` in {login, otp, captcha, payment, submit_confirm, review}, or a field labelled password/OTP/captcha/CVV/PIN/card number whatever the kind, or a "Final Submit"/"Submit application"/"अंतिम" button → `sensitive=true`, the writer is not called, a template ("Please type the OTP yourself. I won't read it. I'll wait." / "Review everything carefully. When you're ready, you can submit."), `pause_guidance`. A "review" page with empty boxes and no submit button is a misread form.
- **Value whitelist** — the target's value is the user's checked value for the writer's `field_key` (DD/MM/YYYY for dates); if the writer named a different value (`contradictions.same`), or claimed a checked value for a key it was not given, its words are dropped. A checked value is said from the template (`fill.type` / `fill.choose`, in the user's language; a radio/dropdown picks the visible option that means the value), unless the user asked a question.
- **Identifiers** (Aadhaar, bank account number; by field key or label: "Aadhaar No.", "आधार क्रमांक", "A/c No." — not "Full Name (as per Aadhaar)") → never a value; the template "type the number yourself from your Aadhaar card", never the writer's words.
- **Free text** is dropped if it holds a number (3+ digits) that is none of the user's checked values (seen live: "use 123456" on the OTP page), or tells them to press a quoted thing that is not on the reading (seen live: "Click the 'Next' button" with no Next; "Click 'Yes' for EWS" with no value). Then: the template for a target with a value, else "I can see your page, but I can't work out the next step right now" (also when no writer answers), or "Everything on this page looks filled" when nothing is empty.
- A new instruction is sent as `guidance` + `assistant_message`, spoken (TTS), and stored as Aster's message (text only, `provider=screen`). A repeat is skipped for automatic frames only: when the user asked, it is said again.
- `portal_field_map` is not sent (every pack has it empty); add it to the prompt when a pack fills it.

## Latency (measured 2026-10-04, laptop → Kaggle T4 / Groq; synthetic MahaDBT-style page, 7 fields)
| | Reader (new page) | Writer | History query | First TTS chunk | Cached question → first audio* | New page → first audio* |
|---|---|---|---|---|---|---|
| GPU reader + Groq writer, en | 8.6 s | 0.4–0.7 s | 0.8 s | 1.0 s | ~2.2 s | ~11 s |
| GPU reader + Groq writer, mr | 8.5 s | 0.5–0.6 s | 0.3 s | 1.5 s | ~2.4 s | ~11 s |
| Groq reader + Groq writer, en | 2.0 s | 0.8 s | 0.8 s | 0.9 s | ~2.4 s | ~4.5 s |
| Groq writer down → GPU writer, en / mr | 9.2 / 8.6 s | 3.5–5.9 s | | | ~6.5–7 s | ~15 s |

\* plus speech-to-text, which the history query now overlaps. GPU reader: ~21 tok/s decode, ~140 tokens, ~4 s to take in a new image (Ollama resizes every frame to the same size: 768/1024/1280 px cost the same). Groq's free tier allows 8,000 tokens/min per organisation and a writer call is ~1.5k tokens: past ~5 questions/min calls wait (seen in the benchmark: 8 s writer calls).
