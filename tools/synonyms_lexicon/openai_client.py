from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Iterable, List

from .schema import RESPONSE_SCHEMA, SCHEMA_NAME

logger = logging.getLogger(__name__)
OpenAI: Any | None = None
OpenAIError: Any | None = None


class ResponsesAPI:
    def __init__(
        self,
        model: str,
        temperature: float,
        timeout: int,
        max_retries: int,
        rate_limit_sleep: float,
        show_curl: bool = True,
    ) -> None:
        global OpenAI, OpenAIError
        if OpenAI is None or OpenAIError is None:
            from openai import OpenAI as _OpenAI, OpenAIError as _OpenAIError

            OpenAI = _OpenAI
            OpenAIError = _OpenAIError

        self.client = OpenAI(timeout=timeout)
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries
        self.rate_limit_sleep = rate_limit_sleep
        self.show_curl = show_curl
        self._openai_error: Any = OpenAIError

    def generate(
        self,
        instructions: str,
        rows: Iterable[Dict[str, str]],
        max_synonyms: int,
    ) -> List[Dict[str, object]]:
        request_payload = self._build_request_payload(
            instructions, list(rows), max_synonyms
        )
        attempts = 0
        last_error: Exception | None = None
        while attempts <= self.max_retries:
            try:
                if self.show_curl:
                    print(self._render_curl(request_payload))
                response = self.client.responses.create(
                    **request_payload,
                )
                if hasattr(response, "output_parsed"):
                    return response.output_parsed  # type: ignore[no-any-return]
                # Fallback for libraries returning text
                return json.loads(response.output[0].content[0].text)  # type: ignore[index]
            except self._openai_error as exc:  # pragma: no cover - exercised through retry tests
                last_error = exc
                attempts += 1
                sleep_seconds = self.rate_limit_sleep * max(1, attempts)
                logger.warning(
                    "OpenAI error on attempt %s/%s: %s",
                    attempts,
                    self.max_retries,
                    exc,
                )
                time.sleep(sleep_seconds)
            except Exception as exc:  # pragma: no cover - defensive
                last_error = exc
                attempts += 1
                logger.warning(
                    "Unexpected error on attempt %s/%s: %s",
                    attempts,
                    self.max_retries,
                    exc,
                )
                time.sleep(self.rate_limit_sleep * max(1, attempts))
        raise RuntimeError(
            f"Failed to fetch response after {self.max_retries} retries: {last_error}"
        )

    def _build_request_payload(
        self, instructions: str, rows: Iterable[Dict[str, str]], max_synonyms: int
    ) -> Dict[str, object]:
        payload = list(rows)
        response_format = {
            "format": {
                "type": "json_schema",
                "name": SCHEMA_NAME,
                "schema": RESPONSE_SCHEMA,
                "strict": True,
            },
        }
        rows_json = json.dumps(payload, ensure_ascii=False)
        user_input = (
            "Return synonyms for each of the provided rows as JSON matching the schema. "
            f"Max {max_synonyms} synonyms per row. Rows JSON: {rows_json}"
        )
        return {
            "model": self.model,
            "input": [{"role": "user", "content": user_input}],
            "instructions": instructions,
            "text": response_format,
            "temperature": self.temperature,
        }

    def build_curl(
        self, instructions: str, rows: Iterable[Dict[str, str]], max_synonyms: int
    ) -> str:
        request_payload = self._build_request_payload(instructions, rows, max_synonyms)
        return self._render_curl(request_payload)

    def _render_curl(self, request_payload: Dict[str, object]) -> str:
        body = json.dumps(request_payload, ensure_ascii=False, indent=2)
        escaped_body = body.replace("'", "'\"'\"'")
        return (
            "curl https://api.openai.com/v1/responses "
            '-H "Content-Type: application/json" '
            '-H "Authorization: Bearer $OPENAI_API_KEY" '
            f"-d '{escaped_body}'"
        )
