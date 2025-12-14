from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Iterable, List, Sequence

from .lexicon import LexiconOption

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
        schema: Dict[str, Any],
        show_curl: bool = False,
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
        self.schema = schema
        self._openai_error: Any = OpenAIError

    def _build_request_payload(self, instructions: str, payload: List[Dict[str, Any]]) -> Dict[str, Any]:
        response_format = {
            "format": {
                "type": "json_schema",
                "name": "utterance_generation",
                "schema": self.schema,
                "strict": True,
            }
        }
        user_content = f"Generate utterances for the provided options as JSON. Rows: {json.dumps(payload, ensure_ascii=False)}"
        return {
            "model": self.model,
            "input": [{"role": "user", "content": user_content}],
            "instructions": instructions,
            "text": response_format,
            "temperature": self.temperature,
        }

    def generate(self, instructions: str, payload: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        request_payload = self._build_request_payload(instructions, payload)
        attempts = 0
        last_error: Exception | None = None
        while attempts <= self.max_retries:
            try:
                if self.show_curl:
                    print(self._render_curl(request_payload))
                response = self.client.responses.create(**request_payload)
                if hasattr(response, "output_parsed"):
                    return response.output_parsed  # type: ignore[no-any-return]
                return json.loads(response.output[0].content[0].text)  # pragma: no cover - fallback
            except self._openai_error as exc:  # pragma: no cover - network call
                attempts += 1
                last_error = exc
                logger.warning("OpenAI error attempt %s/%s: %s", attempts, self.max_retries, exc)
                time.sleep(self.rate_limit_sleep * max(1, attempts))
        raise RuntimeError(f"Failed to fetch response after {self.max_retries} retries: {last_error}")

    def _render_curl(self, payload: Dict[str, Any]) -> str:
        body = json.dumps(payload, ensure_ascii=False, indent=2)
        escaped_body = body.replace("'", "'\"'\"'")
        return (
            "curl https://api.openai.com/v1/responses "
            '-H "Content-Type: application/json" '
            '-H "Authorization: Bearer $OPENAI_API_KEY" '
            f"-d '{escaped_body}'"
        )


class EmbeddingsAPI:
    def __init__(self, model: str, timeout: int) -> None:
        global OpenAI
        if OpenAI is None:
            from openai import OpenAI as _OpenAI

            OpenAI = _OpenAI
        self.client = OpenAI(timeout=timeout)
        self.model = model

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        response = self.client.embeddings.create(model=self.model, input=list(texts))
        return [record.embedding for record in response.data]


def build_centroids(options: Iterable[LexiconOption], embedder: EmbeddingsAPI) -> Dict[str, List[float]]:
    centroids: Dict[str, List[float]] = {}
    for option in options:
        texts = option.terms
        embeddings = embedder.embed(texts)
        centroid = [sum(values) / len(values) for values in zip(*embeddings)]
        centroids[option.optionId] = centroid
    return centroids
