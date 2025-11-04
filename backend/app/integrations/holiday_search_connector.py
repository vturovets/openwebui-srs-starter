"""HTTP connector for exposing the SRS backend to Open-WebUI tools."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request


class HolidaySearchAPIError(RuntimeError):
    """Raised when the upstream SRS backend responds with an error."""

    def __init__(self, message: str, *, status_code: int, body: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass(slots=True)
class _TransportResponse:
    status_code: int
    body: str


class Transport(Protocol):
    def __call__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        data: bytes | None,
        timeout: float,
    ) -> _TransportResponse: ...


def _default_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    data: bytes | None,
    timeout: float,
) -> _TransportResponse:
    request = urllib_request.Request(url=url, data=data, headers=dict(headers), method=method)
    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:  # type: ignore[call-arg]
            body = response.read().decode("utf-8")
            return _TransportResponse(status_code=response.getcode(), body=body)
    except urllib_error.HTTPError as exc:  # pragma: no cover - exercised via tests
        error_body = exc.read().decode("utf-8")
        return _TransportResponse(status_code=exc.code, body=error_body)


@dataclass(slots=True)
class ParseResult:
    """Structured response returned from the `/v1/parse` endpoint."""

    status: str
    data: Mapping[str, Any]
    metadata: Mapping[str, Any]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ParseResult":
        status = str(payload.get("status", ""))
        data = payload.get("data") or {}
        metadata = payload.get("metadata") or {}
        if not isinstance(data, Mapping) or not isinstance(metadata, Mapping):
            raise TypeError("/v1/parse returned an unexpected payload shape")
        return cls(status=status, data=data, metadata=metadata)

    @property
    def validation_errors(self) -> list[str]:
        validation = self.metadata.get("validation", {})
        errors: Iterable[Mapping[str, Any]]
        if isinstance(validation, Mapping):
            errors = validation.get("errors", []) or []
        else:
            errors = []
        extracted: list[str] = []
        for item in errors:
            if isinstance(item, Mapping) and "message" in item and item["message"] is not None:
                extracted.append(str(item["message"]))
        return extracted

    @property
    def is_failed(self) -> bool:
        return self.status.lower() == "failed"


class HolidaySearchConnector:
    """Thin HTTP client that proxies calls from Open-WebUI to the SRS backend."""

    def __init__(
        self,
        base_url: str,
        *,
        default_mode: str,
        default_method: str | None = None,
        timeout: float = 10.0,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_mode = default_mode
        self.default_method = default_method
        self.timeout = timeout
        self._transport = transport or _default_transport

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Mapping[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {"Content-Type": "application/json"}
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        response = self._transport(method, url, headers, data, self.timeout)

        if response.status_code >= 400:
            raise HolidaySearchAPIError(
                f"{path} returned HTTP {response.status_code}",
                status_code=response.status_code,
                body=response.body,
            )

        body = response.body.strip()
        return json.loads(body or "{}")

    def parse(self, text: str, *, mode: str | None = None, method: str | None = None) -> ParseResult:
        payload = {
            "text": text,
            "mode": mode or self.default_mode,
            "method": method or self.default_method,
        }
        response = self._request("POST", "/v1/parse", payload)
        return ParseResult.from_payload(response)

    def fixtures(self) -> Mapping[str, Any]:
        response = self._request("GET", "/v1/fixtures")
        if not isinstance(response, Mapping):
            raise TypeError("/v1/fixtures returned an unexpected payload shape")
        return response

    def voice(self) -> Mapping[str, Any]:
        response = self._request("POST", "/v1/voice")
        if not isinstance(response, Mapping):
            raise TypeError("/v1/voice returned an unexpected payload shape")
        return response

