"""Tests for the Open-WebUI connector shim."""

from __future__ import annotations

import json

from backend.app.integrations import HolidaySearchAPIError, HolidaySearchConnector, ParseResult


def build_transport():
    """Provide a transport callable with canned responses."""

    def transport(method: str, url: str, headers: dict[str, str], data: bytes | None, timeout: float):
        path = url.split("//", 1)[-1].split("/", 1)[-1]
        if path.endswith("v1/parse") and method == "POST":
            payload = {
                "status": "success",
                "data": {"mock": True},
                "metadata": {
                    "validation": {
                        "status": "failed",
                        "errors": [{"message": "missing destination"}],
                    },
                    "availableMethods": [
                        {"id": "rules-basic", "type": "rules"},
                        {"id": "gpt5-default", "type": "llm"},
                    ],
                    "defaultMethod": "rules-basic",
                    "methodDefaults": {"temperature": 0.0, "timeout_s": 30},
                },
            }
            return type("Resp", (), {"status_code": 200, "body": json.dumps(payload)})()
        if path.endswith("v1/fixtures") and method == "GET":
            payload = {
                "airports": [],
                "destinations": [],
                "llmMethod": "rules-basic",
                "llmMethodAlias": "rules",
                "availableMethods": [
                    {"id": "rules-basic", "type": "rules"},
                    {"id": "gpt5-default", "type": "llm"},
                ],
                "defaultMethod": "rules-basic",
                "methodDefaults": {"temperature": 0.0, "timeout_s": 30},
                "suggestionsEnabled": True,
                "suggestionsLimit": 3,
            }
            return type("Resp", (), {"status_code": 200, "body": json.dumps(payload)})()
        if path.endswith("v1/voice") and method == "POST":
            payload = {
                "status": "success",
                "voice_enabled": False,
                "metadata": {
                    "availableMethods": [
                        {"id": "rules-basic", "type": "rules"},
                        {"id": "gpt5-default", "type": "llm"},
                    ],
                    "defaultMethod": "rules-basic",
                },
            }
            return type("Resp", (), {"status_code": 200, "body": json.dumps(payload)})()
        return type("Resp", (), {"status_code": 404, "body": json.dumps({"detail": "not found"})})()

    return transport


def test_parse_result_reports_validation_errors() -> None:
    connector = HolidaySearchConnector(
        "https://example.test",
        default_mode="direct-parse",
        default_method="rules",
        transport=build_transport(),
    )

    result = connector.parse("Where can I travel?")
    assert isinstance(result, ParseResult)
    assert result.status == "success"
    assert result.validation_errors == ["missing destination"]
    assert result.metadata["availableMethods"][1]["id"] == "gpt5-default"
    assert result.metadata["defaultMethod"] == "rules-basic"
    assert result.metadata["methodDefaults"]["timeout_s"] == 30


def test_parse_error_raises_custom_exception() -> None:
    connector = HolidaySearchConnector(
        "https://example.test",
        default_mode="direct-parse",
        transport=lambda *args, **kwargs: type("Resp", (), {"status_code": 500, "body": json.dumps({"detail": "boom"})})(),
    )

    try:
        connector.parse("hello")
    except HolidaySearchAPIError as exc:  # noqa: PERF203 - explicit exception check
        assert exc.status_code == 500
        assert "boom" in exc.body
    else:  # pragma: no cover - ensure the exception is raised during testing
        raise AssertionError("Expected HolidaySearchAPIError to be raised")


def test_fixtures_and_voice_passthrough() -> None:
    connector = HolidaySearchConnector(
        "https://example.test",
        default_mode="direct-parse",
        transport=build_transport(),
    )

    fixtures = connector.fixtures()
    assert fixtures["airports"] == []
    assert fixtures["llmMethod"] == "rules-basic"
    assert fixtures["llmMethodAlias"] == "rules"
    assert fixtures["defaultMethod"] == "rules-basic"
    assert fixtures["availableMethods"][0]["id"] == "rules-basic"
    assert fixtures["methodDefaults"] == {"temperature": 0.0, "timeout_s": 30}

    voice = connector.voice()
    assert voice["status"] == "success"
    assert voice["metadata"]["availableMethods"][0]["id"] == "rules-basic"
