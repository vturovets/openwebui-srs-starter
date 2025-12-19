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
            method_requested="rules-basic",
            method_used="rules-basic",
            detection=detection,
            extraction=None,
            normalized=normalized,
            validation={"status": "passed", "errors": []},
            metadata={
                "defaultMethod": "rules-basic",
                "availableMethods": [],
            },
            attempts=[],
            timings=dict(self.timings),
            error=None,
        )


class StubSTTClient:
    def __init__(
        self,
        transcript: str = "turn voice into text",
        duration_ms: float = 80.0,
        word_timings: list[tuple[float, float]] | None = None,
    ) -> None:
        self.transcript = transcript
        self.duration_ms = duration_ms
        self.word_timings = word_timings
        self.seen_content_types: list[str] = []
        self.payloads: list[bytes] = []

    async def transcribe(self, *, content_type: str, stream):
        self.seen_content_types.append(content_type)
        collected = bytearray()

        async for chunk in stream:
            collected.extend(chunk)

        # Emulate provider latency by sleeping for the configured duration
        await asyncio.sleep(self.duration_ms / 1000.0)

        self.payloads.append(bytes(collected))

        transcript_words = self.transcript.split()
        if self.word_timings is None:
            total_duration_s = self.duration_ms / 1000.0
            count = len(transcript_words)
            if count:
                step = total_duration_s / count
                timings: list[tuple[float, float]] = []
                start = 0.0
                for _ in range(count):
                    end = start + step
                    timings.append((start, end))
                    start = end
            else:
                timings = []
        else:
            timings = list(self.word_timings)

        words = [
            TranscribedWord(word=part, start=start, end=end)
            for part, (start, end) in zip(transcript_words, timings)
        ]
        return TranscriptionResult(text=self.transcript, words=words)


def create_upload(
    content: bytes,
    *,
    content_type: str | None = "audio/wav",
    filename: str = "audio.wav",
) -> UploadFile:
    headers = Headers({"content-type": content_type}) if content_type is not None else Headers()
    return UploadFile(file=BytesIO(content), filename=filename, headers=headers)


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

        if response.words:
            first_word = response.words[0]
            last_word = response.words[-1]
            word_span_ms = (last_word.end - first_word.start) * 1000
        else:
            word_span_ms = 0.0

        minimum_expected = max(stt_client.duration_ms, word_span_ms)
        assert timings["sttMs"] >= minimum_expected
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


def test_voice_endpoint_can_return_transcript_only(tmp_path):
    async def scenario() -> None:
        settings = Settings(
            voice_enabled=True,
            stt_engine="deepgram",
            deepgram_api_key="dg",
            voice_max_bytes=1024,
            csv_path=tmp_path / "voice-log.csv",
        )
        pipeline = StubPipeline()
        logger = StubLogger()
        stt_client = StubSTTClient(transcript="only transcribe", duration_ms=25.0)
        upload = create_upload(b"audio-bytes", content_type="audio/wav")

        response = await voice_endpoint(
            audio=upload,
            transcript_only=True,
            settings=settings,
            pipeline=pipeline,
            logger=logger,
            stt_client=stt_client,
        )

        assert response.status_code == 200
        assert response.media_type == "text/plain"
        assert response.body.decode("utf-8") == "only transcribe"
        assert pipeline.invocations == []

        assert logger.rows
        log_entry = logger.rows[-1]
        assert log_entry["Request type"] == "Voice"
        assert log_entry["Pipeline Status"] == "Transcribed"

    asyncio.run(scenario())


def test_voice_endpoint_uses_word_timing_guard(tmp_path):
    async def scenario() -> None:
        settings = Settings(
            voice_enabled=True,
            stt_engine="deepgram",
            deepgram_api_key="dg",
            voice_max_bytes=1024,
            csv_path=tmp_path / "voice-log.csv",
        )
        pipeline = StubPipeline()
        logger = StubLogger()
        stretched_word_timings = [(0.0, 0.05), (0.05, 0.1), (0.1, 0.15)]
        stt_client = StubSTTClient(
            transcript="timed words example",
            duration_ms=30.0,
            word_timings=stretched_word_timings,
        )
        upload = create_upload(b"audio", content_type="audio/wav")

        response = await voice_endpoint(
            audio=upload,
            settings=settings,
            pipeline=pipeline,
            logger=logger,
            stt_client=stt_client,
        )

        assert response.words
        first_word = response.words[0]
        last_word = response.words[-1]
        word_span_ms = (last_word.end - first_word.start) * 1000

        timings = response.metadata["timings"]
        assert timings["sttMs"] >= stt_client.duration_ms
        assert timings["sttMs"] == pytest.approx(word_span_ms, abs=1e-6)

    asyncio.run(scenario())


def test_voice_endpoint_rejects_generic_octet_stream_without_hint():
    async def scenario() -> None:
        settings = Settings(voice_enabled=True, stt_engine="deepgram", deepgram_api_key="dg")
        upload = create_upload(
            b"audio-bytes",
            content_type="application/octet-stream",
            filename="recording",
        )

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

        assert excinfo.value.status_code == 415
        assert "Unsupported audio format" in str(excinfo.value)

    asyncio.run(scenario())


def test_voice_endpoint_handles_streams_without_seek(tmp_path):
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
        audio_bytes = b"RIFF" + b"\x00" * 4 + b"WAVEfmt "
        upload = create_upload(audio_bytes, content_type=None, filename="recording")

        async def failing_seek(offset: int, whence: int = 0) -> None:
            raise OSError("seek unsupported")

        upload.seek = failing_seek  # type: ignore[assignment]

        response = await voice_endpoint(
            audio=upload,
            settings=settings,
            pipeline=pipeline,
            logger=logger,
            stt_client=stt_client,
        )

        assert response.status == "success"
        assert stt_client.payloads[-1] == audio_bytes

    asyncio.run(scenario())
