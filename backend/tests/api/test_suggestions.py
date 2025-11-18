"""Tests for the /v1/suggestions endpoint."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

from fastapi.testclient import TestClient

from backend.app.dependencies import get_auto_completion_service, get_settings
from backend.app.main import create_app


class StubSettings:
    def __init__(self, *, suggestions_enabled: bool = True, suggestions_limit: int = 3) -> None:
        self.suggestions_enabled = suggestions_enabled
        self.suggestions_limit = suggestions_limit


class RecordingAutoCompletionService:
    def __init__(self, response_factory: Callable[[str, int], Dict[str, List[Dict[str, object]]]]) -> None:
        self._response_factory = response_factory
        self.calls: List[Tuple[str, int]] = []

    def suggest(self, partial_query: str, limit: int) -> Dict[str, List[Dict[str, object]]]:
        self.calls.append((partial_query, limit))
        return self._response_factory(partial_query, limit)


def build_suggestions(**overrides: Any) -> Dict[str, List[Dict[str, object]]]:
    payload: Dict[str, List[Dict[str, object]]] = {
        "destinations": [],
        "departureDates": [],
        "durations": [],
        "party": [],
        "rooms": [],
        "from": [],
    }
    for key, value in overrides.items():
        payload[key] = value
    return payload


def create_client(settings: StubSettings, service: RecordingAutoCompletionService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_auto_completion_service] = lambda: service
    return TestClient(app)


def test_suggestions_endpoint_returns_empty_payload_when_feature_disabled():
    settings = StubSettings(suggestions_enabled=False, suggestions_limit=5)
    service = RecordingAutoCompletionService(lambda *_: build_suggestions())
    client = create_client(settings, service)

    response = client.get("/v1/suggestions", params={"q": "  safari ideas  "})

    assert response.status_code == 200
    assert response.json() == {"suggestions": {}}
    assert service.calls == []


def test_suggestions_endpoint_preserves_destination_ordering():
    destinations = [
        {"value": "Kenya", "source": "text"},
        {"value": "Japan", "source": "text"},
    ]
    settings = StubSettings(suggestions_enabled=True, suggestions_limit=5)

    def responder(partial_query: str, limit: int) -> Dict[str, List[Dict[str, object]]]:
        assert partial_query == "kenya and japan"
        assert limit == 3
        return build_suggestions(destinations=destinations)

    service = RecordingAutoCompletionService(responder)
    client = create_client(settings, service)

    response = client.get("/v1/suggestions", params={"q": "  kenya and japan  "})

    assert response.status_code == 200
    assert response.json() == {"suggestions": build_suggestions(destinations=destinations)}
    assert service.calls == [("kenya and japan", 3)]


def test_suggestions_endpoint_returns_fallback_intervals_when_intersection_empty():
    fallback_intervals = [
        {"start": "2026-01-05", "end": "2026-01-12", "source": "global"},
        {"start": "2026-02-10", "end": "2026-02-17", "source": "global"},
    ]
    settings = StubSettings(suggestions_enabled=True, suggestions_limit=3)

    def responder(*_: object) -> Dict[str, List[Dict[str, object]]]:
        return build_suggestions(departureDates=fallback_intervals)

    service = RecordingAutoCompletionService(responder)
    client = create_client(settings, service)

    response = client.get("/v1/suggestions", params={"q": "kenya and japan"})

    assert response.status_code == 200
    assert response.json() == {"suggestions": build_suggestions(departureDates=fallback_intervals)}


def test_suggestions_endpoint_enforces_limit_cap():
    destinations = [
        {"value": "Kenya", "source": "text"},
        {"value": "Japan", "source": "text"},
    ]
    settings = StubSettings(suggestions_enabled=True, suggestions_limit=4)

    def responder(partial_query: str, limit: int) -> Dict[str, List[Dict[str, object]]]:
        assert limit == 4
        return build_suggestions(destinations=destinations[:limit])

    service = RecordingAutoCompletionService(responder)
    client = create_client(settings, service)

    response = client.get("/v1/suggestions", params={"q": "Kenya", "limit": 10})

    assert response.status_code == 200
    assert response.json() == {"suggestions": build_suggestions(destinations=destinations[:4])}
    assert service.calls == [("Kenya", 4)]
