# Document verification

## Pipeline (per uploaded document)
1. **Upload**: web uploads directly to Storage `documents/{user_id}/{session_id}/{document_id}.{ext}` and inserts a `documents` row (`status=uploaded`). PDFs → backend renders pages to PNG (pymupdf, 200 dpi).
2. **Quality**: client-side blur check before upload (Laplacian variance on a canvas; prompt a retake if low). Server stores `quality` JSON.
3. **Classify**: if the user didn't pick a type → VLM picks `doc_type` from the allowed list with confidence. Below 0.7 → ask the user.
4. **OCR** (`ocr.py`): PDF text layer (confidence 1.0, no GPU) → GPU `/ocr` → vision LLM transcribes lines (`bbox: null`, confidence 0.7; **never for `aadhaar`/`bank_passbook`**, whose full numbers must not leave our systems) → `failed: ocr_unavailable`. `lines[{id:"L0", page, text, confidence, bbox}]` stored in `documents.ocr` with `pages[{path,width,height}]`. Every line goes through `redact_ids` first; on Aadhaar/passbook, split 4-digit groups are merged first, the page PNG gets the number drawn over (all but the last 4) and the original upload is deleted.
5. **Extract**: LLM with JSON schema. Input = doc type + the fields expected for that type + numbered OCR lines. Output per field: `{field_key, line_ids[], value_text}`. **The model cites line ids; it does not invent text.**
6. **Validate** (deterministic, `validator.py`):
   - `value_text` normalised must be a substring of the normalised text of the cited lines (normalisation: NFKC, lowercase, collapse spaces, Devanagari digits→ASCII, strip punctuation except `/-.`). For numbers/dates, compare parsed values.
   - Type checks: date parses (day-first; spaced separators OK); amount is numeric (Indian grouping); exam year plausible (2-digit years = 20xx, "FEBRUARY 23"); percentage 0–100; IFSC regex `^[A-Z]{4}0[A-Z0-9]{6}$`; last-4 = 4 digits.
   - Confidence = min(OCR line confidences) × type-check factor (1.0 pass / 0.5 fuzzy).
   - Fail → no candidate. A `low_confidence` flag is raised if the field is required.
7. **Store**: `field_values` row (`source_type=document`, `source_ref={document_id, line_ids, bbox[]}`, `status=candidate`).
8. **Verify across sources**: run contradictions + rules (below) → `flags`.

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
For each field with ≥ 2 candidates from different sources:
- names → name matcher bands
- numbers → exact (amounts: exact after parsing; percentages: ±0.01)
- dates → exact
- enums → exact after normalisation map (e.g. "OBC" == "इतर मागास वर्ग")
A disagreement creates a `contradiction` flag listing all candidates with sources. **Resolution**: the user picks a candidate (or types a new value with a reason) → `field_values` gets a `confirmed` row referencing the chosen candidate + `resolution_reason`. Candidates are never deleted or edited.

## Rules (`rules_engine.py`, files in `app/verify/rules/*.json`)
- A minimal JSON Logic subset, implemented in-house (~120 lines, fully unit-tested): `var, ==, !=, <, <=, >, >=, and, or, !, in, missing, if`.
- Facts available to rules: `fields.<key>` (confirmed or best candidate), `docs.<doc_type>.present`, `computed.name_match_min`, `computed.age`, `pack.*`.
- Rule: `{id, version, severity: block|warn, reason_code, logic, message: {en,hi,mr}, source?}`. `logic` true → the flag is raised.
- Every evaluation is written to `rule_evaluations` (rule id + version, inputs snapshot, result).

## Flags
`flags(type: contradiction|missing_doc|low_confidence|rule, severity: block|warn, status: open|resolved|acknowledged)`. The readiness gate passes when there are no open `block` flags, or the user explicitly acknowledges them (logged).
