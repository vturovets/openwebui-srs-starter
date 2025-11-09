# OpenWebUI SRS Starter

Prototype monorepo for the **NLP-Powered Holiday Request** project outlined in the
accompanying Software Requirements Specification (SRS) and Software Design
Description (SDD). It ships a deterministic FastAPI backend and a Svelte-based
reference frontend so teams can benchmark NLP strategies end-to-end. The backend
accepts natural-language holiday requests, derives structured parameters using a
fixture-backed pipeline, and records every transaction for benchmarking and UI
telemetry.

The implementation favours transparency over ML magic: language detection,
extraction, normalisation, validation, and logging are explicitly coded so
alternate approaches can be swapped in while retaining comparable output.

## Project structure

```
.
├── backend/
│   ├── app/                    # FastAPI application, pipeline stages, integrations
│   └── tests/                  # Pytest coverage for fixtures, pipeline, and API
├── docs/                       # SRS, SDD, and integration reference material
├── fixtures/                   # Airports, destinations, durations, and configuration JSON
├── frontend/                   # Svelte SPA that consumes the backend contract
├── Makefile                    # Convenience targets for linting and tests
└── pyproject.toml              # Backend dependency metadata
```

## Backend setup

### Prerequisites

- Python 3.10 or newer
- `pip` for installing dependencies
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
| Lint backend code | `make lint` *(wraps `ruff check backend`)* |
| Run backend tests | `make test` *(wraps `pytest`)* |

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
| `LLM_METHOD` | _(unset)_ | Optional identifier for the NLP technique under evaluation (e.g., `rules`, `llm`, `hybrid`). |
| `LLM_API_BASE` | _(unset)_ | Override the LLM provider base URL when using a proxy or self-hosted gateway. |
| `LLM_API_KEY` | _(unset)_ | Credential passed to the structured LLM client when `LLM_METHOD=llm` or `hybrid`. |
| `LLM_MODEL` | `gpt-3.5-turbo` | Model identifier requested from the LLM provider. |
| `LLM_TIMEOUT` | `30` | Client-side timeout (seconds) for outbound LLM requests. |
| `STT_ENGINE` | _(unset)_ | Speech-to-text engine label when voice capture is enabled (e.g., `deepgram`). |
| `DEEPGRAM_API_KEY` | _(unset)_ | API key for Deepgram when `STT_ENGINE=deepgram`. |
| `VOICE_ENABLED` | `false` | Toggle indicating whether voice input is active in the UI. |
| `VOICE_MAX_BYTES` | `10000000` | Maximum audio payload size accepted by `/v1/voice` in bytes. |
| `VOICE_ALLOWED_CONTENT_TYPES` | see code | Comma-separated list of MIME types accepted by `/v1/voice` (defaults cover WAV, MP3, OGG, WebM, and FLAC). |
| `FIXTURES_DIR` | `fixtures` | Directory containing the JSON fixture files. |
| `METHODS_CONFIG_PATH` | `config/methods.yaml` | YAML catalogue describing available parsing methods and hybrid strategies. |
| `PROCESSING_THRESHOLD_MS` | `1000` | Millisecond budget; responses note if total processing time exceeds this value. |

Create a `.env` file to override defaults, for example:

```
INTERACTION_MODE=direct-parse
ALLOWED_LANGS=en
CSV_PATH=data/log.csv
CSV_DELIMITER=;
# Enable the structured LLM path
LLM_METHOD=llm
LLM_API_KEY=sk-your-key
LLM_MODEL=gpt-4o
# Optional when routing through a proxy/self-hosted gateway
# LLM_API_BASE=https://your-proxy.example.com/v1
PROCESSING_THRESHOLD_MS=750
```

When deploying with Docker Compose, mirror the same environment variables in the
service definition so the backend receives the credentials at startup:

```yaml
services:
  backend:
    image: ghcr.io/openwebui/starter-backend:latest
    environment:
      - LLM_METHOD=llm
      - LLM_API_KEY=${LLM_API_KEY}
      - LLM_MODEL=${LLM_MODEL:-gpt-3.5-turbo}
      - LLM_API_BASE=${LLM_API_BASE:-https://api.openai.com/v1}
```

Bind-mount a `.env` file or rely on Compose variable substitution to keep
secrets out of version control.

### Method catalog

Structured extraction strategies are described in [`config/methods.yaml`](config/methods.yaml). The loader merges the `defaults` block with each enabled method, applies environment-variable substitutions (for example `${OPENAI_BASE}`), and resolves hybrid definitions into concrete stage sequences before caching the result in [`Settings`](backend/app/config.py). Each entry is surfaced through the `/v1/fixtures` endpoint so clients can list available options and defaults.

- **Rules/LLM entries** – declare provider metadata, tunable parameters, and optional `api_key_env` indirection to avoid storing secrets in the catalog.
- **Hybrid entries** – reference existing methods via `stages` and optionally specify a `fallback` that runs when upstream stages fail.

Update `METHODS_CONFIG_PATH` to point at an alternate YAML file if you need to swap in different evaluation strategies per environment.

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
for the full endpoint contracts, and
[`docs/openwebui_configuration.md`](docs/openwebui_configuration.md) for
step-by-step instructions on wiring the custom Open-WebUI connector and
renderer.

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
   requested/used method, and any validation errors so the API can report
   detailed diagnostics.

The dialog experience is layered on top via
[`DialogOrchestrator`](backend/app/pipeline/dialog.py), which inspects
validation failures and returns clarification prompts or session context. CSV
instrumentation is handled by [`CSVLogger`](backend/app/logging/csv_logger.py),
which writes a stable schema defined in
[`backend/app/dependencies.py`](backend/app/dependencies.py).

### Fixtures

Fixture JSON files in [`fixtures/`](fixtures) and
[`backend/app/fixtures`](backend/app/fixtures) act as the canonical source of
truth for airports, destinations, durations, and configuration defaults. The
[`FixtureRepository`](backend/app/fixtures/repository.py) exposes typed access to
these resources so pipeline stages can remain deterministic.

### Voice capture

When `VOICE_ENABLED=true`, the API exposes `/v1/voice` and wires in an optional
speech-to-text client via `get_stt_client`. The default implementation is
[`DeepgramSpeechToTextClient`](backend/app/integrations/stt.py), which streams
audio to Deepgram’s REST API and returns word-level timings for the UI.

## Frontend quick start

The `frontend/` directory contains a Vite + Svelte single-page application that
consumes the backend contract. To work on the UI:

```bash
cd frontend
npm install
npm run dev -- --open
```

Additional scripts:

| Task | Command |
| --- | --- |
| Run component tests | `npm test` *(Vitest)* |
| Run Playwright E2E tests | `npm run test:ui` |
| Build production bundle | `npm run build` |

Vitest is configured with JSDOM in `vitest.setup.ts`, and Playwright suites live
under [`frontend/tests`](frontend/tests).

## API endpoints

| Method & Path | Description |
| --- | --- |
| `GET /health` | Returns `{ "status": "ok" }` plus the active interaction mode for readiness checks. |
| `POST /v1/parse` | Parses a natural-language utterance and responds with structured holiday parameters, validation metadata, and timing metrics. |
| `POST /v1/dialog` | Maintains clarification sessions, returning prompts and accumulating transcript context when `INTERACTION_MODE=dialog`. |
| `GET /v1/fixtures` | Exposes airports, destinations, available check-in dates, and configuration defaults so clients can pre-populate UI controls. |
| `POST /v1/voice` | Streams uploaded audio to the configured STT engine, returns the transcript with timing data, and forwards the utterance into the holiday search pipeline. |

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
