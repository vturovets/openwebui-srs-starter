import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest

from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from backend.app.api.routes import VoiceResponse, voice_endpoint
from backend.app.config import Settings
from backend.app.integrations.stt import TranscribedWord, TranscriptionResult
from backend.app.pipeline.pipeline import PipelineRunResult


class StubLogger:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def log(self, payload: dict[str, object]) -> None:
        self.rows.append(payload)


class StubPipeline:
    def __init__(self, timings: dict[str, float] | None = None) -> None:
        self.timings = timings or {"totalMs": 120.0}
        self.invocations: list[str] = []

    def run(self, utterance: str, method: str | None = None) -> PipelineRunResult:
        self.invocations.append(utterance)
        detection = SimpleNamespace(language="en", confidence=0.9)
        normalized = SimpleNamespace(to_payload=lambda: {"utterance": utterance})
        return PipelineRunResult(
            status="success",
            method_requested="rules",
            method_used="rules",
            detection=detection,
            extraction=None,
            normalized=normalized,
            validation={"status": "passed", "errors": []},
            metadata={},
            attempts=[],
            timings=dict(self.timings),
            error=None,
        )


class StubSTTClient:
    def __init__(self, transcript: str = "turn voice into text", duration_ms: float = 80.0) -> None:
        self.transcript = transcript
        self.duration_ms = duration_ms

    async def transcribe(self, *, content_type: str, stream):
        collected = bytearray()

        async for chunk in stream:
            collected.extend(chunk)

        # Emulate provider latency by sleeping for the configured duration
        await asyncio.sleep(self.duration_ms / 1000.0)

        words = [
            TranscribedWord(word=part, start=index * 0.5, end=index * 0.5 + 0.4)
            for index, part in enumerate(self.transcript.split(), start=0)
        ]
        return TranscriptionResult(text=self.transcript, words=words)


def create_upload(content: bytes, content_type: str = "audio/wav") -> UploadFile:
    headers = Headers({"content-type": content_type})
    return UploadFile(file=BytesIO(content), filename="audio.wav", headers=headers)


def test_voice_endpoint_noop_when_disabled():
    async def scenario() -> None:
        settings = Settings(voice_enabled=False)
        upload = create_upload(b"fake", content_type="audio/wav")

        response = await voice_endpoint(audio=upload, settings=settings)

        assert isinstance(response, VoiceResponse)
        assert response.status == "noop"
        assert response.voice_enabled is False
        assert response.transcript is None
        assert response.metadata["mode"] == settings.interaction_mode

    asyncio.run(scenario())


def test_voice_endpoint_rejects_large_payload():
    async def scenario() -> None:
        settings = Settings(voice_enabled=True, stt_engine="deepgram", deepgram_api_key="dg", voice_max_bytes=4)
        upload = create_upload(b"123456", content_type="audio/wav")

        pipeline = StubPipeline()
        logger = StubLogger()
        stt_client = StubSTTClient()

        with pytest.raises(HTTPException) as excinfo:
            await voice_endpoint(
                audio=upload,
                settings=settings,
                pipeline=pipeline,
                logger=logger,
                stt_client=stt_client,
            )

        assert "Audio payload exceeds maximum allowed size" in str(excinfo.value)
        assert excinfo.value.status_code == 413
        assert pipeline.invocations == []
        assert logger.rows == []

    asyncio.run(scenario())


def test_voice_endpoint_rejects_unsupported_media_type():
    async def scenario() -> None:
        settings = Settings(voice_enabled=True, stt_engine="deepgram", deepgram_api_key="dg")
        upload = create_upload(b"1234", content_type="text/plain")

        pipeline = StubPipeline()
        logger = StubLogger()
        stt_client = StubSTTClient()

        with pytest.raises(HTTPException) as excinfo:
            await voice_endpoint(
                audio=upload,
                settings=settings,
                pipeline=pipeline,
                logger=logger,
                stt_client=stt_client,
            )

        assert "Unsupported audio format" in str(excinfo.value)
        assert excinfo.value.status_code == 415
        assert pipeline.invocations == []

    asyncio.run(scenario())


def test_voice_endpoint_transcribes_and_logs(tmp_path):
    async def scenario() -> None:
        settings = Settings(
            voice_enabled=True,
            stt_engine="deepgram",
            deepgram_api_key="dg",
            voice_max_bytes=1024,
            csv_path=tmp_path / "voice-log.csv",
        )
        pipeline_timings = {"totalMs": 150.0, "languageMs": 20.0, "extractionMs": 50.0}
        pipeline = StubPipeline(timings=pipeline_timings)
        logger = StubLogger()
        stt_client = StubSTTClient(transcript="book flights to spain", duration_ms=60.0)
        upload = create_upload(b"audio-bytes", content_type="audio/wav")

        response = await voice_endpoint(
            audio=upload,
            settings=settings,
            pipeline=pipeline,
            logger=logger,
            stt_client=stt_client,
        )

        assert isinstance(response, VoiceResponse)
        assert response.status == "success"
        assert response.transcript == "book flights to spain"
        assert response.engine == "deepgram"
        assert response.words
        assert pipeline.invocations == ["book flights to spain"]

        timings = response.metadata["timings"]
        assert timings["pipelineTotalMs"] == pytest.approx(150.0)
        assert timings["sttMs"] >= 60.0
        assert timings["totalMs"] >= timings["sttMs"] + pipeline_timings["totalMs"]
        assert timings["thresholdBreached"] == (timings["totalMs"] > settings.processing_threshold_ms)

        assert logger.rows
        log_entry = logger.rows[-1]
        assert log_entry["Request type"] == "Voice"
        assert "book flights" in log_entry["User input"]
        assert log_entry["Processing Time"] == f"{timings['totalMs']:.2f}"
        assert log_entry["Language Detection"][0] == "20.00"
        assert "en" in log_entry["Language Detection"][1]

    asyncio.run(scenario())


def test_voice_endpoint_accepts_content_type_with_parameters(tmp_path):
    async def scenario() -> None:
        settings = Settings(
            voice_enabled=True,
            stt_engine="deepgram",
            deepgram_api_key="dg",
            csv_path=tmp_path / "voice-log.csv",
        )
        pipeline = StubPipeline()
        logger = StubLogger()
        stt_client = StubSTTClient()
        upload = create_upload(b"audio-bytes", content_type="video/webm;codecs=opus")

        response = await voice_endpoint(
            audio=upload,
            settings=settings,
            pipeline=pipeline,
            logger=logger,
            stt_client=stt_client,
        )

        assert response.status == "success"
        assert response.engine == "deepgram"

    asyncio.run(scenario())


def test_voice_endpoint_accepts_video_webm_content_type(tmp_path):
    async def scenario() -> None:
        settings = Settings(
            voice_enabled=True,
            stt_engine="deepgram",
            deepgram_api_key="dg",
            csv_path=tmp_path / "voice-log.csv",
        )
        pipeline = StubPipeline()
        logger = StubLogger()
        stt_client = StubSTTClient()
        upload = create_upload(b"audio-bytes", content_type="video/webm;codecs=vp8,opus")

        response = await voice_endpoint(
            audio=upload,
            settings=settings,
            pipeline=pipeline,
            logger=logger,
            stt_client=stt_client,
        )

        assert response.status == "success"
        assert response.engine == "deepgram"

    asyncio.run(scenario())
