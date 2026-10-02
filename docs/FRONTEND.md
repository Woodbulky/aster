# Frontend

## Routes (`web/src/app`)
| Route | Purpose |
|---|---|
| `/login` | Google + email sign-in (Supabase). Language toggle mr/hi/en |
| `/onboarding` | Avatar picker (4 avatars), assistant name (default "Aster"), language → then opens a chat session in the `onboarding` phase |
| `/chat/[sessionId]` | Main conversation: avatar stage (top, ~40% height on mobile), message list with cards, composer (text + mic + push-to-talk) |
| `/fill/[sessionId]` | Desktop guided filling: share-screen button, PiP launcher, field list with copy buttons |
| `/profile` | View/edit the confirmed profile, the source of each value, consent toggles, delete my data |
| `/sessions` | Past form sessions |

## Avatar (`components/avatar/`)
- MVP: SVG/CSS "orb with eyes" animated with framer-motion. No external assets. 4 avatars = 4 colour palettes + eye shapes (e.g. Aster-teal, Mitra-saffron, Tara-indigo, Chintu-green).
- States: `idle` (slow breathe + blink every 3–6 s), `listening` (leans in, ring pulses with mic level), `thinking` (eyes look up, dots orbit; show the current tool name, e.g. "Checking MahaDBT rules…"), `speaking` (mouth/ring scales with TTS audio amplitude via WebAudio AnalyserNode), `happy` (on a resolved flag/confirm), `concerned` (on a blocking flag).
- Respects `prefers-reduced-motion`.
- Optional upgrade: Rive character with the same state names.

## Cards (`components/cards/`), driven by the WS `card` event
`confirm_profile`, `scheme_suggestions`, `research_summary`, `eligibility`, `document_checklist` (upload/capture per item, status chips), `field_review` (value + source chip → opens the document with the bbox highlight or plays the audio), `contradiction` (candidate options with sources + a reason input/voice), `missing_item`, `low_confidence`, `readiness`, `start_screen_share`, `session_summary`.
Each card's actions call REST endpoints. The result is posted back into the conversation as a `ui_event` so the agent knows.

## State & data
- zustand stores: `session` (phase, flags, fields), `voice` (vad state, playing, levels), `ws` (connection, queue).
- The WS client auto-reconnects with backoff and resends `hello`. Messages are typed from `src/lib/ws/protocol.ts`.
- Supabase Realtime subscribes to `documents` and `flags` for the session, so OCR progress shows live.
- i18n: `src/lib/i18n/{en,hi,mr}.json` with a tiny `t()` helper. UI strings only; agent text comes from the backend.

## Design direction
Warm, trustworthy, Indian-public-service friendly — not "AI purple". Off-white background, deep navy text, teal + saffron accents (match the Aster brand), large tap targets (≥ 48 px), body ≥ 16 px, a Devanagari-capable font (Noto Sans + Noto Sans Devanagari, or Mukta). Mobile-first. Accessible: labels, focus rings, captions for every spoken message.
