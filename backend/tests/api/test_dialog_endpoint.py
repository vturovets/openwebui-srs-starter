import asyncio
import csv
import json
from pathlib import Path

import pytest

from backend.app.api.routes import DialogRequest, dialog_turn
from backend.app.config import Settings
from backend.app.logging.csv_logger import CSVLogger
from backend.app.pipeline.dialog import DialogOrchestrator
from backend.app.pipeline.pipeline import HolidaySearchPipeline


REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPO_ROOT / "fixtures"


@pytest.fixture()
def dialog_context(tmp_path):
    settings = Settings(
        fixtures_dir=FIXTURES_DIR,
        csv_path=tmp_path / "dialog-log.csv",
        interaction_mode="dialog",
    )
    settings.ensure_directories()

    pipeline = HolidaySearchPipeline(settings=settings, fixtures_dir=settings.fixtures_dir)
    orchestrator = DialogOrchestrator(pipeline=pipeline, settings=settings)
    logger = CSVLogger(
        path=settings.csv_path,
        fieldnames=(
            "Timestamp",
            "Input",
            "Language",
            "Method",
            "STT",
            "ProcessingTime",
            "Output",
            "Status",
            "ThresholdBreached",
            "SessionId",
            "DialogStatus",
            "MissingParameters",
            "Prompt",
            "Transcript",
        ),
    )

    return {
        "settings": settings,
        "orchestrator": orchestrator,
        "logger": logger,
    }


def test_dialog_clarification_flow(dialog_context):
    async def scenario() -> None:
        settings = dialog_context["settings"]
        orchestrator = dialog_context["orchestrator"]
        logger = dialog_context["logger"]

        first_request = DialogRequest(text="Plan a holiday from Amsterdam to Spain", mode="dialog")
        first_response = await dialog_turn(first_request, settings=settings, orchestrator=orchestrator, logger=logger)
        first_payload = first_response.model_dump(by_alias=True)

        assert first_payload["status"] == "clarification"
        assert first_payload["prompt"]["parameter"] == "departureDate"
        assert first_payload["sessionId"]
        assert first_payload["metadata"]["mode"] == "dialog"
        assert first_payload["metadata"]["missingParameters"] == ["departureDate"]
        assert len(first_payload["metadata"]["transcript"]) == 2

        session_id = first_payload["sessionId"]

        second_request = DialogRequest(text="Leaving on 10 October 2025", sessionId=session_id)
        second_response = await dialog_turn(second_request, settings=settings, orchestrator=orchestrator, logger=logger)
        second_payload = second_response.model_dump(by_alias=True)

        assert second_payload["status"] == "success"
        assert second_payload["sessionId"] == session_id
        assert second_payload["prompt"] is None
        assert second_payload["data"]["from"]
        assert second_payload["data"]["to"]
        assert second_payload["data"]["departureDate"]
        assert second_payload["metadata"]["missingParameters"] == []
        assert len(second_payload["metadata"]["transcript"]) == 3
        assert second_payload["metadata"]["timings"]["thresholdBreached"] is False

        with settings.csv_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        assert len(rows) == 2
        first_row, second_row = rows

        assert first_row["DialogStatus"] == "clarification"
        assert json.loads(first_row["MissingParameters"])[0] == "departureDate"
        assert json.loads(first_row["Transcript"])[0]["role"] == "user"

        assert second_row["DialogStatus"] == "success"
        assert second_row["Status"] == "success"
        assert json.loads(second_row["Transcript"])[-1]["role"] == "user"

    asyncio.run(scenario())


def test_dialog_direct_mode_returns_failed_without_prompt(dialog_context):
    async def scenario() -> None:
        settings = dialog_context["settings"]
        orchestrator = dialog_context["orchestrator"]
        logger = dialog_context["logger"]

        request = DialogRequest(text="Plan a holiday from Amsterdam to Spain", mode="direct-parse")
        response = await dialog_turn(request, settings=settings, orchestrator=orchestrator, logger=logger)
        payload = response.model_dump(by_alias=True)

        assert payload["status"] in {"failed", "error"}
        assert payload["prompt"] is None
        assert payload["sessionId"] is None
        assert payload["metadata"]["mode"] == "direct-parse"
        assert payload["metadata"]["validation"]["status"] == "failed"

    asyncio.run(scenario())
