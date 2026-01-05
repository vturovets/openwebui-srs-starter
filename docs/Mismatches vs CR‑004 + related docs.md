## Gaps / Mismatches vs CR‑004 + related docs

### 1) **Voice input doesn’t respect Preferences mode (FR‑08)**

**Requirement:** In Preferences mode, voice transcripts should be treated as preference text.  
**Current behavior:** `/v1/voice` always runs the holiday pipeline. There is no mode parameter or branch for preferences. The UI doesn’t pass mode to voice uploads either.

**Evidence**

- Voice endpoint always uses `HolidaySearchPipeline` only. (`backend/app/api/routes.py`)

- MicrophoneWidget never uses the `mode` prop to route to preferences parsing. (`frontend/src/components/MicrophoneWidget.svelte`)

**Impact:** Preferences mode via voice won’t map filters (violates FR‑08).

---

### 2) **“No preferences detected” status is not “failed”**

**Requirement (US‑P1):** If no relevant preferences, status should be shown as **failed**.  
**Current behavior:** The backend returns `status="no-preferences-detected"` and the UI displays that string; it’s not mapped to `failed`.

**Evidence**

- Status set to `no-preferences-detected` in mapper. (`backend/app/pipeline/preferences_mapping.py`)

- Response returns that status verbatim. (`backend/app/api/routes.py`)

- UI renders status directly. (`frontend/src/components/StructuredResult.svelte`)

**Impact:** UI status wording doesn’t match acceptance criteria in CR‑004.

---

### 3) **Preferences import accuracy comparison doesn’t use mapped filters**

**Requirement:** Preference import compares extracted filters/options vs expected mappings (CR‑004 Open Issue #2).  
**Current behavior:** Import comparison uses **holiday search `data` fields** only; preferences results store filters separately (`filters`) and leave `data` empty, so all preference comparisons fail or are empty.

**Evidence**

- `getExtractedValueRows()` only reads `result.data` (holiday fields). (`frontend/src/lib/extractedValues.ts`)

- Import comparison uses `getExtractedValueRows()` only. (`frontend/src/App.svelte`, `frontend/src/lib/importUtils.ts`)

- Preferences responses place filter selections under `filters`, not `data`. (`frontend/src/lib/api.ts`, `backend/app/api/routes.py`)

**Impact:** Accuracy summaries for preferences are inaccurate or unusable.

---

### 4) **CSV schema mismatch risk (filterLabel vs filterName)**

**Requirement:** CR‑004 Open Issue #1 shows `filterId,filterName,optionId,optionName`.  
**Current behavior:** Loader requires `filterId,filterLabel,optionId,optionLabel`.

**Evidence**

- Loader requires `filterLabel`/`optionLabel`. (`backend/app/fixtures/filter_catalogue.py`)

- Fixture uses `filterLabel`/`optionLabel`. (`fixtures/filters_options.csv`)

- CR‑004 examples use `filterName`/`optionName`. (`docs/CR-004.md`)

**Impact:** If a real CSV uses `filterName/optionName`, the loader will fail.

---

### 5) **Failure handling for missing `filters_options.csv` can break holiday mode (FR‑31)**

**Requirement:** Missing/invalid preference catalogue should not break holiday requests.  
**Current behavior:** `PreferencesPipeline` instantiates `FiltersCatalogue` on creation and `/v1/parse` depends on `get_preferences_pipeline`, so missing file could prevent standard `/v1/parse` from working.

**Evidence**

- Preferences pipeline loads catalogue in constructor. (`backend/app/pipeline/preferences.py`)

- `/v1/parse` depends on `get_preferences_pipeline`. (`backend/app/api/routes.py`)

**Impact:** Missing catalogue may break entire app, violating FR‑31.

---

### 6) **Exact console title copy differs**

**Requirement (CR‑004 Open Issue #4):** “Preference console”.  
**Current behavior:** UI uses “Preferences Console.

**Evidence:** `frontend/src/App.svelte` vs `docs/CR-004.md`

**Impact:** Minor copy mismatch.

---

### 7) **Preferences feature toggle (from implementation plan) missing**

**Requirement (implementation plan):** environment toggle like `PREFERENCES_ENABLED`.  
**Current behavior:** No such toggle exists in settings.

**Evidence:** `backend/app/config.py` lacks a preferences enable flag; `docs/implementation_plan_CR004.md`.

**Impact:** Not aligned with related implementation plan.
