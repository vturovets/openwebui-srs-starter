# UI Integration Contracts

This document summarises the HTTP contracts that the OpenWebUI frontend and third-party
clients rely on when interacting with the FastAPI backend. All routes are namespaced
under the `/v1` prefix and return JSON unless otherwise noted.

## `/v1/fixtures` (GET)
Returns static data that lets the UI populate dropdowns and default selections without
hard-coding them client-side. 【F:backend/app/api/routes.py†L585-L615】

**Response shape**
- `airports`: List of airport metadata objects as defined in the fixtures repository.
- `destinations`: List of destination metadata objects.
- `dates`: Array of ISO-formatted check-in dates.
- `configuration`: Object containing `defaults`, `roomsConfiguration`,
  `durationOptions`, and `flexibility` pulled from the search configuration JSON. 【F:backend/app/api/routes.py†L597-L612】

## `/v1/parse` (POST)
Runs a single-shot parse of a user utterance through the holiday-search pipeline.
【F:backend/app/api/routes.py†L423-L481】

**Request payload**
- `text` *(string, required)*: The utterance to process.
- `mode` *(string, optional)*: Overrides the server-side interaction mode for this call.
- `method` *(string, optional)*: Overrides the extraction strategy (`rules`, `llm`, or
  `hybrid`). 【F:backend/app/api/routes.py†L30-L52】

**Successful response**
- `status`: `success` when validation passes, `failed` when validation fails but the
  pipeline completed, or `error` when the pipeline raised an exception.
- `data`: Normalised holiday-search payload when successful; contains an `error` object
  if `status` is `error`.
- `metadata`: Includes the resolved `mode`, the actual and requested methods,
  per-stage timings, validation output, transcript echo, recognised entities, and lists
  of `missingFields` / `invalidFields`. 【F:backend/app/api/routes.py†L327-L420】

If `status` is `error`, the endpoint responds with HTTP 400 and the error message in the
response body. 【F:backend/app/api/routes.py†L455-L481】

## `/v1/dialog` (POST)
Supports interactive clarification sessions that accumulate state on the server.
【F:backend/app/api/routes.py†L483-L584】

**Request payload**
- `text` *(string, required)*: The current user utterance.
- `sessionId` *(string, optional)*: Existing dialog session identifier. When omitted the
  backend creates a new session and returns the generated ID.
- `mode` *(string, optional)*: `dialog` enables multi-turn behaviour; any other value
  forces single-turn parsing.
- `method` *(string, optional)*: Preferred extraction strategy. 【F:backend/app/api/routes.py†L54-L95】

**Response payload**
- `status`: `success`, `clarification` (when more information is needed), `failed`, or
  `error` propagated from the pipeline.
- `sessionId`: Echoes the active session when `dialog` mode is engaged.
- `data`: Normalised payload for the accumulated conversation when available.
- `prompt`: Optional clarification payload with `parameter`, `message`, and `reason` when
  the UI must solicit more input. 【F:backend/app/api/routes.py†L96-L120】【F:backend/app/api/routes.py†L543-L584】
- `metadata`: Contains timings (with threshold breach flags), resolved interaction mode,
  recognised entities, missing/invalid field lists, session transcript, and the raw
  pipeline status. 【F:backend/app/api/routes.py†L501-L542】

When the orchestrator determines the dialog cannot proceed, it returns HTTP 400 with the
failure reason in the body. 【F:backend/app/api/routes.py†L535-L584】

## `/v1/voice` (POST)
Accepts audio uploads, transcribes them with the configured speech-to-text (STT) engine,
and feeds the transcript through the same pipeline as `/v1/parse`. 【F:backend/app/api/routes.py†L617-L770】

**Request requirements**
- Multipart/form-data upload with a single `file` field.
- Only MIME types listed in configuration (`VOICE_ALLOWED_CONTENT_TYPES`) are accepted.
- Payloads larger than `voice_max_bytes` are rejected with HTTP 413. 【F:backend/app/api/routes.py†L653-L705】

**Response payload**
- `status`: `noop` when voice is disabled, or the pipeline status when enabled.
- `voice_enabled`: Boolean indicating whether STT processing was performed.
- `engine`: Identifier of the STT engine that produced the transcript. When
  Deepgram credentials are absent the dependency layer swaps in the
  `faster-whisper` fallback, and the field reflects that choice.
- `transcript`: Trimmed text result from the STT provider.
- `words`: Optional word-level timing entries when supplied by the provider.
- `data` and `metadata`: Same structure as `/v1/parse`, with additional `sttMs` and
  `pipelineTotalMs` timing metrics. 【F:backend/app/api/routes.py†L707-L770】

**Error handling**
- HTTP 500 if voice is enabled but no STT provider is configured.
- HTTP 415 for unsupported content types.
- HTTP 413 when the payload exceeds the configured size limit.
- HTTP 422 when no speech is detected after transcription.
- HTTP 400 if the pipeline returns an error status. 【F:backend/app/api/routes.py†L629-L769】
