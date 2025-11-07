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
| `llm_method` | `LLM_METHOD` | `None` | Preferred extraction method: `rules`, `llm`, or `hybrid`. Unknown values fall back to `rules`. |
| `stt_engine` | `STT_ENGINE` | `None` | Speech-to-text provider identifier. Currently `deepgram` is supported. |
| `deepgram_api_key` | `DEEPGRAM_API_KEY` | `None` | API key required when `STT_ENGINE=deepgram`. |
| `voice_enabled` | `VOICE_ENABLED` | `False` | Enables the `/v1/voice` endpoint and STT integration when true. |
| `voice_max_bytes` | `VOICE_MAX_BYTES` | `10000000` | Maximum upload size (in bytes) accepted by the voice endpoint. |
| `voice_allowed_content_types` | `VOICE_ALLOWED_CONTENT_TYPES` | `audio/wav`, `audio/x-wav`, `audio/mpeg`, `audio/mp3`, `audio/ogg`, `audio/webm`, `video/webm`, `audio/flac` | Whitelisted MIME types for audio uploads. |
| `fixtures_dir` | `FIXTURES_DIR` | `fixtures` | Directory containing JSON fixtures used by the pipeline. |
| `processing_threshold_ms` | `PROCESSING_THRESHOLD_MS` | `1000` | SLA threshold used to flag slow pipeline executions in metadata. |

Numeric and list-type values accept either JSON-style arrays or comma-separated strings.
Helper validators normalise the data, so `ALLOWED_LANGS=en,fr` and
`VOICE_ALLOWED_CONTENT_TYPES=audio/wav,audio/webm` and `VOICE_ALLOWED_CONTENT_TYPES=audio/webm,video/webm` are both valid. 【F:backend/app/config.py†L104-L153】

Calling `Settings.ensure_directories()` ensures both the CSV directory and fixtures
directory exist before serving traffic. 【F:backend/app/config.py†L146-L158】

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
