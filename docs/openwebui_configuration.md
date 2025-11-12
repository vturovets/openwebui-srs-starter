# OpenWebUI Configuration Guide

This guide explains how to configure the OpenWebUI starter so that the backend services
and extension tooling behave predictably across environments.

## Environment variables
Runtime configuration is centralised in `backend/app/config.py` using Pydantic settings.
Each field can be provided via `.env` file or environment variable using the alias shown
below. 【F:backend/app/config.py†L18-L158】

| Setting | Env var | Default | Description |
| --- | --- | --- | --- |
| `interaction_mode` | `INTERACTION_MODE` | `"direct-parse"` | Controls whether requests default to single-turn parsing (`direct-parse`) or dialog-driven clarification (`dialog`). |
| `allowed_langs` | `ALLOWED_LANGS` | `["en"]` | Comma-separated list of ISO language codes the language detector should accept. |
| `csv_path` | `CSV_PATH` | `data/log.csv` | Location of the CSV audit log written by the API. Directories are created automatically. |
| `csv_delimiter` | `CSV_DELIMITER` | `","` | Delimiter character applied to rows written to the audit log. |
| `llm_method` | `LLM_METHOD` | `None` | Preferred extraction method: `rules`, `llm`, or `hybrid`. Unknown values fall back to `rules`. |
| `llm_api_base` | `LLM_API_BASE` | `None` | Base URL for the LLM provider. Defaults to `https://api.openai.com/v1` when unset. |
| `llm_api_key` | `LLM_API_KEY` | `None` | Credential supplied to the structured LLM client when the LLM path is active. |
| `llm_model` | `LLM_MODEL` | `"gpt-3.5-turbo"` | Model identifier requested from the provider. |
| `llm_timeout` | `LLM_TIMEOUT` | `30.0` | HTTP client timeout (seconds) enforced for LLM calls. |
| `stt_engine` | `STT_ENGINE` | `None` | Speech-to-text provider identifier. Currently `deepgram` is supported. |
| `deepgram_api_key` | `DEEPGRAM_API_KEY` | `None` | API key required when `STT_ENGINE=deepgram`. |
| `voice_enabled` | `VOICE_ENABLED` | `False` | Enables the `/v1/voice` endpoint and STT integration when true. |
| `voice_max_bytes` | `VOICE_MAX_BYTES` | `10000000` | Maximum upload size (in bytes) accepted by the voice endpoint. |
| `voice_allowed_content_types` | `VOICE_ALLOWED_CONTENT_TYPES` | `audio/wav`, `audio/x-wav`, `audio/mpeg`, `audio/mp3`, `audio/ogg`, `audio/webm`, `video/webm`, `audio/flac` | Whitelisted MIME types for audio uploads. |
| `fixtures_dir` | `FIXTURES_DIR` | `fixtures` | Directory containing JSON fixtures used by the pipeline. |
| `processing_threshold_ms` | `PROCESSING_THRESHOLD_MS` | `1000` | SLA threshold used to flag slow pipeline executions in metadata. |
| `show_failed_only` | `SHOW_FAILED_ONLY` | `True` | Restricts the import dashboard to failed rows unless toggled off. |
| `import_max_concurrency` | `IMPORT_MAX_CONCURRENCY` | `4` | Upper bound on concurrent pipeline executions while processing CSV imports. |
| `import_queue_limit` | `IMPORT_QUEUE_LIMIT` | `32` | Maximum number of active import jobs permitted before new submissions are rejected. |
| `import_batch_size` | `IMPORT_BATCH_SIZE` | `64` | Maximum number of rows accepted per import job to avoid runaway memory use. |
| `import_max_pending_jobs` | `IMPORT_MAX_PENDING_JOBS` | `None` | Optional cap on queued-but-not-started jobs; unset defaults to a rolling window. |

Numeric and list-type values accept either JSON-style arrays or comma-separated strings.
Helper validators normalise the data, so `ALLOWED_LANGS=en,fr` and
`VOICE_ALLOWED_CONTENT_TYPES=audio/wav,audio/webm` and `VOICE_ALLOWED_CONTENT_TYPES=audio/webm,video/webm` are both valid. 【F:backend/app/config.py†L104-L153】

`CSV_DELIMITER` accepts a single printable character such as `;` or `|`, allowing
locales that prefer semicolon-delimited audit trails to interoperate without
post-processing. 【F:backend/app/config.py†L37-L57】【F:backend/app/logging/csv_logger.py†L22-L51】

Calling `Settings.ensure_directories()` ensures both the CSV directory and fixtures
directory exist before serving traffic. 【F:backend/app/config.py†L146-L158】

## Import workflow and guardrails

The import dashboard allows analysts to upload CSV extracts of historical runs so the
pipeline can reprocess them in the background and surface mismatches directly in the UI.
Requests are enqueued by `ImportManager`, which enforces concurrency, queue, and batch
limits derived from the environment variables above. 【F:backend/app/imports/manager.py†L70-L119】

1. `/v1/imports` accepts a CSV file, materialises it into dictionaries, and validates that
   at least one row is present and that the batch size is within the configured limit.
   【F:backend/app/api/routes.py†L188-L216】
2. A background task is scheduled per import job. The manager uses a shared
   `ThreadPoolExecutor` and semaphore to ensure no more than
   `IMPORT_MAX_CONCURRENCY` rows are processed concurrently. 【F:backend/app/imports/manager.py†L87-L119】
3. Clients poll `/v1/imports/{jobId}` to retrieve live status updates until the job enters a
   terminal state (`completed`, `failed`, or `cancelled`). Poll responses include running
   counts of successes, mismatches, errors, and timing breakdowns. 【F:backend/app/api/routes.py†L218-L263】
4. Completed job summaries remain cached for an hour (configurable via the manager
   constructor) so operators can refresh dashboards without replaying work.

Environment guardrails are enforced early: exceeding the queue limit produces an HTTP
429, and oversized uploads return HTTP 400 with a descriptive message. Operators should
monitor these responses when adjusting throughput in staging. 【F:backend/app/imports/manager.py†L120-L185】

### Scaling guardrails for high-volume imports

For bulk backfills (1,000+ rows per session) consider the following adjustments:

- Raise `IMPORT_P95_SAMPLE_SIZE` to at least match the anticipated batch size so the
  percentile calculation reflects the larger dataset. For example, a 1,500-row import
  should set `IMPORT_P95_SAMPLE_SIZE=1500` to avoid premature reporting.
- Increase `IMPORT_P95_THRESHOLD_MS` gradually (e.g., 1,500–2,000 ms) when the pipeline
  includes LLM calls or external APIs that introduce additional latency. This prevents the
  dashboard from flagging every row as an anomaly while you profile performance.
- Scale `IMPORT_MAX_CONCURRENCY` based on available CPU cores. Doubling the default to 8
  roughly halves total wall-clock time for CPU-bound workloads, but ensure the FastAPI
  worker pool and database (if any) can sustain the parallelism. `IMPORT_QUEUE_LIMIT`
  should also be increased proportionally so the UI does not reject new jobs while
  previous batches complete.
- When multiple teams share the environment, set `IMPORT_MAX_PENDING_JOBS` to a finite
  value (for example 6) to prevent unbounded queue growth while still allowing short
  bursts of submissions.

Always stage these changes first and observe CPU, memory, and downstream service error
rates before rolling to production. The manager surfaces per-stage timings and
`usageFootprint` metrics in its status payloads, providing immediate feedback on whether
the new guardrails balance throughput against resource usage. 【F:backend/app/imports/manager.py†L37-L68】【F:backend/app/api/routes.py†L231-L263】

### Deployment and lifecycle notes

Deployments that adopt FastAPI's lifespan context must ensure the import manager and its
thread pool are created during application startup and torn down during shutdown to avoid
orphaned workers. The current starter still wires dependencies through `@app.on_event`
hooks, so migrating to lifespan requires moving the cache-clearing logic and any eager
calls to `get_import_manager()` into the lifespan block. This keeps the background import
infrastructure aligned with the app lifecycle and avoids stale settings after reloads.
【F:backend/app/main.py†L16-L44】【F:backend/app/dependencies.py†L70-L111】

## Enabling the LLM extraction path

Set `LLM_METHOD=llm` (or `hybrid`) to activate the structured LLM client. Provide
the supporting credentials so `HolidaySearchLLMClient` can be instantiated by the
dependency layer. 【F:backend/app/config.py†L30-L90】【F:backend/app/dependencies.py†L64-L88】

Populate a `.env` file with the following keys to run the backend locally:

```
LLM_METHOD=llm
LLM_API_KEY=sk-your-key
LLM_MODEL=gpt-4o
# Optional when routing through a proxy/self-hosted gateway
# LLM_API_BASE=https://your-proxy.example.com/v1
```

When deploying via Docker Compose, mirror the same settings in the service
definition so the container receives the credentials on startup:

```yaml
services:
  backend:
    environment:
      - LLM_METHOD=llm
      - LLM_API_KEY=${LLM_API_KEY}
      - LLM_MODEL=${LLM_MODEL:-gpt-3.5-turbo}
      - LLM_API_BASE=${LLM_API_BASE:-https://api.openai.com/v1}
```

Compose can read the values from a shared `.env` file or secrets manager, keeping
keys out of source control.

## Voice and speech-to-text setup
Voice features require multiple settings to be in place:

1. Set `VOICE_ENABLED=true` to allow audio uploads. 【F:backend/app/config.py†L66-L87】
2. Choose an STT engine by setting `STT_ENGINE`. At present only `deepgram` is wired in.
3. Provide the engine-specific credentials (`DEEPGRAM_API_KEY` for Deepgram). The
   dependency layer will raise an error at startup if the key is missing when Deepgram is
   selected. 【F:backend/app/dependencies.py†L69-L102】

The API validates incoming audio against the configured MIME-type allowlist and payload
size limit, returning HTTP 415/413 when requests fall outside those bounds. Adjust
`VOICE_ALLOWED_CONTENT_TYPES` or `VOICE_MAX_BYTES` to align with client capabilities.
【F:backend/app/api/routes.py†L653-L705】

## Holiday search tool defaults
The OpenWebUI extension exposes the backend through the `HolidaySearchTool` wrapper.
Its configuration class defines the tunable options that the UI can surface to end users.
【F:backend/app/integrations/openwebui_extension.py†L44-L104】

| Option | Default | Purpose |
| --- | --- | --- |
| `base_url` | *(required)* | Points the connector at the FastAPI deployment. |
| `interaction_mode` | `"direct-parse"` | Mirrors the backend default; controls whether `/v1/dialog` is used. |
| `llm_method` | `None` | Overrides the extraction strategy sent with parse requests. |
| `voice_enabled` | `False` | Advertises whether the UI should expose audio capture controls. |
| `timeout` | `10.0` | Request timeout (seconds) enforced by the connector. |

Runtime code may update these options via `HolidaySearchTool.set_options`, which accepts
keyword arguments matching the fields above. 【F:backend/app/integrations/openwebui_extension.py†L105-L137】

To pre-populate UI selectors, call `HolidaySearchTool.fixtures()`; the helper augments
the `/v1/fixtures` payload with the current interaction mode, method preference, and
voice flag so that the frontend can synchronise its controls. 【F:backend/app/integrations/openwebui_extension.py†L165-L193】
