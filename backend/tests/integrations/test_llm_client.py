"""Tests for the structured holiday search LLM client."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from backend.app.config import Settings
from backend.app.integrations.gemini import GeminiStructuredLLMClient
from backend.app.integrations.llm import HolidaySearchLLMClient
from backend.app.fixtures.repository import FixtureRepository
from backend.app.pipeline.configuration import SearchConfiguration
from backend.app.pipeline.extractors import LLMExtractor


REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPO_ROOT / "fixtures"
CONFIG_PATH = FIXTURES_DIR / "configuration_search.json"


def _load_configuration() -> SearchConfiguration:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return SearchConfiguration.from_fixture_payload(payload)


def _build_settings(tmp_path: Path) -> Settings:
    return Settings(
        llm_api_base="https://mock-llm",
        llm_api_key="test-key",
        llm_model="gpt-test",
        llm_timeout=5,
        fixtures_dir=FIXTURES_DIR,
        csv_path=tmp_path / "log.csv",
    )


def _build_gemini_settings(tmp_path: Path) -> Settings:
    return Settings(
        llm_api_base="https://generativelanguage.googleapis.com",
        llm_api_key="gemini-key",
        llm_model="gemini-1.5-flash",
        llm_timeout=5,
        fixtures_dir=FIXTURES_DIR,
        csv_path=tmp_path / "log.csv",
    )


def test_llm_client_success_payload_matches_extractor(tmp_path: Path) -> None:
    """HolidaySearchLLMClient should return structured payloads the extractor accepts."""

    llm_content = {
        "airports": ["AMS", {"id": "ANR", "name": "Antwerp", "available": True}],
        "destinations": [
            "d7b4bb39-2000-1234-aaac-1234567d",
            {"id": "d7b4bb39-2000-1234-aaaa-1234567a", "name": "Australia"},
        ],
        "duration": "2007",
        "flexibility": {"id": "3", "name": "+- 3 days"},
        "dates": [
            "2025-10-10",
            {"phrase": "12 October 2025", "iso": "2025-10-12"},
        ],
        "_metadata": {
            "provider": "mock-llm",
            "promptId": "prompt-xyz",
            "responseId": "response-abc",
        },
    }

    response_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(llm_content),
                }
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        return httpx.Response(200, json=response_payload)

    http_client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://mock-llm")

    settings = _build_settings(tmp_path)
    llm_client = HolidaySearchLLMClient(
        settings=settings,
        fixtures_dir=settings.fixtures_dir,
        http_client=http_client,
    )

    payload = llm_client("Plan a sunny holiday")

    fixtures = FixtureRepository(FIXTURES_DIR)
    configuration = _load_configuration()
    extractor = LLMExtractor(fixtures, configuration, llm_client=lambda _: payload)

    extraction = extractor.extract("Plan a sunny holiday")

    assert [airport["id"] for airport in extraction.airports] == ["AMS", "ANR"]
    assert extraction.destinations[0]["id"] == "d7b4bb39-2000-1234-aaac-1234567d"
    assert extraction.destinations[1]["name"] == "Australia"
    assert extraction.duration and extraction.duration["id"] == "2007"
    assert extraction.flexibility and extraction.flexibility["id"] == "3"
    assert [iso.isoformat() for _, iso in extraction.dates] == ["2025-10-10T00:00:00", "2025-10-12T00:00:00"]


def test_llm_client_raises_on_malformed_message(tmp_path: Path) -> None:
    """The client should surface provider payload issues as value errors."""

    response_payload = {
        "choices": [
            {
                "message": {
                    "content": "not-json",
                }
            }
        ]
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_payload)

    http_client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://mock-llm")

    settings = _build_settings(tmp_path)
    llm_client = HolidaySearchLLMClient(
        settings=settings,
        fixtures_dir=settings.fixtures_dir,
        http_client=http_client,
    )

    with pytest.raises(ValueError, match="non-JSON message content"):
        llm_client("Malformed payload please")


def test_gemini_client_builds_structured_payload(tmp_path: Path) -> None:
    """The Gemini client should build structured requests and propagate metadata."""

    captured: dict[str, object] = {}

    structured_response = {
        "airports": ["AMS", {"id": "ANR", "name": "Antwerp"}],
        "destinations": [
            "d7b4bb39-2000-1234-aaac-1234567d",
            {"id": "d7b4bb39-2000-1234-aaaa-1234567a", "name": "Australia"},
        ],
        "duration": "2007",
        "flexibility": {"id": "3", "name": "+- 3 days"},
        "dates": [
            "2025-10-10",
            {"phrase": "12 October 2025", "iso": "2025-10-12"},
        ],
    }

    response_payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(structured_response),
                        }
                    ],
                },
                "finishReason": "STOP",
            }
        ],
        "modelVersion": "2024-05-01",
        "usageMetadata": {"promptTokenCount": 42},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["json"] = json.loads(request.content.decode("utf-8"))

        assert request.url.path == "/v1beta/models/gemini-1.5-flash:generateContent"
        assert request.url.params["key"] == "gemini-key"
        assert request.headers["Content-Type"] == "application/json"

        return httpx.Response(
            200,
            json=response_payload,
            headers={"x-request-id": "req-123", "x-trace-id": "trace-456"},
        )

    http_client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://generativelanguage.googleapis.com",
    )

    settings = _build_gemini_settings(tmp_path)
    llm_client = GeminiStructuredLLMClient(
        settings=settings,
        fixtures_dir=settings.fixtures_dir,
        http_client=http_client,
    )

    payload = llm_client("Plan a sunny holiday")

    assert llm_client.last_latency_ms is not None

    request_payload = captured.get("json")
    assert isinstance(request_payload, dict)

    generation_config = request_payload.get("generation_config")
    assert isinstance(generation_config, dict)
    assert generation_config.get("response_mime_type") == "application/json"
    assert "response_schema" in generation_config

    contents = request_payload.get("contents")
    assert isinstance(contents, list) and contents
    user_part = contents[0]["parts"][0]["text"]
    query_payload = json.loads(user_part)
    assert query_payload["task"] == "extract_search_parameters"
    assert query_payload["metadata"]["flexibility"]["allowed"] is True

    assert payload["airports"][0] == "AMS"
    assert payload["destinations"][1]["name"] == "Australia"

    metadata = payload.get("_metadata")
    assert isinstance(metadata, dict)
    assert metadata["provider"] == "google-gemini"
    assert metadata["requestId"] == "req-123"
    assert metadata["traceId"] == "trace-456"
    assert metadata["finishReason"] == "STOP"
    assert metadata["usageMetadata"] == {"promptTokenCount": 42}


def test_gemini_client_raises_on_malformed_response(tmp_path: Path) -> None:
    """Gemini client should surface malformed responses as value errors."""

    response_payload = {"candidates": []}

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_payload)

    http_client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://generativelanguage.googleapis.com",
    )

    settings = _build_gemini_settings(tmp_path)
    llm_client = GeminiStructuredLLMClient(
        settings=settings,
        fixtures_dir=settings.fixtures_dir,
        http_client=http_client,
    )

    with pytest.raises(ValueError, match="did not include any candidates"):
        llm_client("Malformed payload please")
