# Executable Implementation Plan — Rule-Based Synonyms & Heuristics

Goal: deliver the rule-based preference mapping method outlined in **Rule‑Based Synonyms & Heuristics Implementation Guide** while aligning with existing SRS/SDD flow and CR‑004 preference-mode scope. The method must parse free-text preferences, map them to `filters_options.csv`, and surface telemetry/CSV logging for benchmarking.

## Deliverables
- Rule-based preference mapper module wired into the preference-mode pipeline (`/v1/preferences/parse`) returning structured `filters` output with confidence and status metadata.【F:docs/Implementation Guide Rule Based method.md†L47-L89】【F:docs/CR-004.md†L289-L312】
- Synonym dictionary ingestion (JSON/YAML) plus catalogue loader for `filters_options.csv`, including normalization, inverted index, and cache warmup/validation at startup.【F:docs/Implementation Guide Rule Based method.md†L13-L45】【F:docs/CR-004.md†L315-L342】
- Negation-aware pre-processing, n-gram generation, scoring heuristics, and thresholded selection to produce `selected` flags and confidence values per option.【F:docs/Implementation Guide Rule Based method.md†L91-L155】
- Config switches for synonym path, thresholds, and language selection aligned with `.env` conventions from SRS/SDD; default to English-only in v1.【F:docs/Implementation Guide Rule Based method.md†L57-L89】【F:docs/SDD_v001_041125.md†L9-L26】
- CSV logging and import/summary compatibility for preference-mode runs, including timing and method fields.【F:docs/CR-004.md†L196-L225】【F:docs/SDD_v001_041125.md†L9-L26】

## Work Breakdown
### 1) Catalogue & Synonym Ingestion
- Implement `FiltersCatalogue` service to read `filters_options.csv` on startup, normalizing labels (lowercase, strip punctuation) and grouping options by filterId/filterLabel; fail fast if file missing/invalid and expose cached structure for mappers.【F:docs/Implementation Guide Rule Based method.md†L13-L31】【F:docs/CR-004.md†L315-L342】
- Add `SynonymStore` that loads `synonyms.json|yaml`, builds canonical synonyms per option, applies normalization identical to catalogue, and constructs an inverted index mapping synonym → [(filterId, optionId)].【F:docs/Implementation Guide Rule Based method.md†L33-L45】
- Expose reload hook for synonyms to support future updates without redeploy; guard with schema validation.

### 2) Text Pre-processing & Negation Handling
- Add preprocessing utility to lowercase, strip punctuation/extra whitespace, and optionally lemmatize tokens before matching; generate unigrams/bigrams/trigrams from cleaned text to catch multi-word synonyms.【F:docs/Implementation Guide Rule Based method.md†L91-L114】
- Implement negation detector using regex (`\b(no|not|without|don’t)\s+(...)`) to flag spans; provide mapping table for positive alternatives (e.g., catering → `Room Only`) and ensure negated spans are replaced before matching or scored with penalty.【F:docs/Implementation Guide Rule Based method.md†L101-L113】【F:docs/CR-004.md†L90-L107】

### 3) Matching & Scoring
- For each n-gram, check inverted index; accumulate candidates with weights for phrase length and frequency. Apply negation penalty and map to positive alternatives when defined; otherwise mark as excluded.【F:docs/Implementation Guide Rule Based method.md†L115-L142】
- Compute confidence score (0–1) using weighted sum of features (length bonus, count bonus, negation penalty). Persist per candidate and filter-level best selection list.
- Apply configurable threshold (env) to mark `selected=true`; retain lower-scoring candidates as `selected=false` when returning options for transparency and UI hints.【F:docs/Implementation Guide Rule Based method.md†L125-L144】【F:docs/CR-004.md†L358-L370】

### 4) API & Pipeline Integration
- Register `rules` preference mapper in method catalogue; route `/v1/preferences/parse` to run language detection (English-only), preprocess text, load synonyms/catalogue, perform matching, then shape response per CR‑004 `filters` schema with metadata (`method`, `mode`, `timings.totalMs`, `thresholdBreached`).【F:docs/CR-004.md†L289-L312】【F:docs/SDD_v001_041125.md†L9-L26】
- Ensure mutually exclusive interpretation modes: holiday request flow unchanged; preference mode returns `status` values (`success`, `no-preferences-detected`, `invalid-catalogue`) and empty filters when nothing crosses threshold.【F:docs/CR-004.md†L253-L276】【F:docs/CR-004.md†L365-L370】

### 5) Configuration & Ops
- Add env keys: `PREFERENCES_RULES_SYNONYMS_PATH`, `PREFERENCES_RULES_THRESHOLD`, `PREFERENCES_RULES_NEGATION_PENALTY`, `PREFERENCES_RULES_LANGS` (default `en`), leveraging existing config loader pattern; document defaults in `.env` template and README.【F:docs/Implementation Guide Rule Based method.md†L57-L89】【F:docs/SDD_v001_041125.md†L9-L26】
- Provide seed `synonyms.json` aligned with fixture examples (Wi‑Fi, Room Only, Scuba) to support demos/tests and keep under version control alongside `filters_options.csv`.【F:docs/Implementation Guide Rule Based method.md†L33-L45】【F:docs/CR-004.md†L90-L107】
- Update CSV logger to include filters/options JSON and confidence scores in `Output`, set `Method=rules`, and record timing for latency guardrails; ensure import runner passes method/mode through for summary stats.【F:docs/CR-004.md†L196-L225】【F:docs/SDD_v001_041125.md†L9-L26】

### 6) Frontend Hooks (minimal)
- Ensure preference-mode UI renders returned filters/options grouped by filter label and supports empty-state messaging when no preferences detected; reuse existing mode switch contract from CR‑004 without additional UI changes beyond wiring fields.【F:docs/CR-004.md†L253-L276】【F:docs/CR-004.md†L301-L312】

## Test Plan (Executable Scenarios)
### Backend Unit/Integration
- `test_catalogue_loads_and_normalizes`: start service with valid `filters_options.csv`; assert filters/options normalized and cached; expect startup failure when file missing/corrupt.【F:docs/Implementation Guide Rule Based method.md†L13-L31】【F:docs/CR-004.md†L315-L342】
- `test_synonym_index_build`: load seed `synonyms.json`; verify inverted index maps synonyms to correct optionIds and rejects duplicates/unknown options.【F:docs/Implementation Guide Rule Based method.md†L33-L45】
- `test_preprocess_and_ngrams`: input "Wi-Fi in all rooms" yields normalized tokens and bigram/trigram coverage for "wi fi", "wi fi in" to prove multi-word matching readiness.【F:docs/Implementation Guide Rule Based method.md†L91-L114】
- `test_negation_mapping`: "no catering but scuba required" returns board option `Room Only` plus scuba option with negation penalty applied and `selected=true` when above threshold.【F:docs/Implementation Guide Rule Based method.md†L101-L113】【F:docs/CR-004.md†L90-L107】
- `test_scoring_and_threshold`: configure threshold 0.6; ensure single mention of low-weight synonym is `selected=false` (confidence <0.6) while repeated/bigram synonym crosses threshold.【F:docs/Implementation Guide Rule Based method.md†L115-L142】
- `test_preferences_parse_endpoint`: POST `/v1/preferences/parse` with "need free wifi and scuba" returns filters structure, method=rules, mode=preferences, timing metadata, and CSV log entry capturing output/status.【F:docs/CR-004.md†L289-L312】【F:docs/SDD_v001_041125.md†L9-L26】
- `test_no_preferences_detected`: unknown text returns empty filters/status `no-preferences-detected` without crashing and respects timing/logging.【F:docs/CR-004.md†L365-L370】
- `test_processing_threshold_flag`: simulate slow matcher to assert `thresholdBreached` toggles when duration exceeds `PROCESSING_THRESHOLD_MS`.【F:docs/SDD_v001_041125.md†L9-L26】

### Frontend/Contract
- `test_preferences_mode_payload`: toggling to Preferences sends `mode=preferences` and `method=rules`; UI renders mapped filters list when present and shows empty-state when not.【F:docs/CR-004.md†L253-L276】【F:docs/CR-004.md†L301-L312】
- `test_holiday_mode_unchanged`: switching back to Holiday request keeps original fields and uses holiday parsing pipeline per SRS/SDD baseline, ensuring no regression from rules integration.【F:docs/SRS_v003_011125.md†L157-L184】【F:docs/SDD_v001_041125.md†L9-L26】

### Import/Summary & Telemetry
- `test_import_preferences_rules`: import CSV with preference texts/expected mappings; verify runner routes to rules mapper, records outputs/status in CSV, and summary groups by method with accuracy/P95 stats.【F:docs/CR-004.md†L208-L245】【F:docs/CR-004.md†L381-L399】
- `test_csv_log_schema`: ensure log row includes raw input, method=rules, processing time, filters JSON, and status, matching existing audit schema.【F:docs/CR-004.md†L196-L225】【F:docs/SDD_v001_041125.md†L9-L26】
