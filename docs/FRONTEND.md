# Frontend

## Routes (`web/src/app`)
| Route | Purpose |
|---|---|
| `/` | Public landing page (hero, how it works, features, guardrails) |
| `/login` | Google + email magic link (one flow for sign-up and sign-in). UI is English |
| `/home` | Workspace overview. First visit opens the **profile setup pop-up**: About you → Home & category → Education → General documents → Companion (avatar, name, reply language) |
| `/chat` | Conversation UI: avatar welcome, prompt cards, message list, composer (text + mic), reply-language toggle, context panel. Becomes `/chat/[sessionId]` with M3 |
| `/documents` | General documents vault (10th/12th marksheets, domicile, income, caste, caste validity) → Supabase Storage `documents/<uid>/general/<doc_type>/<ts>.<ext>` |
| `/profile` | View/edit the profile (fields = `profiles` columns) with a source chip per saved value ("Typed by you", "From your document" … from `profile_field_sources`), companion settings, **Delete my data** (type DELETE → `DELETE /api/me` → signed out) |
| `/fill/[sessionId]` | Desktop guided filling (M7): share the portal tab (`getDisplayMedia`, browser surface), frame policy in `lib/screen.ts` (dHash), `GuidePanel` (instruction, field value + Copy + source, Done, Help, mic) in the page or in a Document PiP window (React portal; side-by-side message where unsupported), a big **Private mode** button (no frames at all, speech stopped) in the header and in PiP, "your checked values" list with Copy (identifiers: "type it from your document", no Copy), "Practice on the demo portal" link (`/mock-portal/login.html`). Mobile: "open on a laptop" + the link (no QR) |
| `/sessions` | Past form sessions ("My applications"): scheme, step, date, Open + Audit trail. `/sessions/[id]`: the audit timeline with a "Record intact / changed" badge (`GET …/audit`) |

## Avatar (`components/avatar/`)
- MVP: SVG/CSS "orb with eyes" animated with framer-motion. No external assets. 4 avatars = 4 colour palettes + eye shapes (e.g. Aster-teal, Mitra-saffron, Tara-indigo, Chintu-green).
- States: `idle` (slow breathe + blink every 3–6 s), `listening` (leans in, ring pulses with mic level), `thinking` (eyes look up, dots orbit; show the current tool name, e.g. "Checking MahaDBT rules…"), `speaking` (mouth/ring scales with TTS audio amplitude via WebAudio AnalyserNode), `happy` (on a resolved flag/confirm), `concerned` (on a blocking flag).
- Respects `prefers-reduced-motion`.
- Optional upgrade: Rive character with the same state names.

## Cards (`components/cards/`), driven by the WS `card` event
`confirm_profile`, `scheme_suggestions`, `research_summary`, `eligibility` (+ "Continue to documents"), `document_checklist` (upload per item, blur check, status chips), `field_review` (value + source chip → `DocumentViewer`: the page with the cited lines boxed; no box for vision-read lines), `contradiction` / `missing_item` / `low_confidence` (one `FlagCard`: candidates with source chips, pick or type, reason, "Keep as is"/"Continue anyway"; only the latest card per flag is shown), `readiness` (`ReadinessCard`, + "Start guided filling" when ready), `start_screen_share` (`StartScreenShareCard` → `/fill/[sessionId]`), `session_summary`.
Each card's actions call REST endpoints. The result is posted back into the conversation as a `ui_event` so the agent knows.

## Consent
`ConsentHost` (in the app shell) is the one consent screen: `ensureConsent(scope)` in `lib/api.ts` reads the latest answer (RLS) and opens it if needed, before any document upload (checklist + vault). `putProfile`/`confirmProfile` retry once after a `consent_required:<scope>` 403 (caste/religion). Changing the text = bump `CONSENT_VERSION` in `backend/app/api/me.py`.

## State & data
- zustand stores: `session` (phase, flags, fields), `voice` (vad state, playing, levels), `ws` (connection, queue).
- The WS client auto-reconnects with backoff and resends `hello`. Messages are typed from `src/lib/ws/protocol.ts`.
- Document progress: the checklist chips poll the `documents` row (RLS) every 2 s, and the server pushes the field review + flag cards over the WS when a document is done. Supabase Realtime is not used (M6 trim: no visible gain over these two).
- i18n: `src/lib/i18n/{en,hi,mr}.json` with a tiny `t()` helper. UI strings only; agent text comes from the backend.

## Design direction
Warm, calm, trustworthy — not "AI purple". Follows the `chatgpt/` reference: off-white `#fafbf8`, deep green ink/primary (`#273d33` / `#2c5743`), soft sage / peach / lavender / butter tiles, soft orb avatars, Manrope headings + DM Sans body + Noto Sans Devanagari fallback. Shared utilities in `globals.css`: `btn-primary`, `btn-subtle`, `btn-ghost`, `card`, `field`, `eyebrow`, `chip`. UI copy is English; the assistant replies in en/hi/mr (`assistant_settings.language`). Large tap targets (≥ 48 px), body ≥ 16 px. Mobile-first. Accessible: labels, focus rings, captions for every spoken message.
