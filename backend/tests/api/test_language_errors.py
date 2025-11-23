import asyncio

import pytest
from fastapi import HTTPException

from backend.app.api.routes import ParseRequest, parse_text
from backend.app.config import Settings
from backend.app.pipeline.language import LanguageNotPermittedError


class StubLogger:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def log(self, payload: dict[str, object]) -> None:  # pragma: no cover - interface compatibility
        self.rows.append(payload)


class StubPipeline:
    def run(self, text: str, method: str | None = None):
        raise LanguageNotPermittedError("Detected language 'fr' is not permitted")


def test_parse_endpoint_surfaces_language_errors() -> None:
    settings = Settings(allowed_langs=["en"])
    pipeline = StubPipeline()
    logger = StubLogger()

    request = ParseRequest(text="Bonjour le monde", mode=None, method=None, batch=None, import_mode=False)

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(
            parse_text(
                payload=request,
                settings=settings,
                pipeline=pipeline,
                logger=logger,
                summary_logger=None,
            )
        )

    assert excinfo.value.status_code == 400
    assert "Supported languages" in str(excinfo.value.detail)
