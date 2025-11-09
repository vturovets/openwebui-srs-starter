"""Open-WebUI backend extension wiring for the holiday search API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, MutableMapping

from .holiday_search_connector import HolidaySearchConnector, ParseResult


def _coerce_sequence(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _derive_clarifications(parse_result: ParseResult) -> list[dict[str, str]]:
    """Build clarification prompts based on validation metadata."""

    metadata = parse_result.metadata or {}
    validation = metadata.get("validation") or {}

    errors: Iterable[Mapping[str, Any]]
    if isinstance(validation, Mapping):
        raw_errors = validation.get("errors", []) or []
        if isinstance(raw_errors, Iterable):
            errors = [item for item in raw_errors if isinstance(item, Mapping)]
        else:  # pragma: no cover - defensive branch
            errors = []
    else:  # pragma: no cover - defensive branch
        errors = []

    prompts: list[dict[str, str]] = []
    for error in errors:
        message = str(error.get("message", "")).strip()
        parameter = str(error.get("parameter", "")).strip()
        reason = str(error.get("code", "")).strip()
        if not message:
            continue
        prompts.append(
            {
                "parameter": parameter or "unknown",
                "message": message,
                "reason": reason or "validation",
            }
        )

    missing_fields = metadata.get("missingFields")
    if isinstance(missing_fields, Iterable) and not prompts:
        prompts.extend(
            {
                "parameter": str(field),
                "message": f"Please provide a value for {field}.",
                "reason": "missing",
            }
            for field in missing_fields
        )

    return prompts


def _extract_recognized(metadata: Mapping[str, Any]) -> dict[str, list[str]]:
    recognized = metadata.get("recognized")
    if not isinstance(recognized, Mapping):
        recognized = {}
    normalized: dict[str, list[str]] = {
        "airports": _coerce_sequence(recognized.get("airports")),
        "destinations": _coerce_sequence(recognized.get("destinations")),
        "dates": _coerce_sequence(recognized.get("dates")),
    }

    entities = metadata.get("recognizedEntities")
    if isinstance(entities, Mapping):
        for key in ("airports", "destinations", "dates"):
            items = entities.get(key)
            if isinstance(items, Iterable):
                normalized[key] = [str(item) for item in items]

    return normalized


@dataclass(slots=True)
class HolidaySearchToolConfig:
    """Configuration surface exposed to the Open-WebUI runtime."""

    base_url: str
    interaction_mode: str = "direct-parse"
    llm_method: str | None = None
    voice_enabled: bool = False
    timeout: float = 10.0


class HolidaySearchTool:
    """Wrapper that adapts :class:`HolidaySearchConnector` for Open-WebUI."""

    def __init__(
        self,
        config: HolidaySearchToolConfig,
        *,
        transport=None,
    ) -> None:
        self.config = config
        self._connector = HolidaySearchConnector(
            config.base_url,
            default_mode=config.interaction_mode,
            default_method=config.llm_method,
            timeout=config.timeout,
            transport=transport,
        )

    @property
    def interaction_mode(self) -> str:
        return self.config.interaction_mode

    @interaction_mode.setter
    def interaction_mode(self, value: str) -> None:
        self.config.interaction_mode = value

    @property
    def llm_method(self) -> str | None:
        return self.config.llm_method

    @llm_method.setter
    def llm_method(self, value: str | None) -> None:
        self.config.llm_method = value

    @property
    def voice_enabled(self) -> bool:
        return self.config.voice_enabled

    @voice_enabled.setter
    def voice_enabled(self, value: bool) -> None:
        self.config.voice_enabled = value

    def set_options(self, **kwargs: Any) -> None:
        """Bulk update the connector configuration at runtime."""

        if "interaction_mode" in kwargs:
            self.interaction_mode = str(kwargs["interaction_mode"])
        if "llm_method" in kwargs:
            llm_method = kwargs["llm_method"]
            self.llm_method = str(llm_method) if llm_method is not None else None
        if "voice_enabled" in kwargs:
            self.voice_enabled = bool(kwargs["voice_enabled"])

    def parse(self, text: str, *, mode: str | None = None, method: str | None = None) -> dict[str, Any]:
        """Invoke the FastAPI `/v1/parse` endpoint and normalise the payload."""

        result = self._connector.parse(text, mode=mode, method=method)
        metadata = dict(result.metadata)
        metadata.setdefault("mode", mode or self.interaction_mode)
        metadata.setdefault("method", method or self.llm_method)
        available_methods = metadata.get("availableMethods")
        if not isinstance(available_methods, list):
            metadata["availableMethods"] = []
        if "defaultMethod" not in metadata:
            metadata["defaultMethod"] = self.llm_method
        defaults_payload = metadata.get("methodDefaults")
        if not isinstance(defaults_payload, Mapping):
            metadata["methodDefaults"] = {}
        metadata["recognizedSummaries"] = _extract_recognized(metadata)
        clarifications = _derive_clarifications(result)

        payload: MutableMapping[str, Any] = {
            "status": result.status,
            "data": result.data,
            "metadata": metadata,
        }
        if clarifications:
            payload["clarifications"] = clarifications
        return dict(payload)

    def dialog(self, text: str, *, session_id: str | None = None) -> Mapping[str, Any]:
        """Proxy dialog requests for multi-turn clarification flows."""

        response = self._connector._request(  # noqa: SLF001 - extension endpoint proxy
            "POST",
            "/v1/dialog",
            {
                "text": text,
                "sessionId": session_id,
                "mode": self.interaction_mode,
                "method": self.llm_method,
            },
        )
        if not isinstance(response, Mapping):
            raise TypeError("/v1/dialog returned an unexpected payload shape")
        return response

    def fixtures(self) -> Mapping[str, Any]:
        """Expose cached fixtures so the UI can seed dropdowns."""

        response = self._connector.fixtures()
        enriched = dict(response)
        enriched["voiceEnabled"] = self.voice_enabled
        enriched["mode"] = self.interaction_mode
        enriched["llmMethod"] = self.llm_method
        available_methods = response.get("availableMethods")
        if isinstance(available_methods, list):
            enriched["availableMethods"] = list(available_methods)
        else:
            enriched["availableMethods"] = []
        default_method = response.get("defaultMethod")
        if isinstance(default_method, str) and default_method:
            enriched["defaultMethod"] = default_method
        else:
            enriched["defaultMethod"] = self.llm_method
        defaults_payload = response.get("methodDefaults")
        if isinstance(defaults_payload, Mapping):
            enriched["methodDefaults"] = dict(defaults_payload)
        else:
            enriched["methodDefaults"] = {}
        return enriched

    def voice(self, audio_payload: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        """Forward voice requests to the FastAPI `/v1/voice` endpoint."""

        if audio_payload is None:
            response = self._connector.voice()
        else:
            response = self._connector._request(  # noqa: SLF001 - extension endpoint proxy
                "POST",
                "/v1/voice",
                audio_payload,
            )
        if not isinstance(response, Mapping):
            raise TypeError("/v1/voice returned an unexpected payload shape")
        metadata = dict(response.get("metadata") or {})
        metadata.setdefault("mode", self.interaction_mode)
        response_payload = dict(response)
        response_payload["metadata"] = metadata
        return response_payload


__all__ = ["HolidaySearchTool", "HolidaySearchToolConfig"]

