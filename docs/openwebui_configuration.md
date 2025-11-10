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

Numeric and list-type values accept either JSON-style arrays or comma-separated strings.
Helper validators normalise the data, so `ALLOWED_LANGS=en,fr` and
`VOICE_ALLOWED_CONTENT_TYPES=audio/wav,audio/webm` and `VOICE_ALLOWED_CONTENT_TYPES=audio/webm,video/webm` are both valid. 【F:backend/app/config.py†L104-L153】

`CSV_DELIMITER` accepts a single printable character such as `;` or `|`, allowing
locales that prefer semicolon-delimited audit trails to interoperate without
post-processing. 【F:backend/app/config.py†L37-L57】【F:backend/app/logging/csv_logger.py†L22-L51】

Calling `Settings.ensure_directories()` ensures both the CSV directory and fixtures
directory exist before serving traffic. 【F:backend/app/config.py†L146-L158】

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

1. Set `VOICE_ENABLED=true` to allow audio uploads. 【F:backend/app/config.py†L66-L99】
2. Choose an STT engine by setting `STT_ENGINE`.
   - `deepgram` streams audio to the hosted Deepgram API and requires `DEEPGRAM_API_KEY`.
   - `faster-whisper` (or `whisper`) runs the open-source Whisper model locally with the
     help of the optional `faster-whisper` Python package. Additional tunables such as
     `WHISPER_MODEL_SIZE`, `WHISPER_COMPUTE_TYPE`, and `WHISPER_DOWNLOAD_ROOT` allow the
     deployment to control model quality, precision, and cache location.
3. Provide the engine-specific credentials (only Deepgram currently requires an API key).
   The dependency layer will raise an error at startup if mandatory settings are missing.
   【F:backend/app/dependencies.py†L69-L119】

Install the Whisper dependency via `pip install .[stt]` when enabling the local engine.

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
