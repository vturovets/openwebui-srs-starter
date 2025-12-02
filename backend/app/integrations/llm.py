"""HTTP client helpers for structured LLM extraction."""

from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping, MutableMapping, Sequence

from datetime import date, timedelta

import httpx

from ..config import Settings
from ..fixtures.repository import FixtureRepository
from ..pipeline.configuration import SearchConfiguration


CONFIGURATION_FILENAME = "configuration_search.json"


class StructuredLLMClient:
    """Base client that posts structured prompts to an LLM provider."""

    def __init__(
        self,
        *,
        api_base: str | None,
        api_key: str | None,
        model: str,
        timeout: float,
        endpoint: str = "/chat/completions",
        http_client: httpx.Client | None = None,
    ) -> None:
        base = (api_base or "").rstrip("/")
        if not base:
            raise ValueError("LLM provider base URL must be configured")

        self._endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        self._model = model
        self._api_key = api_key
        self._last_latency_ms: float | None = None

        self._client = http_client or httpx.Client(base_url=base, timeout=timeout)
        self._client_owner = http_client is None

    def close(self) -> None:
        """Close the underlying HTTP client when owned by this instance."""

        if self._client_owner:
            self._client.close()

    def __del__(self) -> None:  # pragma: no cover - defensive cleanup
        self.close()

    def _build_messages(self, text: str) -> Sequence[Mapping[str, str]]:
        raise NotImplementedError

    def _build_request_payload(self, text: str) -> MutableMapping[str, Any]:
        payload: MutableMapping[str, Any] = {
            "model": self._model,
            "messages": list(self._build_messages(text)),
            "temperature": 0,
        }

        if self._supports_json_mode():
            payload["response_format"] = {"type": "json_object"}

        return payload

    def _supports_json_mode(self) -> bool:
        """Return ``True`` when the configured model supports JSON mode."""

        return False

    def _headers(self) -> Mapping[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _extract_message_payload(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            choices = payload["choices"]
        except KeyError as exc:
            raise ValueError("LLM provider response is missing 'choices'") from exc
        if not isinstance(choices, Sequence) or not choices:
            raise ValueError("LLM provider response did not include any choices")

        first_choice = choices[0]
        if not isinstance(first_choice, Mapping):
            raise ValueError("LLM provider returned malformed choice data")

        message = first_choice.get("message", {})
        if not isinstance(message, Mapping):
            raise ValueError("LLM provider returned malformed message payload")

        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("LLM provider returned empty content")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("LLM provider returned non-JSON message content") from exc

        if not isinstance(parsed, Mapping):
            raise ValueError("LLM provider response content must be a JSON object")
        return parsed

    def __call__(self, text: str) -> Mapping[str, Any]:
        payload = self._build_request_payload(text)
        start = perf_counter()
        try:
            response = self._client.post(self._endpoint, json=payload, headers=self._headers())
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"LLM provider request failed: {exc}") from exc
        self._last_latency_ms = (perf_counter() - start) * 1000

        try:
            raw_payload = response.json()
        except json.JSONDecodeError as exc:
            raise ValueError("LLM provider returned a non-JSON HTTP response") from exc

        if not isinstance(raw_payload, Mapping):
            raise ValueError("LLM provider response body must be a JSON object")

        return self._extract_message_payload(raw_payload)

    @property
    def last_latency_ms(self) -> float | None:
        """Expose the last measured network latency."""

        return self._last_latency_ms


class HolidaySearchLLMClient(StructuredLLMClient):
    """Structured LLM client tailored to the holiday search SRS domain."""

    def __init__(
        self,
        settings: Settings,
        *,
        fixtures_dir: str | Path | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        fixtures_path = Path(fixtures_dir or settings.fixtures_dir)
        fixtures = FixtureRepository(fixtures_path)
        configuration = self._load_configuration(fixtures_path)

        self._metadata = {
            "airports": fixtures.list_airports(),
            "destinations": fixtures.list_destinations(),
            "durations": configuration.durations,
            "flexibility": {
                "allowed": configuration.flexibility_allowed,
                "options": configuration.flex_options,
            },
        }
        tomorrow = (date.today() + timedelta(days=1)).isoformat()

        self._system_prompt = ("You analyse travel booking queries and extract parameters for the holiday search engine. The user may or may not explicitly declare booking parameters. Respond with a JSON object containing these keys: 'airports' (list), 'destinations' (list), 'duration', 'flexibility', and 'dates' (list). Use metadata to validate extracted values against allowed ones. Return airports and destinations explicitly describing their availability according to the metadata. For missing input parameters, use default values from the metadata. Each airport and destination should reference the provided identifiers when possible. Dates should be returned as objects with 'phrase' and ISO8601 `YYYY-MM-DD` (year-month-day) 'iso' fields when detected." f" Today is '{tomorrow}'. Never return any date in past to that date, otherwise leave empty.")

        super().__init__(
            api_base=settings.llm_api_base,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout=settings.llm_timeout,
            http_client=http_client,
        )

    @staticmethod
    def _load_configuration(fixtures_dir: Path) -> SearchConfiguration:
        config_path = fixtures_dir / CONFIGURATION_FILENAME
        if not config_path.is_file():
            raise FileNotFoundError(
                f"Search configuration file '{CONFIGURATION_FILENAME}' not found in '{fixtures_dir}'"
            )
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise FileNotFoundError(f"Unable to read search configuration: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("Search configuration fixture must be a JSON object")
        return SearchConfiguration.from_fixture_payload(payload)

    def _build_messages(self, text: str) -> Sequence[Mapping[str, str]]:
        query_payload = {
            "task": "extract_search_parameters",
            "query": text,
            "metadata": self._metadata,
            "output": {
                "airports": "List of airport identifiers or objects with id/name",
                "destinations": "List of destination identifiers or objects with id/name",
                "duration": "Identifier or object from the provided durations list",
                "flexibility": "Identifier or object from the provided flexibility options",
                "dates": "List of detected travel dates with 'phrase' and 'iso' fields",
            },
        }

        messages: list[Mapping[str, str]] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": json.dumps(query_payload, ensure_ascii=False)},
        ]
        return messages


__all__ = ["StructuredLLMClient", "HolidaySearchLLMClient"]
