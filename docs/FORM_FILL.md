# Guided form filling (screen share)

## UX
- Desktop Chrome only (Android Chrome has no `getDisplayMedia`). On mobile, show "Open Aster on a laptop to fill with Aster" + a QR code to the same session.
- The user opens the portal in a tab and logs in **themselves**.
- In Aster: "Start guided filling" → `getDisplayMedia({video: true})` (the user picks the portal tab) → open a **Document Picture-in-Picture** window (`documentPictureInPicture.requestWindow`) containing the avatar, the current instruction, the field value with a Copy button, and mic/pause controls. Aster floats above the portal while they work.
- If Document PiP is unsupported → instruct the user to place windows side by side.

## Frame policy (client)
- Grab a frame from the video track via `ImageCapture.grabFrame()` (or a video→canvas fallback). Downscale to max 1280 px wide, JPEG q=0.7.
- Send a frame only: (a) with each user utterance/text, (b) when the screen changed (dHash distance > 10 vs the last sent frame), checked every 1.5 s, max 1 frame / 3 s, (c) when the user taps "Help with this page".
- WS: `{"type":"screen_frame","frame_id":"…","reason":"utterance|change|manual"}` + a binary JPEG. Frames are held in backend memory (LRU of 3) and never written to disk, DB or logs.

## Backend analysis (`analyze_screen`)
VLM call with: frame + confirmed fields (identifiers masked) + pack `portal_field_map` (if any) + the last instruction. JSON schema output:
```json
{
  "page_kind": "login|otp|captcha|form|review|submit_confirm|payment|other",
  "sensitive": true,
  "page_title": "string",
  "visible_fields": [
    {"label": "Annual Family Income", "field_key": "annual_family_income|null", "appears_filled": false,
     "suggested_value": "148000|null", "source_field_key": "annual_family_income|null", "note": "string|null"}
  ],
  "next_instruction": "string (user's language, one step)",
  "warnings": ["string"]
}
```
Post-processing (code, not prompt):
- If `page_kind` ∈ {login, otp, captcha, payment, submit_confirm} → force `sensitive=true`, drop every `suggested_value`, and reply with a template ("Please enter your password/OTP yourself; I'll wait." / "Review everything; when ready, you can submit."). Send `pause_guidance` until the page changes.
- `suggested_value` must equal a confirmed field value (or its portal-formatted variant). Otherwise drop it and set the note "check your document".
- Identifier fields (Aadhaar, account number) → never suggested; instruction = "type the number from your <document>".
- Dropdown labels: map the value to the visible option text when the LLM provides it; otherwise say the value.

## Guidance card in PiP
Field label · value · Copy · source ("from Income Certificate") · ✔ "Done" (the user marks it; the next frame verifies `appears_filled`).
