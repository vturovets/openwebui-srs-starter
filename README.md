# OpenWebUI SRS Starter

Prototype monorepo for the **NLP-Powered Holiday Request** project outlined in the
accompanying Software Requirements Specification (SRS) and Software Design
Description (SDD). It ships a deterministic FastAPI backend, a Vite + Svelte
frontend, and supporting fixtures so teams can benchmark NLP strategies end-to-end.

The backend accepts natural-language holiday requests, derives structured
parameters through a transparent pipeline, and records every transaction to a CSV
audit trail. Dialogue flows, voice transcription, import guardrails, and pluggable
LLM strategies are implemented as explicit modules so alternative approaches can
be swapped in while retaining comparable output for experiments.

### Highlights

- **Deterministic NLP pipeline** – [`backend/app/pipeline`](backend/app/pipeline)
  wires together language detection, rule/LLM extraction, data normalisation, and
  validation. Every stage is observable for benchmarking and experimentation.
- **Bulk import runner with guardrails** – [`backend/app/services/import_runner.py`](backend/app/services/import_runner.py)
  powers CSV/backlog ingestion with retry, concurrency, and resource controls that
  mirror the production expectations described in [`docs/imports.md`](docs/imports.md).
- **Resource-aware telemetry** – [`backend/app/telemetry/resource_monitor.py`](backend/app/telemetry/resource_monitor.py)
  samples CPU and memory usage so long-running imports can throttle themselves
  before overwhelming shared environments.
- **CSV-backed observability** – [`backend/app/logging/csv_logger.py`](backend/app/logging/csv_logger.py)
  emits a stable schema that the frontend can replay for A/B comparisons and
  regressions analysis.
- **Frontend parity** – [`frontend/`](frontend) reproduces the OpenWebUI flow with
  component tests (Vitest) and Playwright E2E coverage for interactive journeys.
- **Utterance dataset generator (CR-006)** – [`tools/utterance_generator`](tools/utterance_generator)
  builds single-option and multi-option utterance datasets from the filters
  lexicon and scores embeddings for purity/separation checks.
- **Free-text preference mapping (CR-004)** – [`backend/app/pipeline/preferences.py`](backend/app/pipeline/preferences.py)
  interprets preference-oriented utterances (e.g. _“room only, scuba, strong
  Wi‑Fi”_) and maps them to structured filters/options from
  [`fixtures/filters_options.csv`](fixtures/filters_options.csv), logging mapping
  spans and method metadata alongside timing thresholds.

## Project structure

```
.
├── backend/
│   ├── app/                    # FastAPI application, API routes, pipeline stages, services, integrations
│   └── tests/                  # Pytest coverage for API contracts, pipeline flows, and fixtures
├── config/                     # Method catalogue and supporting YAML
├── docs/                       # SRS, SDD, and integration reference material
├── fixtures/                   # Airports, destinations, durations, and configuration JSON
├── frontend/                   # Svelte SPA that consumes the backend contract
├── scripts/                    # Helper scripts (PowerShell launcher, bulk import CLI)
├── Makefile                    # Convenience targets for linting and tests
└── pyproject.toml              # Backend dependency metadata
```

## Backend setup

### Prerequisites

- Python 3.10 or newer
- `pip` for installing dependencies
- `ffmpeg` available on `PATH` (required by the local faster-whisper fallback)
- (Optional) `make` for shortcut commands defined in the root `Makefile`

### Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .[dev]
```

The editable install pulls both runtime and development dependencies
(FastAPI, uvicorn, pytest, ruff, etc.).

### Useful commands

| Task | Command |
| --- | --- |
| Run API locally | `uvicorn backend.app.main:app --reload`
| Lint backend code | `make lint` *(ruff check backend)* |
| Run backend + frontend tests | `make test` *(pytest + npm test)* |

### Synonym lexicon generator (CR-005)

Use the structured Responses API utility to build per-option synonym lexicons from a CSV:

```powershell
python -m tools.synonyms_lexicon `
  --input "data/filters_options_refined_an_131225.csv" `
  --output "out/synonyms_lexicon.json" `
  --batch-size 150 `
  --model "gpt-5.2" `
  --temperature 0.3 `
  --max-synonyms 10 `
  --raw-dir "out/raw_responses"
```

Flags `--resume`, `--dry-run`, `--rate-limit-sleep`, `--max-retries`, and `--timeout` control resumability and resilience. Metadata is stored alongside the output file.

### Utterance dataset generator (CR-006)

Create labelled utterance datasets from a filter lexicon and score embeddings for
purity/coverage:

```bash
# Generate single-option utterances (preference_only + mini_query) via OpenAI Responses
python -m tools.utterance_generator single \
  --lexicon fixtures/filters_options.csv \
  --output out/single_utterances.json \
  --max-per-option 3 \
  --show-curl

# Generate 20 multi-option utterances (2–4 options per combo) via OpenAI Responses
python -m tools.utterance_generator multi \
  --lexicon fixtures/filters_options.csv \
  --output out/multi_combos.json \
  --count 20 \
  --seed 13

# Score embeddings against centroids to flag purity/coverage issues
python -m tools.utterance_generator score \
  --lexicon fixtures/filters_options.csv \
  --utterances data/utterances.jsonl \
  --output out/scoring_report.json \
  --embedding-model text-embedding-3-small \
  --show-curl

# Sample existing utterance JSON into a flat CSV
python -m tools.utterance_generator sample \
  --single-file out/single_utterances.json \
  --single-count 10 \
  --multi-file out/multi_combos.json \
  --multi-count 5 \
  --seed 99 \
  --output out/sampled_utterances.csv
```

Use `.env`/environment variables (e.g., `OPENAI_API_KEY`) to configure the
OpenAI client. `score` expects a JSONL file where each record includes an
`embedding` vector and the target `option_ids` array.

## Configuration

Runtime settings come from environment variables or a local `.env` file at the
repository root. The `Settings` class in [`backend/app/config.py`](backend/app/config.py)
controls the available options and ensures required directories exist before
serving traffic. Key options mirror the SRS:

| Variable | Default | Description |
| --- | --- | --- |
| `INTERACTION_MODE` | `direct-parse` | Choose `direct-parse` for single-shot parsing or `dialog` to allow clarification flows (UI support required). |
| `ALLOWED_LANGS` | `en` | Comma-separated ISO language codes accepted by the language detector (v1 ships with English only). |
| `CSV_PATH` | `data/log.csv` | Path to the CSV audit log; directories are created automatically. |
| `CSV_DELIMITER` | `,` | Single-character delimiter used when writing the CSV audit log. |
| `IMPORT_SUMMARY_PATH` | `data/import_summary.csv` | Optional path for persisting roll-up import summaries (empty string disables the sink). |
| `IMPORT_SUMMARY_DELIMITER` | `,` | Single-character delimiter for the import summary CSV sink. |
| `LLM_METHOD` | _(unset)_ | Optional identifier for the NLP technique under evaluation (e.g., `rules`, `llm`, `hybrid`). |
| `LLM_API_BASE` | _(unset)_ | Override the LLM provider base URL when using a proxy or self-hosted gateway. |
| `LLM_API_KEY` | _(unset)_ | Credential passed to the structured LLM client when `LLM_METHOD=llm` or `hybrid`. |
| `LLM_MODEL` | `gemini-2.5-flash` | Model identifier requested from the LLM provider. |
| `LLM_TIMEOUT` | `30` | Client-side timeout (seconds) for outbound LLM requests. |
| `STT_ENGINE` | _(unset)_ | Speech-to-text engine label when voice capture is enabled (e.g., `deepgram`). |
| `DEEPGRAM_API_KEY` | _(unset)_ | API key for Deepgram when `STT_ENGINE=deepgram`. |
| `FALLBACK_WHISPER_MODEL` | `small.en` | Local model identifier used by `faster-whisper` when Deepgram credentials are missing. |
| `FALLBACK_WHISPER_DEVICE` | `auto` | Device hint forwarded to `faster-whisper` (`auto`, `cpu`, `cuda`, etc.). |
| `FALLBACK_WHISPER_COMPUTE_TYPE` | `default` | Compute type passed to `faster-whisper` (`default`, `int8`, `int8_float16`, ...). |
| `FALLBACK_WHISPER_CACHE_DIR` | _(unset)_ | Optional directory for caching `faster-whisper` model downloads. |
| `VOICE_ENABLED` | `false` | Toggle indicating whether voice input is active in the UI. |
| `VOICE_MAX_BYTES` | `10000000` | Maximum audio payload size accepted by `/v1/voice` in bytes. |
| `VOICE_ALLOWED_CONTENT_TYPES` | see code | Comma-separated list of MIME types accepted by `/v1/voice` (defaults cover WAV, MP3, OGG, WebM, and FLAC). |
| `FIXTURES_DIR` | `fixtures` | Directory containing the JSON fixture files. |
| `FILTERS_OPTIONS_PATH` | `fixtures/filters_options.csv` | Catalogue used by preference mappers; relative paths resolve under `FIXTURES_DIR`. |
| `PREFERENCES_RULES_SYNONYMS_PATH` | `fixtures/rule_based_synonyms.json` | Synonym dictionary consumed by the rule-based preferences mapper. |
| `PREFERENCES_RULES_LANGS` | `en` | Languages accepted by the rule-based preferences pipeline (comma-separated list). |
| `PREFERENCES_RULES_THRESHOLD` | `0.6` | Confidence cut-off for marking rule-based preference options as selected. |
| `PREFERENCES_RULES_NEGATION_PENALTY` | `0.25` | Penalty applied per negated hit when scoring rule-based matches. |
| `POPULARITY_IMPUTER_ENABLED` | `true` | Enable or disable the popularity-based imputer that fills missing dates, airports, and party values using historic stats. Only applied when `LLM_METHOD=hybrid`. |
| `POPULARITY_DATA_PATH` | `fixtures/popularity_stats.json` | Location of the persisted popularity statistics. Relative paths are resolved under `FIXTURES_DIR`. |
| `METHODS_CONFIG_PATH` | `config/methods.yaml` | YAML catalogue describing available parsing methods and hybrid strategies. |
| `PROCESSING_THRESHOLD_MS` | `1000` | Millisecond budget; responses note if total processing time exceeds this value. |
| `SHOW_RESULTS` | `SHOW_ALL` | Controls whether imported CSV logs are visible in the UI: `SHOW_ALL` (default) displays everything, `SHOW_FAILED_ONLY` limits visibility to failures, and `SUPPRESS` hides all rows. |
| `IMPORT_P95_THRESHOLD_MS` | `750` | Target P95 latency (ms) used when flagging slow imported runs in the performance summary. |
| `IMPORT_P95_SAMPLE_SIZE` | `1000` | Minimum number of imported rows required before computing a P95 value. |
| `IMPORT_P95_SIGNIFICANCE` | `0.95` | Percentile (0–1) applied when calculating the imported response-time P95 metric. |
| `MIN_SAMPLE_SIZE` | `1000` | Minimum observations required before issuing statistical inferences for P95/accuracy. |
| `IMPORT_ACCURACY_THRESHOLD` | `0.85` | Target accuracy (0–1) checked with an exact binomial test during imports. |
| `P95_OUTLIERS_THRESHOLD` | `10000` | Discard imported timings above this many milliseconds before P95 calculations. |
| `ALPHA` | `0.05` | Significance level (alpha) used when constructing confidence intervals. |
| `IMPORT_WORKER_CONCURRENCY` | `8` | Maximum worker tasks scheduled simultaneously per import job. |
| `IMPORT_MAX_CONCURRENCY` | `32` | Hard ceiling for concurrent import worker tasks, even when overrides request more parallelism. |
| `IMPORT_BATCH_SIZE` | `64` | Number of queued requests submitted before awaiting completion to avoid overwhelming the runtime. |
| `IMPORT_CPU_THRESHOLD` | `90` | Pause scheduling when the 1-minute CPU load estimate exceeds this percentage. |
| `IMPORT_MEMORY_THRESHOLD_MB` | `4096` | Pause scheduling when estimated RAM usage exceeds this many megabytes. |
| `IMPORT_PAUSE_SECONDS` | `0.1` | Duration to sleep before re-checking system load while throttling import execution. |
| `IMPORT_RETRY_ATTEMPTS` | `3` | Number of retries applied to transient pipeline errors during imports. |
| `IMPORT_RETRY_BACKOFF_SECONDS` | `0.25` | Initial exponential backoff delay between retries for transient errors. |
| `VITE_CONSOLE_MODE` | `both` | Frontend console toggle: `holiday` shows Holiday Search only, `preferences` shows Preferences only, and `both` shows the mode switcher. |

> **Note:** When `STT_ENGINE=deepgram` but the `DEEPGRAM_API_KEY` is omitted, the
> backend falls back to a local `faster-whisper` model. Install it with `pip
> install faster-whisper` and ensure `ffmpeg` is on your `PATH` so uploaded audio
> can be decoded. Tune the local runtime using `FALLBACK_WHISPER_MODEL`,
> `FALLBACK_WHISPER_DEVICE`, `FALLBACK_WHISPER_COMPUTE_TYPE`, and
> `FALLBACK_WHISPER_CACHE_DIR`. 【F:backend/app/dependencies.py†L133-L168】【F:backend/app/integrations/stt.py†L131-L240】

Create a `.env` file to override defaults, for example:

```
INTERACTION_MODE=direct-parse
ALLOWED_LANGS=en
CSV_PATH=data/log.csv
CSV_DELIMITER=;
# Enable the structured LLM path (hybrid required for the imputer)
LLM_METHOD=hybrid
LLM_API_KEY=sk-your-key
LLM_MODEL=gemini-2.5-flash
# Optional when routing through a proxy/self-hosted gateway
# LLM_API_BASE=https://generativelanguage.googleapis.com/v1beta
# Rule-based preferences configuration
PREFERENCES_RULES_SYNONYMS_PATH=fixtures/rule_based_synonyms.json
PREFERENCES_RULES_LANGS=en
PREFERENCES_RULES_THRESHOLD=0.6
PREFERENCES_RULES_NEGATION_PENALTY=0.25
# Enable the popularity imputer (only used when LLM_METHOD=hybrid) and override the stats filename (relative to FIXTURES_DIR)
POPULARITY_IMPUTER_ENABLED=true
POPULARITY_DATA_PATH=popularity_stats.json
PROCESSING_THRESHOLD_MS=750
IMPORT_P95_THRESHOLD_MS=1250
IMPORT_P95_SAMPLE_SIZE=2000
IMPORT_P95_SIGNIFICANCE=0.9
MIN_SAMPLE_SIZE=1200
IMPORT_ACCURACY_THRESHOLD=0.9
P95_OUTLIERS_THRESHOLD=12000
ALPHA=0.05
```

When deploying with Docker Compose, mirror the same environment variables in the
service definition so the backend receives the credentials at startup. Bind-mount
a `.env` file or rely on Compose variable substitution to keep secrets out of
version control. A minimal service definition looks like:

```yaml
services:
  backend:
    build: ./backend
    environment:
      - INTERACTION_MODE=${INTERACTION_MODE:-direct-parse}
      - CSV_PATH=/logs/transactions.csv
      - LLM_METHOD=${LLM_METHOD:-rules}
      - LLM_API_BASE=${LLM_API_BASE:-https://generativelanguage.googleapis.com/v1beta}
      - LLM_MODEL=${LLM_MODEL:-gemini-2.5-flash}
```

### Method catalog

Structured extraction strategies are described in [`config/methods.yaml`](config/methods.yaml). The loader merges the `defaults` block with each enabled method, applies environment-variable substitutions (for example `${OPENAI_BASE}`), and resolves hybrid definitions into concrete stage sequences before caching the result in [`Settings`](backend/app/config.py). Each entry is surfaced through the `/v1/fixtures` endpoint, and the pipeline metadata always includes:

- `availableMethods` – ordered list of enabled methods with labels, provider metadata, and runtime params.
- `defaultMethod` / `methodDefaults` – resolved defaults shared across methods (time-outs, temperatures, etc.).
- `catalogSize` – count of enabled strategies, useful for UI summaries.
- `requestedAlias` – caller-supplied alias that mapped to the resolved pipeline method.

- **Rules/LLM entries** – declare provider metadata, tunable parameters, and optional `api_key_env` indirection to avoid storing secrets in the catalog.
- **Hybrid entries** – reference existing methods via `stages` and optionally specify a `fallback` that runs when upstream stages fail.

Update `METHODS_CONFIG_PATH` to point at an alternate YAML file if you need to swap in different evaluation strategies per environment.

### Preference mapping mode (CR-004)

The **Free-Text Preference → Filter Mapping** capability accepts preference
utterances via `POST /v1/preferences/parse` using the same request envelope as
`/v1/parse` (`{ text, mode, method? }`). Responses include detected language,
mapped filters/options grouped by filter label, mapping spans, and timing
metadata. The method catalogue (`LLM_METHOD` and `config/methods.yaml`) drives
which rule/LLM/hybrid strategies are used, while the canonical filter taxonomy
is loaded from [`fixtures/filters_options.csv`](fixtures/filters_options.csv) and
tunable via `FILTERS_OPTIONS_*` and `PREFERENCES_RULES_*` settings (synonyms,
accepted languages, thresholds, negation penalties). Preference mapping calls
participate in the same CSV logging and import/summary flow as holiday search so
P95/accuracy stats can be compared across methods.

## Bulk import operations

High-volume backlogs can be processed with the [`ImportJobRunner`](backend/app/services/import_runner.py). It batches
`/v1/parse` requests, automatically retries transient failures, and applies
guardrails to keep resource usage stable. Configuration is exposed through
environment variables such as `IMPORT_WORKER_CONCURRENCY`,
`IMPORT_BATCH_SIZE`, `IMPORT_RETRY_ATTEMPTS`, and the CPU/memory thresholds used
by the telemetry sampler. Consult [`docs/imports.md`](docs/imports.md) for
operational guidance and tuning tips.

The repository includes [`scripts/run_import.py`](scripts/run_import.py) for
running imports from the command line. Provide a JSON file containing an array
of parse requests (each entry can be a string or `{ text, mode?, method? }`)
and optional `--mode`/`--method` defaults. The script prints a roll-up JSON
summary to stdout and, when `IMPORT_SUMMARY_PATH` is configured, writes a single
row to the import summary CSV.

## Import summary endpoint

POST `/v1/import/summary` accepts raw import-operation metadata (status plus
the captured `metadata` payload) and returns statistically robust performance
and usage summaries. The service filters outliers above `P95_OUTLIERS_THRESHOLD`,
bootstraps the import P95 against `IMPORT_P95_THRESHOLD_MS` using the configured
`ALPHA`/`ALPHA` level, and runs an exact binomial test against
`IMPORT_ACCURACY_THRESHOLD` once `MIN_SAMPLE_SIZE` observations are available.
The frontend import flow calls this endpoint after replaying CSV rows so the UI
can surface thresholds, inferences, and resource footprints consistently.

## Telemetry & guardrails

Import runs sample host resources via the
[`ResourceMonitor`](backend/app/telemetry/resource_monitor.py). When CPU or
memory utilisation exceeds configured thresholds, scheduling pauses until the
host recovers. Guardrail actions, retry counts, and latency percentiles are
reported in the [`ImportSummary`](backend/app/services/import_runner.py) data
model so the UI (or CLI) can surface performance regressions.

## Running the backend

Launch the FastAPI app with uvicorn (after activating your virtual environment):

```bash
uvicorn backend.app.main:app --reload
```

The service starts on `http://127.0.0.1:8000` by default. FastAPI’s interactive
docs are available at `/docs` and `/redoc`. To make the API reachable by
Open-WebUI or other remote clients, bind to all interfaces and front it with a
reverse proxy or tunnel, for example:

```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
ngrok http 8000
```

Use the HTTPS forwarding URL reported by your tunnel as the base URL when
configuring Open-WebUI. See [`docs/ui_integration_contracts.md`](docs/ui_integration_contracts.md)
for the full endpoint contracts, and [`docs/openwebui_configuration.md`](docs/openwebui_configuration.md)
for step-by-step instructions on wiring the custom Open-WebUI connector and renderer.

Behind the scenes, reusable dependencies are provided via
[`backend/app/dependencies.py`](backend/app/dependencies.py). Settings,
`HolidaySearchPipeline`, the CSV logger, speech-to-text client, and dialog
orchestrator all use `functools.lru_cache` to keep reloads fast while preserving
deterministic behaviour in tests.

## Backend architecture

The NLP pipeline lives under [`backend/app/pipeline`](backend/app/pipeline) and
is orchestrated by [`HolidaySearchPipeline`](backend/app/pipeline/pipeline.py).
The high-level flow is:

1. **Language detection** – [`LanguageDetector`](backend/app/pipeline/language.py)
   validates the utterance against allowed languages and surfaces confidence
   scores.
2. **Extraction** – [`RulesExtractor`](backend/app/pipeline/extractor_rules.py)
   parses known patterns while [`LLMExtractor`](backend/app/pipeline/extractors.py)
   optionally calls an injected LLM client. [`HybridExtractor`](backend/app/pipeline/extractors.py)
   combines both strategies when requested.
3. **Normalisation** – [`Normalizer`](backend/app/pipeline/normalizer.py)
   maps raw matches to structured IDs using fixture-driven configuration.
4. **Validation** – [`Validator`](backend/app/pipeline/validator.py)
   ensures the payload satisfies availability constraints from
   [`fixtures/`](fixtures) and raises `ValidationError` when remediation is
   required.
5. **Timing and metadata** – the pipeline records per-stage timings,
   requested/used method, recognized entities, missing/invalid fields, and any
   validation errors so the API can report detailed diagnostics.

The dialog experience is layered on top via
[`DialogOrchestrator`](backend/app/pipeline/dialog.py), which inspects
validation failures and returns clarification prompts or session context. CSV
instrumentation is handled by [`CSVLogger`](backend/app/logging/csv_logger.py),
which writes a stable schema defined in
[`backend/app/dependencies.py`](backend/app/dependencies.py). The exported log
intentionally contains two **Language Detection** columns: the first stores the
timing budget, while the second records the textual summary (language code plus
confidence).

### Fixtures

Fixture JSON files in [`fixtures/`](fixtures) and
[`backend/app/fixtures`](backend/app/fixtures) act as the canonical source of
truth for airports, destinations, durations, and configuration defaults. The
[`FixtureRepository`](backend/app/fixtures/repository.py) exposes typed access to
these resources so pipeline stages can remain deterministic. The
`/v1/fixtures` response also reflects runtime toggles such as
`voiceEnabled` and `showResults`, mirroring the current [`Settings`](backend/app/config.py).

### Voice capture

When `VOICE_ENABLED=true`, the API exposes `/v1/voice` and wires in an optional
speech-to-text client via `get_stt_client`. The default implementation is
[`DeepgramSpeechToTextClient`](backend/app/integrations/stt.py), which streams
audio to Deepgram’s REST API and returns word-level timings for the UI. The
`VoiceResponse` payload reports the transcription status, selected engine, word
timings, and the downstream pipeline metadata so voice and text flows stay
aligned. If `STT_ENGINE=deepgram` but `DEEPGRAM_API_KEY` is not provided, the
service automatically falls back to a local `faster-whisper` instance configured
via `FALLBACK_WHISPER_MODEL`, `FALLBACK_WHISPER_DEVICE`,
`FALLBACK_WHISPER_COMPUTE_TYPE`, and `FALLBACK_WHISPER_CACHE_DIR`. Install
`ffmpeg` alongside `faster-whisper` so the local decoder can open common audio
formats; the `engine` field in the response will surface `faster-whisper` when
this path is active. 【F:backend/app/config.py†L84-L120】【F:backend/app/integrations/stt.py†L131-L240】

## Frontend quick start

The `frontend/` directory contains a Vite + Svelte single-page application that
consumes the backend contract and mirrors the Open-WebUI holiday search
experience. To work on the UI locally (default dev server on <http://127.0.0.1:4173>):

```bash
cd frontend
npm install
npm run dev -- --open
```

Additional scripts:

| Task | Command |
| --- | --- |
| Run component tests | `npm test` *(Vitest)* |
| Run component tests in watch mode | `npm run test:watch` |
| Run Playwright E2E tests | `npm run test:ui` |
| Build production bundle | `npm run build` |
| Preview built bundle | `npm run preview` |

Vitest is configured with JSDOM in [`frontend/vitest.setup.ts`](frontend/vitest.setup.ts),
and Playwright suites live under [`frontend/tests`](frontend/tests).

## API endpoints

| Method & Path | Description |
| --- | --- |
| `GET /health` | Returns `{ "status": "ok" }` plus the active interaction mode for readiness checks. |
| `POST /v1/parse` | Parses a natural-language utterance and responds with structured holiday parameters, validation metadata, and timing metrics. |
| `POST /v1/preferences/parse` | Maps free-text preferences to structured filters/options using rule/LLM/hybrid strategies and returns mapping spans plus timing metadata. |
| `POST /v1/dialog` | Maintains clarification sessions, returning prompts and accumulating transcript context when `INTERACTION_MODE=dialog`. |
| `GET /v1/fixtures` | Exposes airports, destinations, available check-in dates, configuration defaults, enabled methods, and UI hints such as `voiceEnabled`/`showResults`. |
| `POST /v1/import/summary` | Accepts previously captured import metadata and returns performance/accuracy/usage roll-ups aligned with the UI dashboards. |
| `POST /v1/voice` | Streams uploaded audio to the configured STT engine, returns the transcript with timing data, and forwards the utterance into the holiday search pipeline. |

### Sample `/v1/parse` request

```http
POST /v1/parse
Content-Type: application/json

{
  "text": "Book a trip from Amsterdam to Italy on 10 October 2025 for 7 nights",
  "method": "rules"
}
```

### Sample response

```json
{
  "status": "success",
  "data": {
    "language": "en",
    "from": ["AMS"],
    "to": ["d7b4bb39-123c-1234-b123-1234567i:COUNTRY"],
    "departureDate": ["2026-10-10", "2026-10-16"],
    "durationId": "2007",
    "party": {"adults": 2, "nonAdults": 0},
    "rooms": null
  },
  "metadata": {
    "methodId": "rules-basic",
    "methodType": "rules",
    "requestedAlias": "rules",
    "mode": "direct-parse",
    "method": "rules-basic",
    "requestedMethod": "rules-basic",
    "timings": {
      "languageMs": 896.89,
      "extractionMs": 3648.19,
      "normalizationMs": 0.22,
      "validationMs": 0.12,
      "totalMs": 4545.61,
      "thresholdBreached": true
    },
    "validation": {"status": "passed", "errors": []},
    "transcript": [
      {"role": "user", "text": "Book a trip from Amsterdam to Italy on 10 October 2025 for 7 nights"}
    ],
    "recognized": {
      "airports": [{"id": "AMS", "name": "Amsterdam", "available": true}],
      "destinations": [{"id": "d7b4bb39-123c-1234-b123-1234567i", "name": "Italy", "type": "COUNTRY", "available": true}],
      "duration": {"id": "2007", "name": "7 nights", "isDefault": true},
      "flexibility": null,
      "dates": [{"phrase": "on 10", "iso": "2026-10-13T00:00:00"}]
    },
    "recognizedEntities": {
      "airports": ["AMS"],
      "destinations": ["d7b4bb39-123c-1234-b123-1234567i"],
      "dates": ["2026-10-13T00:00:00"],
      "duration": "2007",
      "flexibility": null
    },
    "missingFields": [],
    "invalidFields": [],
    "language": {"code": "en", "confidence": 0.9999951336379177},
    "attempts": [
      {"method": "rules-basic", "type": "rules", "status": "success"}
    ],
    "llm": {},
    "availableMethods": [
      {
        "id": "rules-basic",
        "type": "rules",
        "label": "rules-basic",
        "params": {
          "timeout_s": 30,
          "temperature": 0.0,
          "dictionary_filename": "data/dictionary.csv",
          "configuration_filename": "configs/rules.conf"
        }
      },
      {
        "id": "gemini-2.5-flash",
        "type": "llm",
        "label": "gemini-2.5-flash",
        "params": {
          "timeout_s": 30,
          "temperature": 0.1,
          "max_output_tokens": 1024,
          "top_p": 0.95,
          "top_k": 40
        },
        "provider": "google",
        "model": "gemini-2.5-flash",
        "api_base": "https://generativelanguage.googleapis.com/v1beta",
        "api_key_env": "GOOGLE_API_KEY"
      },
      {
        "id": "hybrid-v1",
        "type": "hybrid",
        "label": "hybrid-v1",
        "params": {
          "timeout_s": 30,
          "temperature": 0.0
        },
        "strategy": "cascade",
        "stages": ["rules-basic", "gemini-2.5-flash"],
        "fallback": "gemini-2.5-flash"
      }
    ],
    "defaultMethod": "rules-basic",
    "methodDefaults": {"timeout_s": 30, "temperature": 0.0},
    "catalogSize": 3
  }
}
```

## Testing checklist

- **Backend** – run `make lint` and `make test` before opening a pull request.
- **Frontend** – run `npm test` for component coverage and `npm run test:ui`
  for Playwright E2E suites when UI changes impact flows.

## Further reading

- [`docs/ui_integration_contracts.md`](docs/ui_integration_contracts.md) – API
  request/response contracts shared with the Open-WebUI extension.
- [`docs/openwebui_configuration.md`](docs/openwebui_configuration.md) – UI
  configuration steps for pointing Open-WebUI at this backend.
- [`docs/srs.md`](docs/srs.md) and [`docs/sdd.md`](docs/sdd.md) – detailed
  requirements and design documentation for the prototype.

## Popularity statistics fixture

The popularity imputer described in [`docs/CR-001.md`](docs/CR-001.md) consumes the
pre-computed statistics stored in [`fixtures/popularity_stats.json`](fixtures/popularity_stats.json).
It only activates when `LLM_METHOD=hybrid`; other modes force `POPULARITY_IMPUTER_ENABLED` to `false`
even if the variable is set. Use `POPULARITY_DATA_PATH` to point at alternate stats files.
Relative values are resolved under `FIXTURES_DIR`, so `POPULARITY_DATA_PATH=popularity_stats.json`
will resolve to `<fixtures_dir>/popularity_stats.json` automatically.
The file is regenerated from `docs/demo_set_example.csv` and exposes the
following schema so the backend can decide whether to use global trends or
destination-specific modes:

- `metadata` – includes the schema version, UTC generation timestamp, source
  CSV path, the SHA-256 checksum of that CSV (used to detect stale fixtures),
  the number of processed rows, the `top_n` limit applied to frequency lists,
  and the fully-qualified generator name (`scripts.build_popularity_stats`).
- `global` – captures the most popular parameters across the entire dataset.
  Each metric (duration, rooms, party tuple, departure interval, departure
  airport) is summarised with `mode`, `mode_count`, `top_values` (up to
  `metadata.top_n` entries), `unique_values`, and the total number of
  observations used. `rooms` keeps `null` whenever the CSV stores a blank value
  and `0` when the source row requested automatic room allocation. `party`
  values are serialised as `{adults, children, infants}` objects. `interval`
  values are `{start, end}` ISO-8601 strings. `global.totals` also records the
  number of rows processed and how many destination mentions were encountered in
  the CSV.
- `destinations` – a dictionary keyed by destination name where each value
  mirrors the global summary fields above so the imputer can prefer
  destination-specific defaults whenever possible.
- `intersections` – captures the most popular departure intervals for historic
  searches that mentioned multiple destinations at once. Each entry stores the
  sorted list of destinations, the modal interval, and the `top_intervals`
  collection so the runtime service can quickly detect overlaps instead of
  recomputing intersections.

### Rebuilding the fixture

Use the helper CLI whenever the CSV changes to regenerate the file referenced by
`POPULARITY_DATA_PATH`:

```bash
make popularity-stats
# or
python -m scripts.build_popularity_stats --csv docs/demo_set_example.csv \
  --output fixtures/popularity_stats.json --pretty
```

The script normalises start/end dates to ISO format, coerces numeric fields,
splits multi-destination rows, and emits the JSON payload above. Because the
metadata captures both a schema version and the CSV checksum, the backend can
fail fast whenever the fixture is out of sync with the raw data.
