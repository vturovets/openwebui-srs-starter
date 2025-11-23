"""Tests for the Open-WebUI backend extension wrapper."""

from __future__ import annotations

import json

import pytest

from backend.app.integrations import HolidaySearchTool, HolidaySearchToolConfig


def build_transport():
    """Provide a canned transport for exercising the wrapper."""

    def transport(method: str, url: str, headers: dict[str, str], data: bytes | None, timeout: float):
        path = url.split("//", 1)[-1].split("/", 1)[-1]
        if path.endswith("v1/parse") and method == "POST":
            body = json.loads(data.decode("utf-8")) if data else {}
            text = body.get("text", "")
            payload = {
                "status": "failed" if "missing" in text else "success",
                "data": {"query": text},
                "metadata": {
                    "timings": {"totalMs": 42.0},
                    "validation": {
                        "errors": [
                            {
                                "message": "Destination is required",
                                "parameter": "to",
                                "code": "missing_destination",
                            }
                        ]
                    },
                    "availableMethods": [
                        {"id": "rules-basic", "type": "rules"},
                        {"id": "gpt5-default", "type": "llm"},
                    ],
                    "defaultMethod": "rules-basic",
                    "methodDefaults": {"temperature": 0.0, "timeout_s": 30},
                    "recognizedEntities": {
                        "airports": ["AMS"],
                        "destinations": [],
                        "dates": ["2025-10-10"],
                    },
                },
            }
            return type("Resp", (), {"status_code": 200, "body": json.dumps(payload)})()
        if path.endswith("v1/fixtures") and method == "GET":
            payload = {
                "airports": ["AMS", "LGW"],
                "destinations": ["Italy"],
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
                "metadata": {
                    "timings": {"totalMs": 75.0},
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


def test_parse_wraps_metadata() -> None:
    tool = HolidaySearchTool(
        HolidaySearchToolConfig(base_url="https://example.test", interaction_mode="dialog"),
        transport=build_transport(),
    )

    payload = tool.parse("missing destination")
    assert payload["status"] == "failed"
    assert payload["metadata"]["mode"] == "dialog"
    assert payload["metadata"]["recognizedSummaries"]["airports"] == ["AMS"]
    assert payload["metadata"]["availableMethods"][0]["id"] == "rules-basic"
    assert payload["metadata"]["defaultMethod"] == "rules-basic"
    assert payload["metadata"]["methodDefaults"]["temperature"] == 0.0
    assert payload["clarifications"][0]["parameter"] == "to"


def test_fixtures_include_runtime_flags() -> None:
    tool = HolidaySearchTool(
        HolidaySearchToolConfig(
            base_url="https://example.test",
            interaction_mode="dialog",
            llm_method="rules",
            voice_enabled=True,
        ),
        transport=build_transport(),
    )

    fixtures = tool.fixtures()
    assert fixtures["voiceEnabled"] is True
    assert fixtures["mode"] == "dialog"
    assert fixtures["llmMethod"] == "rules-basic"
    assert fixtures["llmMethodAlias"] == "rules"
    assert fixtures["defaultMethod"] == "rules-basic"
    assert [method["id"] for method in fixtures["availableMethods"]] == [
        "rules-basic",
        "gpt5-default",
    ]
    assert fixtures["methodDefaults"] == {"temperature": 0.0, "timeout_s": 30}


def test_voice_passthrough_enriches_metadata() -> None:
    tool = HolidaySearchTool(
        HolidaySearchToolConfig(base_url="https://example.test"),
        transport=build_transport(),
    )

    response = tool.voice({"mock": True})
    assert response["metadata"]["mode"] == "direct-parse"
    assert response["metadata"]["availableMethods"][1]["id"] == "gpt5-default"


def test_dialog_payload_requires_mapping() -> None:
    def bad_transport(method: str, url: str, headers, data, timeout):  # type: ignore[no-untyped-def]
        return type("Resp", (), {"status_code": 200, "body": json.dumps([1, 2, 3])})()

    tool = HolidaySearchTool(
        HolidaySearchToolConfig(base_url="https://example.test"),
        transport=bad_transport,
    )

    with pytest.raises(TypeError):
        tool.dialog("hello")

