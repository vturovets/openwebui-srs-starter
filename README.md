# OpenWebUI SRS Starter

Prototype backend for the **NLP-Powered Holiday Request** project described in the accompanying Software Requirements Specification (SRS) and Software Design Description (SDD). The service exposes a FastAPI application that receives natural-language holiday requests, extracts structured search parameters, validates them against curated fixtures, and records every transaction for benchmarking.

The implementation is intentionally deterministic so that teams can benchmark alternative NLP approaches against a clear baseline. The codebase is organised into a language detector, rule-based extractor, normaliser, and validator backed by configuration fixtures. Each request is timed, logged, and returned with detailed metadata to support UI instrumentation.

## Features

- **Deterministic NLP pipeline** – language detection, rule-based entity extraction, normalization, and validation sequenced as defined in the SRS baseline.
- **Fixture-driven validation** – airports, destinations, and travel configuration are loaded from JSON fixtures so business rules can be tuned without code changes.
- **Performance instrumentation** – every request reports timing breakdowns and flags threshold breaches to help compare alternative NLP approaches.
- **CSV audit trail** – each `/v1/parse` invocation appends a UTF-8 row with the raw input, derived output, method metadata, and final status.
- **Minimal API surface** – health probe, fixture export, and parsing endpoint compatible with an Open-WebUI front end.

## Repository layout

```
.
├── backend/
│   ├── app/            # FastAPI application, pipeline stages, dependencies
│   └── tests/          # Pytest coverage for fixtures, pipeline, and API
├── docs/               # SRS and SDD reference material
├── fixtures/           # Airports, destinations, dates, and configuration JSON
├── Makefile            # Convenience targets for linting and tests
└── pyproject.toml      # Project metadata and dependency list
```

## Prerequisites

- Python 3.10 or newer
- `pip` for installing dependencies
- (Optional) `make` for shortcut commands defined in `Makefile`

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .[dev]
```

The editable install pulls both runtime and development dependencies (FastAPI, uvicorn, pytest, ruff, etc.).

## Configuration

Runtime settings come from environment variables or a local `.env` file at the repository root. The `Settings` class in [`backend/app/config.py`](backend/app/config.py) controls the available options and ensures required directories exist before serving traffic. Key options mirror the SRS:

| Variable | Default | Description |
| --- | --- | --- |
| `INTERACTION_MODE` | `direct-parse` | Choose `direct-parse` for single-shot parsing or `dialog` to allow clarification flows (UI support required). |
| `ALLOWED_LANGS` | `en` | Comma-separated ISO language codes accepted by the language detector (v1 ships with English only). |
| `CSV_PATH` | `data/log.csv` | Path to the CSV audit log; directories are created automatically. |
| `LLM_METHOD` | _(unset)_ | Optional identifier for the NLP technique currently under evaluation (e.g., `rules`, `llm`, `hybrid`). |
| `STT_ENGINE` | _(unset)_ | Speech-to-text engine label when voice capture is enabled. |
| `VOICE_ENABLED` | `false` | Toggle indicating whether voice input is active in the UI. |
| `FIXTURES_DIR` | `fixtures` | Directory containing the JSON fixture files. |
| `PROCESSING_THRESHOLD_MS` | `1000` | Millisecond budget; responses note if total processing time exceeds this value. |

Create a `.env` file to override defaults, for example:

```
INTERACTION_MODE=direct-parse
ALLOWED_LANGS=en
CSV_PATH=data/log.csv
LLM_METHOD=rules
PROCESSING_THRESHOLD_MS=750
```

## Running the API

Launch the FastAPI app with uvicorn (after activating your virtual environment):

```bash
uvicorn backend.app.main:app --reload
```

The service starts on `http://127.0.0.1:8000` by default. FastAPI’s interactive docs are available at `/docs` and `/redoc`.
To make the API reachable by Open-WebUI or other remote clients, bind to all interfaces and front it with a tunnel or reverse proxy, for example:

```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
ngrok http 8000
```

Use the HTTPS forwarding URL reported by your tunnel as the base URL when configuring Open-WebUI. See [`docs/ui_integration_contracts.md`](docs/ui_integration_contracts.md) for the full endpoint contracts, and [`docs/openwebui_configuration.md`](docs/openwebui_configuration.md) for step-by-step instructions on wiring the custom Open-WebUI connector and renderer.

Behind the scenes, the app initialises reusable settings, the holiday search pipeline, and a CSV logger through dependency injection helpers defined in [`backend/app/dependencies.py`](backend/app/dependencies.py). Each dependency uses `functools.lru_cache` so reloads remain quick while preserving deterministic behaviour during tests.

### Endpoints

| Method & Path | Description |
| --- | --- |
| `GET /health` | Returns `{ "status": "ok" }` plus the active interaction mode for readiness checks. |
| `POST /v1/parse` | Core endpoint that parses a natural-language utterance and responds with structured holiday parameters, validation metadata, and timing metrics. |
| `GET /v1/fixtures` | Exposes airports, destinations, available check-in dates, and configuration defaults so clients can pre-populate UI controls. |
| `POST /v1/voice` | Stub endpoint that mirrors the voice-processing metadata and configuration flags exposed to the UI. |

### Sample `/v1/parse` request

```http
POST /v1/parse
Content-Type: application/json

{
  "text": "Book a trip from Amsterdam to Italy on 10 October 2025 for 7 nights",
  "mode": "dialog",
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
    "departureDate": ["2025-10-07", "2025-10-13"],
    "durationId": "2007",
    "party": {"adults": 2, "nonAdults": 0},
    "rooms": null
  },
  "metadata": {
    "mode": "dialog",
    "method": "rules",
    "timings": {
      "languageMs": 1.2,
      "extractionMs": 4.8,
      "normalizationMs": 0.9,
      "validationMs": 0.4,
      "totalMs": 18.6,
      "thresholdBreached": false
    },
    "validation": {
      "status": "passed",
      "errors": []
    },
    "recognized": {
      "airports": [{"id": "AMS", "name": "Amsterdam", "available": true}],
      "destinations": [{"id": "d7b4bb39-123c-1234-b123-1234567i", "name": "Italy", "type": "COUNTRY", "available": true}],
      "duration": {"id": "2007", "name": "7 nights", "isDefault": true},
      "flexibility": {"id": "3", "name": "+- 3 days", "isDefault": true},
      "dates": [
        {"phrase": "10 October 2025", "iso": "2025-10-10T00:00:00"}
      ]
    },
    "language": {
      "code": "en",
      "confidence": 0.78
    }
  }
}
```

Values in the `timings` block are illustrative; actual measurements depend on your environment and configuration. When validation fails, `status` becomes `failed` and `metadata.validation.errors` explains the reason while still returning HTTP 200 (per the SRS requirement).

## Pipeline anatomy

The [`HolidaySearchPipeline`](backend/app/pipeline/pipeline.py) coordinates the deterministic stages described in the SRS:

1. **Language detection** (`pipeline/language.py`) – lightweight heuristics confirm that English is supported and emit a confidence score.
2. **Rule-based extraction** (`pipeline/extractor_rules.py`) – dictionary-driven entity detection maps airports, destinations, date phrases, durations, and flexibility references.
3. **Normalisation** (`pipeline/normalizer.py`) – converts extracted entities into canonical IDs, expands flexible date windows against available check-in dates, and applies configuration defaults for party/rooms.
4. **Validation** (`pipeline/validator.py`) – enforces availability, selection limits, date ranges, and required field combinations; failures are reported as `status="failed"` with HTTP 200, matching the SRS.

Each `/v1/parse` call measures the time spent in every stage, adds a total, and highlights threshold breaches relative to `PROCESSING_THRESHOLD_MS`. The CSV logger in [`backend/app/logging/csv_logger.py`](backend/app/logging/csv_logger.py) records the raw input, method metadata, timings, and structured output (or validation errors) for downstream benchmarking.

## Fixtures and validation rules

Fixture files in `fixtures/` contain the canonical data used during extraction and validation. They are loaded by [`FixtureRepository`](backend/app/fixtures/repository.py), which eagerly validates schema expectations so mistakes surface during startup:

- `airports.json` – available departure airports and availability flags.
- `destinations.json` – supported destinations with IDs and types.
- `dates.json` – chronological list of allowable check-in dates (format `DD-MM-YYYY`).
- `configuration_search.json` – business rules (default party size, duration catalog, flexibility options, multi-select limits, required field combinations, etc.).

Adjusting these files lets you experiment with new markets or validation constraints without editing Python code. The pipeline enforces that departure dates align with `dates.json` and that requests include a departure date plus either departure airports or destinations.

## Logging

CSV audit entries are appended to `CSV_PATH` on each parse request using the fixed columns:

```
Timestamp, Input, Language, Method, STT, ProcessingTime, Output, Status, ThresholdBreached
```

If total processing time exceeds `PROCESSING_THRESHOLD_MS`, the dedicated `ThresholdBreached` column records `true`; otherwise it records `false`. The `Output` column always captures a JSON object containing the pipeline `status`, the structured `data` payload, and the `validation` block emitted by the API. This guarantees validation error messages are preserved alongside the normalized data even when the overall status is `failed`.

## Testing and quality checks

```bash
pytest            # run unit tests covering fixtures, pipeline, and API endpoints
ruff check .      # linting based on the configured Ruff rules
```

The Makefile offers shortcuts (`make test`, `make lint`) if you prefer. Continuous integration should run both commands to preserve deterministic behaviour across fixtures, configuration, and API contracts.

## Further reading

- [docs/SRS_v003_011125.md](docs/SRS_v003_011125.md) – complete product requirements and validation rules.
- [docs/SDD_v001_041125.md](docs/SDD_v001_041125.md) – architectural decisions and suggested extensions.

These documents provide deeper guidance when extending the starter into hybrid or LLM-powered parsing approaches.
