# Implementation Plan: CR-004 Free-Text Preference → Filter Mapping

## Objectives
Deliver the preference-mapping capability that lets users enter free-text preferences, maps them to filters/options defined in `filters_options.csv`, and evaluates multiple methods while keeping search parsing unchanged.【F:docs/CR-004.md†L18-L199】【F:docs/CR-004.md†L253-L370】

## Deliverables
- Backend preference-mode API and pipeline returning structured `filters` plus telemetry metadata.【F:docs/CR-004.md†L289-L312】
- Frontend mode switch and console adjustments to separate **Holiday request** vs **Preferences** flows with revised labels/actions.【F:docs/CR-004.md†L253-L276】
- CSV logging and import/summary integration for performance and accuracy benchmarking in preference mode.【F:docs/CR-004.md†L196-L225】【F:docs/CR-004.md†L373-L399】
- Fixtures loader and cache for `filters_options.csv` with validation on startup.【F:docs/CR-004.md†L315-L342】
- Tests covering backend logic, UI toggling, and statistical summary behaviour (P95 + accuracy).【F:docs/CR-004.md†L241-L245】【F:docs/CR-004.md†L387-L399】

## Work Breakdown
### 1) Backend: Interpretation Mode & Routing
- Add a `preferences` interpretation mode to the API surface (e.g., `/v1/preferences/parse`) that accepts `{ text, mode="preferences", method }`. Keep `/v1/parse` behaviour unchanged for holiday search.【F:docs/CR-004.md†L289-L312】
- Wire mode detection into request handling so only one mode executes per call and both paths reuse language detection and timing guards from the existing pipeline.【F:docs/CR-004.md†L253-L263】【F:docs/SDD_v001_041125.md†L9-L26】
- Extend response schema for preference calls to include `filters`, `metadata.method`, `metadata.mode`, `metadata.timings.totalMs`, and optional `metadata.mappings`.【F:docs/CR-004.md†L301-L312】

### 2) Backend: Filters Catalogue & Mapping Logic
- Implement a loader that reads `filters_options.csv` from `FIXTURES_DIR`, validates readability/delimiter on startup, and caches structured filters/options (id + label). Fail fast if missing or invalid.【F:docs/CR-004.md†L315-L342】
- Define a `FilterSelection` domain model restricting mapped options to catalogue entries; allow optional synonyms/keyword hints for method-specific use.【F:docs/CR-004.md†L345-L356】
- Add preference-mapping strategies (rules, LLM, hybrid) registered in the methods catalogue. Ensure only catalogue-backed options are emitted and include `status: "no-preferences-detected"` when empty/low confidence.【F:docs/CR-004.md†L358-L370】

### 3) Backend: Logging, Imports, and Summaries
- Extend CSV logger to persist preference-mode runs using existing columns, embedding mapped filters/options JSON in `Output` and status in `Status`.【F:docs/CR-004.md†L196-L199】【F:docs/CR-004.md†L373-L378】
- Update import runner to accept preference datasets (text + expected mappings), passing `mode=preferences` and grouping stats by `method`.【F:docs/CR-004.md†L208-L245】
- Ensure `/v1/import/summary` consumes preference runs without schema change, applying P95 bootstrap vs `IMPORT_P95_THRESHOLD_MS` and binomial accuracy vs `IMPORT_ACCURACY_THRESHOLD`, respecting `MIN_SAMPLE_SIZE` and `P95_OUTLIERS_THRESHOLD`.【F:docs/CR-004.md†L381-L399】

### 4) Frontend: Mode Switch & Console Updates
- Add a single mode switch (toggle/segmented control) that activates either **Holiday request** or **Preferences**, never both. Persist selected mode into API payloads.【F:docs/CR-004.md†L253-L263】
- When in Preferences mode: update console title; relabel the primary text area to “Add your preferences”; hide `Default Participants`, `Flexibility, days`, `Airports`, and `Destinations`; keep `Method`, `Parse request`, `Import CSV`, `Export CSV`, `Reset`.【F:docs/CR-004.md†L253-L276】
- Render mapped filters grouped by filter label, showing options (and optional text span hints) returned from the backend.【F:docs/CR-004.md†L190-L195】【F:docs/CR-004.md†L301-L312】
- Maintain existing holiday-search UI when that mode is active (labels and inputs per SRS baseline).【F:docs/SRS_v003_011125.md†L157-L184】

### 5) Performance Guardrails
- Reuse stopwatch logic to capture total processing time for preference mode and flag `thresholdBreached` using `PROCESSING_THRESHOLD_MS`.【F:docs/SDD_v001_041125.md†L9-L26】
- Ensure import runner and summary dashboards surface P95 timing and inference text in Preferences mode (CR-003 style blocks).【F:docs/CR-004.md†L381-L399】

## Test Plan
- **Backend unit/integration**
  - `test_preferences_parse_success`: POST `/v1/preferences/parse` with text "Wi-Fi in all rooms" yields `filters` including Wi-Fi-related option(s) from catalogue; status success; `metadata.mode="preferences"`; timing present.【F:docs/CR-004.md†L234-L235】【F:docs/CR-004.md†L301-L312】
  - `test_preferences_parse_no_match`: text with no catalogue coverage returns empty filters and `status="no-preferences-detected"`.【F:docs/CR-004.md†L365-L370】
  - `test_preferences_negative_preference`: text "no catering but scuba required" returns `Boards: Room Only` plus `Facilities: Scuba` options, constrained to CSV catalogue.【F:docs/CR-004.md†L234-L235】【F:docs/CR-004.md†L345-L356】
  - `test_filters_catalogue_load`: startup raises if `filters_options.csv` missing or unreadable; caches structured filters/options with ids/labels.【F:docs/CR-004.md†L315-L342】
  - `test_method_selection_logged`: selected method echoed in response metadata and CSV output; grouping by method preserved in import processing.【F:docs/CR-004.md†L196-L225】【F:docs/CR-004.md†L242-L245】
  - `test_performance_threshold_flag`: simulate slow preference mapping to assert `thresholdBreached` toggles when exceeding `PROCESSING_THRESHOLD_MS`.【F:docs/SDD_v001_041125.md†L9-L26】
  - `test_import_summary_preferences`: feed sample preference import runs to `/v1/import/summary` and verify P95 bootstrap + binomial accuracy inference respect thresholds and minimum sample size rules.【F:docs/CR-004.md†L381-L399】

- **Frontend/UI**
  - `test_mode_switch_toggle`: ensures only one mode active; payloads send correct mode string; labels/input visibility change per mode.【F:docs/CR-004.md†L253-L276】
  - `test_preferences_console_render`: in Preferences mode, input label shows “Add your preferences”; mapped filters/options render grouped by filter with method visible.【F:docs/CR-004.md†L234-L235】【F:docs/CR-004.md†L301-L312】
  - `test_holiday_mode_regression`: switching back to Holiday request restores original fields/labels and uses search parsing endpoint per SRS.【F:docs/SRS_v003_011125.md†L141-L184】【F:docs/CR-004.md†L253-L276】

- **Performance/telemetry**
  - `test_processing_time_recorded`: timing captured for preference runs and included in CSV log row alongside filters output.【F:docs/CR-004.md†L196-L225】
  - `test_import_outlier_filtering`: import summary excludes outliers per `P95_OUTLIERS_THRESHOLD` before computing P95 for preference runs.【F:docs/CR-004.md†L216-L224】【F:docs/CR-004.md†L381-L399】

## Rollout & Ops
- Add environment toggles and defaults for preference mapping (e.g., `PREFERENCES_ENABLED`, path to `filters_options.csv`) ensuring `.env` documentation is updated alongside config templates.【F:docs/CR-004.md†L315-L342】
- Provide seed `filters_options.csv` in fixtures with example Wi-Fi/Scuba/Boards rows to support tests and demos.【F:docs/CR-004.md†L90-L107】
- Update monitoring/metrics dashboards to include preference-mode latency and accuracy grouped by method, reusing existing summary visualizations.【F:docs/CR-004.md†L208-L245】【F:docs/CR-004.md†L381-L399】
