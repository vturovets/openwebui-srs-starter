"""HTTP client for Google Gemini structured extraction.

The client relies on ``Settings`` values sourced from the existing environment
variables ``LLM_API_KEY``, ``LLM_MODEL`` and ``LLM_API_BASE`` (optional) to
authenticate against the Gemini API without additional dependencies.
"""

from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping, MutableMapping, Sequence

import httpx

from ..config import Settings
from ..fixtures.repository import FixtureRepository
from ..pipeline.configuration import SearchConfiguration


DEFAULT_API_BASE = "https://generativelanguage.googleapis.com"
CONFIGURATION_FILENAME = "configuration_search.json"
SYSTEM_INSTRUCTION_FILENAME = "gemini_system_instructions.json"
GENERATION_CONFIG_FILENAME = "gemini_generation_config.json"


def _load_configuration(fixtures_dir: Path) -> SearchConfiguration:
    config_path = fixtures_dir / CONFIGURATION_FILENAME
    if not config_path.is_file():
        raise FileNotFoundError(
            f"Search configuration file '{CONFIGURATION_FILENAME}' not found in '{fixtures_dir}'"
        )
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:  # pragma: no cover - filesystem errors are handled elsewhere
        raise FileNotFoundError(f"Unable to read search configuration: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("Search configuration fixture must be a JSON object")
    return SearchConfiguration.from_fixture_payload(payload)


def _load_json_object(fixtures_dir: Path, filename: str, payload_key: str) -> MutableMapping[str, Any]:
    path = fixtures_dir / filename
    if not path.is_file():
        raise FileNotFoundError(f"Fixture '{filename}' not found in '{fixtures_dir}'")

    try:
        contents = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON content in fixture '{filename}'") from exc
    except OSError as exc:  # pragma: no cover - filesystem errors are handled elsewhere
        raise FileNotFoundError(f"Unable to read fixture '{filename}': {exc}") from exc

    try:
        payload = contents[payload_key]
    except KeyError as exc:
        raise ValueError(f"Fixture '{filename}' missing key '{payload_key}'") from exc

    if not isinstance(payload, Mapping):
        raise ValueError(f"Fixture '{filename}.{payload_key}' must be a JSON object")

    return dict(payload)


class GeminiStructuredLLMClient:
    """Structured LLM client for Google Gemini."""

    def __init__(
        self,
        settings: Settings,
        *,
        fixtures_dir: str | Path | None = None,
        http_client: httpx.Client | None = None,
        show_curl: bool = False,
    ) -> None:
        fixtures_path = Path(fixtures_dir or settings.fixtures_dir)
        fixtures = FixtureRepository(fixtures_path)
        configuration = _load_configuration(fixtures_path)

        self._metadata = {
            "airports": fixtures.list_airports(),
            "destinations": fixtures.list_destinations(),
            "durations": configuration.durations,
            "flexibility": {
                "allowed": configuration.flexibility_allowed,
                "options": configuration.flex_options,
            },
        }

        self._system_instruction = _load_json_object(
            fixtures_path, SYSTEM_INSTRUCTION_FILENAME, "system_instruction"
        )
        self._generation_config = _load_json_object(
            fixtures_path, GENERATION_CONFIG_FILENAME, "generationConfig"
        )

        api_base = (settings.llm_api_base or DEFAULT_API_BASE).rstrip("/")
        endpoint_path = f"models/{settings.llm_model}:generateContent"

        self._model = settings.llm_model
        self._api_key = settings.llm_api_key
        self._endpoint = endpoint_path
        self._show_curl = show_curl
        self._last_latency_ms: float | None = None

        self._client = http_client or httpx.Client(base_url=api_base, timeout=settings.llm_timeout)
        self._client_owner = http_client is None

    def close(self) -> None:
        if self._client_owner:
            self._client.close()

    def __del__(self) -> None:  # pragma: no cover - defensive cleanup
        self.close()

    def _build_generation_config(self) -> MutableMapping[str, Any]:
        return dict(self._generation_config)

    def _build_request_payload(self, query: str) -> MutableMapping[str, Any]:
        payload: MutableMapping[str, Any] = {
            "system_instruction": self._system_instruction,
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": query},
                        {"text": json.dumps(self._metadata, ensure_ascii=False)},
                    ],
                }
            ],
            "generation_config": self._build_generation_config(),
        }
        return payload

    def _extract_structured_payload(self, payload: Mapping[str, Any]) -> MutableMapping[str, Any]:
        try:
            candidates = payload["candidates"]
        except KeyError as exc:
            raise ValueError("Gemini provider response is missing 'candidates'") from exc

        if not isinstance(candidates, Sequence) or not candidates:
            raise ValueError("Gemini provider response did not include any candidates")

        first_candidate = candidates[0]
        if not isinstance(first_candidate, Mapping):
            raise ValueError("Gemini provider returned malformed candidate data")

        content = first_candidate.get("content")
        if not isinstance(content, Mapping):
            raise ValueError("Gemini provider returned malformed content payload")

        parts = content.get("parts")
        if not isinstance(parts, Sequence) or not parts:
            raise ValueError("Gemini provider content did not include any parts")

        first_part = parts[0]
        if not isinstance(first_part, Mapping):
            raise ValueError("Gemini provider returned malformed part payload")

        if "json" in first_part:
            structured_payload = first_part["json"]
        elif "text" in first_part:
            text_payload = first_part["text"]
            if not isinstance(text_payload, str) or not text_payload.strip():
                raise ValueError("Gemini provider returned empty text content")
            try:
                structured_payload = json.loads(text_payload)
            except json.JSONDecodeError as exc:
                raise ValueError("Gemini provider returned non-JSON text content") from exc
        else:
            raise ValueError("Gemini provider response did not include structured content")

        if not isinstance(structured_payload, Mapping):
            raise ValueError("Gemini provider content must be a JSON object")

        return dict(structured_payload)

    def _format_curl_command(
        self,
        request_payload: Mapping[str, Any],
        params: Mapping[str, str] | None,
    ) -> str:
        url = f"{self._client.base_url}{self._endpoint}"
        if params:
            query_string = str(httpx.QueryParams(params))
            if query_string:
                url = f"{url}?{query_string}"

        payload_json = json.dumps(request_payload, ensure_ascii=False)
        escaped_payload = payload_json.replace("'", "'\"'\"'")

        return (
            "curl -X POST "
            "-H \"Content-Type: application/json\" "
            f"-d '{escaped_payload}' "
            f'"{url}"'
        )

    def build_curl_command(self, query: str) -> str:
        """Return a cURL command that mirrors the Gemini request for ``query``."""

        request_payload = self._build_request_payload(query)
        params = {"key": self._api_key} if self._api_key else None
        return self._format_curl_command(request_payload, params)

    def _merge_metadata(
        self,
        payload: MutableMapping[str, Any],
        response_body: Mapping[str, Any],
        response: httpx.Response,
    ) -> None:
        metadata: MutableMapping[str, Any] = {}
        existing = payload.get("_metadata")
        if isinstance(existing, Mapping):
            metadata.update(existing)

        candidate_metadata = None
        candidates = response_body.get("candidates")
        if isinstance(candidates, Sequence) and candidates:
            first_candidate = candidates[0]
            if isinstance(first_candidate, Mapping):
                candidate_metadata = first_candidate.get("metadata")
                finish_reason = first_candidate.get("finishReason")
                if finish_reason and "finishReason" not in metadata:
                    metadata["finishReason"] = finish_reason
        if isinstance(candidate_metadata, Mapping):
            metadata.update(candidate_metadata)

        response_metadata = response_body.get("metadata")
        if isinstance(response_metadata, Mapping):
            metadata.update(response_metadata)

        usage_metadata = response_body.get("usageMetadata")
        if isinstance(usage_metadata, Mapping):
            metadata.setdefault("usageMetadata", usage_metadata)

        model_version = response_body.get("modelVersion")
        if model_version:
            metadata.setdefault("modelVersion", model_version)

        header_mappings = {
            "x-request-id": "requestId",
            "x-response-id": "responseId",
            "x-trace-id": "traceId"
        }
        for header, key in header_mappings.items():
            value = response.headers.get(header)
            if value and key not in metadata:
                metadata[key] = value

        metadata.setdefault("provider", "google-gemini")
        metadata.setdefault("model", self._model)

        payload["_metadata"] = metadata

    def __call__(self, text: str) -> Mapping[str, Any]:
        request_payload = self._build_request_payload(text)
        params = {"key": self._api_key} if self._api_key else None
        curl_command = self._format_curl_command(request_payload, params)

        if self._show_curl:
            print(curl_command)

        if self._show_curl:
            print(self._format_curl_command(request_payload, params))

        start = perf_counter()
        try:
            response = self._client.post(
                self._endpoint,
                json=request_payload,
                params=params,
                headers={"Content-Type": "application/json"},
            )
            if response.status_code != httpx.codes.OK and not self._show_curl:
                print(curl_command)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Gemini provider request failed: {exc}") from exc
        self._last_latency_ms = (perf_counter() - start) * 1000

        try:
            response_body = response.json()
        except json.JSONDecodeError as exc:
            raise ValueError("Gemini provider returned a non-JSON HTTP response") from exc

        if not isinstance(response_body, Mapping):
            raise ValueError("Gemini provider response body must be a JSON object")

        usage_metadata: MutableMapping[str, Any]
        existing_usage = response_body.get("usageMetadata")
        if isinstance(existing_usage, Mapping):
            usage_metadata = dict(existing_usage)
        else:
            usage_metadata = {}
        usage_metadata.setdefault("requestcount", 1)
        response_body = dict(response_body)
        response_body["usageMetadata"] = usage_metadata

        payload = self._extract_structured_payload(response_body)
        self._merge_metadata(payload, response_body, response)
        return payload

    @property
    def last_latency_ms(self) -> float | None:
        return self._last_latency_ms


__all__ = ["GeminiStructuredLLMClient"]
