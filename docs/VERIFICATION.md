# Document verification

## Pipeline (per uploaded document)
1. **Upload**: web uploads directly to Storage `documents/{user_id}/{session_id}/{document_id}.{ext}` and inserts a `documents` row (`status=uploaded`). PDFs → backend renders pages to PNG (pymupdf, 200 dpi).
2. **Quality**: client-side blur check before upload (`web/src/lib/blur.ts`: Laplacian variance of an 800 px grayscale copy; below `BLUR_MIN = 100` the card asks for a clearer photo or "use anyway"; calibrated on the specimen: sharp ≈ 2250, 2× blur 326, 3× blur 82). Server stores `quality: {blur_var}`. `demo/specimens/income_certificate_blurry.png` scores 21.
3. **Slot + file checks** (code, no model): `verify/doctype.py` matches title phrases (en/mr/hi). A slot is questioned only when its own title is absent and a look-alike's is present (income ↔ EWS / non-creamy layer / caste; caste ↔ validity; 10th ↔ 12th): block flag `doc_type_mismatch` ("might not be your income certificate…"), nothing extracted until the user re-uploads or says why it is right (then it is read again, trusted). An income read next to "below / less than / पेक्षा कमी / से कम" is a limit, not income: block flag `income_is_a_limit`, value not saved. `verify/integrity.py` reads the original file before OCR: AI-generator markers (IPTC `trainedAlgorithmicMedia`, SD/ComfyUI PNG chunks, generator names) → block; saved with an editor (Photoshop, Canva, GIMP, Word…) or a PDF changed > 2 days after it was made → warn (values still read). Flags are `type: rule`, answered with a reason only; a newer upload in the slot closes them. Wording never judges; audit `document.integrity` (signal codes only). Rule `INCOME_CERT_DATE_IN_FUTURE` (block).
4. **OCR** (`ocr.py`): PDF text layer (confidence 1.0, no GPU) → GPU `/ocr` → vision LLM transcribes lines (`bbox: null`, confidence 0.7; **never for `aadhaar`/`bank_passbook`**, whose full numbers must not leave our systems) → `failed: ocr_unavailable`. `lines[{id:"L0", page, text, confidence, bbox}]` stored in `documents.ocr` with `pages[{path,width,height}]`. Every line goes through `redact_ids` first; on Aadhaar/passbook, split 4-digit groups are merged first, the page PNG gets the number drawn over (all but the last 4) and the original upload is deleted.
5. **Extract**: LLM with JSON schema. Input = doc type + the fields expected for that type + numbered OCR lines. Output per field: `{field_key, line_ids[], value_text}`. **The model cites line ids; it does not invent text.**
6. **Validate** (deterministic, `validator.py`):
   - `value_text` normalised must be a substring of the normalised text of the cited lines (normalisation: NFKC, lowercase, collapse spaces, Devanagari digits→ASCII, strip punctuation except `/-.`). For numbers/dates, compare parsed values.
   - Type checks: date parses (day-first; spaced separators OK); amount is numeric (Indian grouping); exam year plausible (2-digit years = 20xx, "FEBRUARY 23"); percentage 0–100; IFSC regex `^[A-Z]{4}0[A-Z0-9]{6}$`; last-4 = 4 digits.
   - Confidence = min(OCR line confidences) × type-check factor (1.0 pass / 0.5 fuzzy).
   - Name fields: no digits, not an issuer header ("भारत सरकार", "Government of India" …, names.py score ≥ 75). Enum fields (gender): must map to a known value.
   - Fail → no candidate; the field review card lists it under "not found on this document".
7. **Store**: `field_values` row (`source_type=document`, `source_ref={document_id, line_ids, bbox[]}`, `status=candidate`).
8. **Verify across sources** (`checks.run_checks`, after every document and on `run_verification`): contradictions + rules + missing documents (the latter only on `run_verification`) → `flags`. When it ends (read or failed) the pipeline tells the open conversation in-process (`pipeline.subscribe`), which shows the field review card, any new flag cards and a short spoken summary. ponytail: one backend instance.

Income certificates do not extract `full_name`: they are often issued in a parent's name.

Voice/text answers create candidates with `source_type=voice|text`, `source_ref={message_id}`. Confirmed profile values are candidates with `source_type=profile`.

## Canonical field keys
`full_name, father_name, mother_name, dob, gender, mobile, aadhaar_last4, category, caste, religion, annual_family_income, income_cert_number, income_cert_issue_date, income_cert_fy, domicile_state, district, taluka, ssc_board, ssc_year, ssc_percentage, hsc_board, hsc_year, hsc_percentage, current_course, current_year, institute_name, bank_name, bank_ifsc, bank_account_last4, account_holder_name`

## Document types → expected fields
| doc_type | fields |
|---|---|
| `aadhaar` | full_name, dob, gender, aadhaar_last4 (mask the rest immediately; never store the full number) |
| `ssc_marksheet` / `hsc_marksheet` | full_name, mother_name, ssc/hsc_year, *_percentage, *_board |
| `income_certificate` | full_name, annual_family_income, income_cert_number, income_cert_issue_date, income_cert_fy |
| `caste_certificate` / `caste_validity` | full_name, caste, category |
| `domicile_certificate` | full_name, domicile_state, district |
| `bank_passbook` | account_holder_name, bank_name, bank_ifsc, bank_account_last4 |
| `fee_receipt` / `admission_letter` | full_name, institute_name, current_course, current_year |

## Name matching (`names.py`)
1. Transliterate Devanagari → Latin (indic-transliteration, ITRANS → simplified).
2. Normalise: lowercase; drop honorifics (shri, smt, kumari, ku, mr, ms); phonetic folds (`aa→a, ee→i, oo→u, w→v, ph→f, z→j, sh→s, th→t, dh→d, kh→k, gh→g, bh→b, chh→ch`); remove double letters.
3. Tokenise; handle initials ("R." matches any token starting with r).
4. Score = rapidfuzz `token_set_ratio` on normalised names, capped by the weakest token of the shorter name (best `ratio` against the other name's tokens): `token_set_ratio` alone scored Patil/Patel 94 and Sharma/Verma 82. No Jaro-Winkler tie-break yet.
5. Bands: ≥ 92 `match`, 80–92 `minor_variation` (warning: portals may reject spelling differences), < 80 `mismatch` (blocking).
Unit tests must include: Marathi vs English, surname-first order, middle name/father's name present vs absent, initials, common spelling variants (Shinde/Shindhe, Kasliwal/Kaslival).

## Contradictions (`contradictions.py`)
Candidates that count (`effective`): a replaced document's candidates drop out; after a confirmation only the confirmed value and later candidates count; only the latest profile value counts; a document value with confidence < 0.6 gets its own `low_confidence` flag (for the fields in `checks.CHECKED_FIELDS`) and stays out of comparisons until confirmed.
For each field with ≥ 2 candidates from different sources:
- names → **not here**: the name rules compare them (so one spelling problem is flagged once)
- numbers → exact after parsing (percentages: ±0.05, people round 69.83 to 69.8)
- dates → exact
- enums → exact after normalisation map (e.g. "OBC" == "इतर मागास वर्ग", "पुरुष" == "Male")
- free text → token_set_ratio ≥ 90; text in different scripts is not compared (a Marathi board name vs an English one)
A disagreement on a number/date/enum/id is `block`, on free text `warn`. Flags are deduped by (type, reason, field) and by the **values** involved: an answered flag is not raised again for the same values.

## Resolution (guardrail 3)
The user picks a candidate or types a value, with a reason, or keeps it as is (acknowledge). `checks.resolve` → a `confirmed` `field_values` row (`source_type=resolution`, `source_ref {flag_id, candidate_id, via, message_id}`, `resolution_reason`) + flag `resolved`/`acknowledged` + audit. Candidates are never deleted or edited.
- **Tap**: `POST …/flags/{id}/resolve|acknowledge` (`via=tap`).
- **Voice / text**: on a user turn with open flags, `agent/answers.py` maps the user's words to `{flag, value from the card, reason}` (JSON mode); `resolve_flag` validates: the choice must match a candidate, the reason must be found in the user's own message (partial_ratio ≥ 70), only a voice/text turn can answer (never a card-tap turn). `via` and `message_id` come from the orchestrator. Seen live: the 8B model said "we'll use 148000" without calling a tool, hence the code path.

## Readiness
`checks.readiness`: every value the form will use (confirmed, else the best candidate) with its source, open blocking flags, warnings, and acknowledged flags with the user's reason. `verification ↔ ready` follows the open blocking flags in code; the readiness card is shown by code when the phase becomes `ready`, and the model's state says "Form ready: NO" while anything blocks.

## Rules (`rules_engine.py`, files in `app/verify/rules/*.json`)
- A minimal JSON Logic subset, implemented in-house (~120 lines, fully unit-tested): `var, ==, !=, <, <=, >, >=, and, or, !, !!, in, if`; a missing var makes the result unknown (no flag), so no `missing` operator is needed.
- `rules/core.json` (6): `NAME_MISMATCH_ACROSS_DOCS` (block, < 80), `NAME_MINOR_VARIATION` (warn, 80–92), `BANK_HOLDER_NAME_MISMATCH` (block), `BANK_HOLDER_NAME_VARIATION` (warn), `INCOME_CERT_OLDER_THAN_1Y` (warn), `HSC_NOT_AFTER_SSC` (block). Each rule names its `field_key`; name rules carry the name candidates (pick a spelling), single-value rules can be answered with a typed value.
- Facts available to rules: `fields.<key>` (confirmed or best candidate), `docs.<doc_type>.present`, `computed.name_match_min` (lowest pairwise score between the spellings of the student's name), `computed.bank_holder_match`, `computed.income_cert_age_days`, `pack.*` (`computed_facts`).
- Rule: `{id, version, severity: block|warn, reason_code, logic, message: {en,hi,mr}, source?}`. `logic` true → the flag is raised.
- Every evaluation is written to `rule_evaluations` (rule id + version, inputs snapshot + missing vars, result = raised).

## Flags
`flags(type: contradiction|missing_doc|low_confidence|rule, severity: block|warn, status: open|resolved|acknowledged)`. The readiness gate passes when there are no open `block` flags, or the user explicitly acknowledges them (logged).
