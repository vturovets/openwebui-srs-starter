# Open-WebUI Holiday Search Tool Configuration

This document explains how to register the custom Holiday Search connector and
frontend widget inside a fork of [`open-webui/open-webui`](https://github.com/open-webui/open-webui).
The connector proxies Open-WebUI tool invocations to the FastAPI service shipped
with this repository.

## Environment variables

Expose the following variables when starting the Open-WebUI backend:

| Variable | Purpose |
| --- | --- |
| `HOLIDAY_TOOL_BASE_URL` | Base URL for the FastAPI deployment (e.g. `https://example.ngrok.app`). |
| `HOLIDAY_TOOL_MODE` | Default interaction mode reported to `/v1/parse` when the UI does not specify one. |
| `HOLIDAY_TOOL_METHOD` | Optional method tag included in `/v1/parse` requests to support benchmarking runs. |

When using Docker Compose, append the values to the `webui` service:

```yaml
services:
  webui:
    environment:
      - HOLIDAY_TOOL_BASE_URL=https://example.ngrok.app
      - HOLIDAY_TOOL_MODE=direct-parse
      - HOLIDAY_TOOL_METHOD=rules
```

## Registering the tool workflow

Add the connector definition to `backend/apps/web/models/tools.py` inside the
Open-WebUI repository:

```python
from backend.integrations.holiday_search import HolidaySearchConnector


HOLIDAY_SEARCH_TOOL = ToolDefinition(
    name="holiday-search",
    description="Proxy holiday request parsing to the SRS FastAPI backend",
    invoke=lambda payload: HolidaySearchConnector(
        base_url=settings.get("HOLIDAY_TOOL_BASE_URL"),
        default_mode=settings.get("HOLIDAY_TOOL_MODE", "direct-parse"),
        default_method=settings.get("HOLIDAY_TOOL_METHOD"),
    ).parse(payload["text"], mode=payload.get("mode"), method=payload.get("method")),
)
```

Finally, register `HOLIDAY_SEARCH_TOOL` in the tool catalogue so that it appears
in the workflow composer or default workspace template.

## Frontend output renderer

Copy [`docs/openwebui_tool_output.tsx`](openwebui_tool_output.tsx) into the
Open-WebUI frontend (for example under `web/src/components/tools/`). Wire the
component into the tool output router so that holiday search results render the
structured `data` and `metadata` payloads, including validation errors when the
pipeline reports `status="failed"`.

## Running benchmark sessions

Set `HOLIDAY_TOOL_METHOD` to the identifier representing the pipeline variant
under test (e.g. `rules`, `llm`, `hybrid`). The connector forwards the value to
the FastAPI backend, which records it in CSV logs and surfaces it in response
metadata for the frontend.
