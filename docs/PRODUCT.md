# Product — what Aster does

## One line
A student talks to Aster in Marathi, Hindi or English. Aster learns their profile, finds out what a scheme needs, checks their documents for problems, and then guides them live while they fill the official portal.

## Users
- **Student/applicant** (primary). Mobile-first for steps 1–5. Desktop Chrome for screen-share form filling.
- **Helper** (parent, cyber-café operator, college clerk) sitting next to the student. Same UI; no separate dashboard in the MVP.

## End-to-end flow (phases)
| # | Phase | What the user experiences | What the system does |
|---|---|---|---|
| 1 | Sign in | Google or email login | Supabase Auth; a profile row is created by trigger |
| 2 | Meet Aster | Pick avatar + name + language | Saves `assistant_settings` |
| 3 | Onboarding | Aster asks ~10 core details by voice/chat (name, DOB, gender, district, category, 10th/12th year + %, course + year, family income) | Agent proposes values → confirm card → saved to `profiles`. Sensitive fields (caste, religion) asked only with a short "why" + consent |
| 4 | Choose form | "Which form?" → "MahaDBT" (+ optional portal URL) | Creates `form_sessions`. If several schemes fit, Aster suggests them from the profile |
| 5 | Research | Aster says "Let me check the official rules…" (tool activity visible) | Loads the verified knowledge pack, else does live research (search → fetch → PDF). Every criterion/document has `source_url` + quote |
| 6 | Eligibility | Card: each criterion ✅ / ❌ / ❔ with reason + source link. Spoken summary | Deterministic rules on profile vs criteria; LLM only explains |
| 7 | Documents | Checklist card; upload or photo per item | Storage upload → GPU OCR → field extraction with line ids |
| 8 | Verification | Fields with source highlights; contradiction cards ("certificate says ₹1,48,000, you said 1.2 lakh — which is final?") | Validator, name matcher, rules → flags; user resolves with a reason |
| 9 | Ready check | "Shall we fill the form now?" Readiness summary | Blocks only on unresolved blocking flags (user may override with an acknowledged warning) |
| 10 | Guided filling | Desktop: share the portal screen; Aster floats in a picture-in-picture window and says "This box is Annual Income — type 148000". Copy buttons | Frames → VLM → guidance JSON; pauses on login/OTP/submit screens |
| 11 | Wrap-up | Summary + what to keep ready + reminders | Audit trail, session marked done |

Voice and chat both work in every phase, and the user can switch at any time.

## Demo script (8–10 min)
1. Login → pick avatar "Aster" → Marathi.
2. Voice onboarding (5 answers) → confirm card.
3. "मला MahaDBT भरायचा आहे" → research tool trace → eligibility card with sources.
4. Upload Aadhaar, marksheet, income certificate, passbook → fields fill with highlighted sources.
5. Seeded problems: name spelling mismatch on passbook + income contradiction → resolve by voice.
6. "Let's fill" → share the portal tab → Aster in PiP guides 4–5 fields by voice, refuses to read the OTP, pauses at Submit.
7. Kill the Kaggle notebook live → Aster keeps working on the fallback providers. Show the audit trail.

## Out of scope (MVP)
Auto-submission, auto-typing into the portal, storing portal credentials, caseworker dashboard, offline mode, more than one portal deeply supported.
