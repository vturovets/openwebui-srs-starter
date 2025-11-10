"""Tests for the structured LLM client integrations."""

from __future__ import annotations

import json
from typing import Mapping, Sequence

import httpx

from backend.app.integrations.llm import StructuredLLMClient


class _TestableLLMClient(StructuredLLMClient):
    """Minimal concrete implementation for exercising the base behaviour."""

    def _build_messages(self, text: str) -> Sequence[Mapping[str, str]]:
        return [{"role": "user", "content": text}]


def test_structured_llm_client_retries_without_json_mode_on_400() -> None:
    """Ensure we gracefully fallback when providers reject JSON mode."""

    call_payloads: list[Mapping[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        call_payloads.append(payload)
        if "response_format" in payload:
            return httpx.Response(
                400,
                json={"error": {"message": "response_format is not supported"}},
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"echo": payload["messages"][0]["content"]})
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://example.com")

    llm_client = _TestableLLMClient(
        api_base=None,
        api_key="dummy",
        model="gpt-4o-mini",
        timeout=5,
        http_client=client,
    )

    first_result = llm_client("hello world")
    assert first_result == {"echo": "hello world"}
    # Two HTTP calls were made: one failing with JSON mode, one succeeding without.
    assert len(call_payloads) == 2
    assert "response_format" in call_payloads[0]
    assert "response_format" not in call_payloads[1]

    second_result = llm_client("no retry expected")
    assert second_result == {"echo": "no retry expected"}
    # Subsequent requests should skip JSON mode entirely.
    assert len(call_payloads) == 3
    assert "response_format" not in call_payloads[-1]

