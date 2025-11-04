# OpenWebUI Integration Notes

This note captures the backend contracts and deployment expectations needed by UI engineers integrating OpenWebUI with the SRS starter API.

## Base URL & Deployment Checklist

1. **Start the FastAPI service** with uvicorn and bind to all interfaces:
   ```bash
   uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
   ```
2. **Expose the service publicly**. Any HTTPS-capable tunnel or reverse proxy works. For example, with ngrok:
   ```bash
   ngrok http 8000
   ```
   Use the HTTPS forwarding URL reported by ngrok (e.g. `https://abcd1234.ngrok.app`) as the API base in OpenWebUI.
3. **Configure OpenWebUI** to call the backend at `https://<public-host>/`. The REST surface lives under:
   - `GET https://<public-host>/health`
   - `POST https://<public-host>/v1/parse`
   - `GET https://<public-host>/v1/fixtures`
   - `POST https://<public-host>/v1/voice`

### Runtime environment variables

Set these before starting uvicorn (either in the shell or a `.env` file) so the backend metadata matches the UI behaviour:

| Variable | Purpose |
| --- | --- |
| `INTERACTION_MODE` | Default interaction mode reported to the UI and `/health`. |
| `LLM_METHOD` | Method identifier echoed in `/v1/parse` metadata for UI instrumentation. |
| `VOICE_ENABLED` | Toggles voice support; `/v1/voice` reports `noop` when `false`. |
| `STT_ENGINE` | Speech-to-text engine label surfaced by `/v1/voice`. |
| `PROCESSING_THRESHOLD_MS` | Millisecond budget compared against total pipeline time; flagged in `/v1/parse` metadata. |
| `CSV_PATH`, `FIXTURES_DIR` | Optional paths if running outside the repository defaults. |

## REST Contracts

### `GET /health`
- **Request body:** none.
- **Response:**
  ```json
  {
    "status": "ok",
    "interaction_mode": "<current interaction mode>"
  }
  ```

### `POST /v1/parse`
- **Request body:**
  ```json
  {
    "text": "<utterance>",
    "mode": "<optional override>",
    "method": "<optional method id>"
  }
  ```
  `text` is required; `mode` and `method` fall back to `INTERACTION_MODE` and `LLM_METHOD` when omitted.
- **Response envelope:**
  ```json
  {
    "status": "success | failed | error",
    "data": { ... },
    "metadata": {
      "mode": "<resolved mode>",
      "method": "<resolved method>",
      "timings": {
        "languageMs": <float>,
        "extractionMs": <float>,
        "normalizationMs": <float>,
        "validationMs": <float>,
        "totalMs": <float>,
        "thresholdBreached": <bool>
      },
      "validation": {
        "status": "passed | failed | error",
        "errors": [ { "message": "<detail>" }, ... ]
      },
      "recognized": {
        "airports": [ { ...fixture airport... }, ... ],
        "destinations": [ { ...fixture destination... }, ... ],
        "duration": { ...duration option... },
        "flexibility": { ...flex option... },
        "dates": [ { "phrase": "<matched phrase>", "iso": "<ISO timestamp>" }, ... ]
      },
      "language": {
        "code": "<ISO code>",
        "confidence": <float>
      }
    }
  }
  ```
  - When validation fails, HTTP status remains 200 and `status` becomes `"failed"`; `data` contains the normalised payload.
  - When a bad request occurs (e.g. invalid input), the service returns HTTP 400 with `status: "error"` and `data.error` describing the issue.
  - `data` is the normalised query payload with keys: `language`, `from`, `to`, `departureDate`, `durationId`, `party`, `rooms`.

### `GET /v1/fixtures`
- **Request body:** none.
- **Response:**
  ```json
  {
    "airports": [ { ...fixture airport... }, ... ],
    "destinations": [ { ...fixture destination... }, ... ],
    "dates": [ "DD-MM-YYYY", ... ],
    "configuration": {
      "defaults": { ... },
      "roomsConfiguration": { ... },
      "durationOptions": [ { ... }, ... ],
      "flexibility": [ { ... }, ... ]
    }
  }
  ```
  The payload mirrors the JSON fixtures shipped in the repository and should be used to populate dropdowns or autocomplete sources.

### `POST /v1/voice`
- **Request body:** none (placeholder endpoint).
- **Response:**
  ```json
  {
    "status": "success | noop",
    "voice_enabled": <bool>,
    "engine": "<speech-to-text engine or null>",
    "metadata": {
      "timings": { "totalMs": <float> },
      "mode": "<interaction mode>"
    }
  }
  ```
  Returns `status: "noop"` and `engine: null` when `VOICE_ENABLED` is false.
