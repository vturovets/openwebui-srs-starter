import asyncio
from collections.abc import AsyncIterator, Iterable

import pytest

import backend.app.integrations.stt as stt


class _DummyWord:
    def __init__(self, word: str, start: float, end: float) -> None:
        self.word = word
        self.start = start
        self.end = end


class _DummySegment:
    def __init__(self, text: str, words: Iterable[_DummyWord] | None) -> None:
        self.text = text
        self.words = list(words or [])


class _RecordingModel:
    """Simple stand-in for ``faster_whisper.WhisperModel`` used in tests."""

    def __init__(
        self,
        model_size_or_path: str,
        device: str,
        compute_type: str,
        download_root: str | None = None,
    ) -> None:
        self.device = device
        self.compute_type = compute_type
        self.calls: list[tuple[str, int, bool]] = []

    def transcribe(self, path: str, *, beam_size: int, word_timestamps: bool):
        self.calls.append((path, beam_size, word_timestamps))
        with open(path, "rb") as handle:
            payload = handle.read()
        segments = [
            _DummySegment(" hello", [_DummyWord("hello", 0.0, 0.4)]),
            _DummySegment(" world", [_DummyWord("world", 0.4, 0.9)]),
        ]
        info = {"payload_length": len(payload)}
        return segments, info


def test_faster_whisper_transcribes_async_stream(monkeypatch) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(stt, "WhisperModel", _RecordingModel)
        client = stt.FasterWhisperSpeechToTextClient(
            model="tiny",
            device="cpu",
            compute_type="default",
            cache_dir=None,
            voice_max_bytes=32,
            beam_size=7,
        )

        async def stream() -> AsyncIterator[bytes]:
            yield b"abc"
            yield b"def"

        result = await client.transcribe(
            content_type="video/webm;codecs=opus",
            stream=stream(),
        )

        assert result.text == "hello world"
        assert [(w.word, w.start, w.end) for w in result.words] == [
            ("hello", 0.0, 0.4),
            ("world", 0.4, 0.9),
        ]
        recording = client._model.calls  # type: ignore[attr-defined]
        assert recording
        recorded_path, recorded_beam, recorded_word_flag = recording[-1]
        assert recorded_path.endswith(".webm")
        assert recorded_beam == 7
        assert recorded_word_flag is True

    asyncio.run(scenario())


def test_faster_whisper_accepts_sync_iterable(monkeypatch) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(stt, "WhisperModel", _RecordingModel)
        client = stt.FasterWhisperSpeechToTextClient(
            model="tiny",
            device="cpu",
            compute_type="default",
            cache_dir=None,
            voice_max_bytes=64,
        )

        result = await client.transcribe(
            content_type="audio/mpeg",
            stream=[b"payload"],
        )

        assert result.text == "hello world"
        assert len(result.words) == 2
        recorded_path, *_ = client._model.calls[-1]  # type: ignore[attr-defined]
        assert recorded_path.endswith(".mp3")

    asyncio.run(scenario())


def test_faster_whisper_enforces_voice_limit(monkeypatch) -> None:
    async def scenario() -> None:
        invoked = False

        class _FailingModel(_RecordingModel):
            def transcribe(self, path: str, *, beam_size: int, word_timestamps: bool):
                nonlocal invoked
                invoked = True
                return super().transcribe(
                    path,
                    beam_size=beam_size,
                    word_timestamps=word_timestamps,
                )

        monkeypatch.setattr(stt, "WhisperModel", _FailingModel)
        client = stt.FasterWhisperSpeechToTextClient(
            model="tiny",
            device="cpu",
            compute_type="default",
            cache_dir=None,
            voice_max_bytes=4,
        )

        async def stream() -> AsyncIterator[bytes]:
            yield b"abcd"
            yield b"ef"

        with pytest.raises(stt.SpeechToTextError):
            await client.transcribe(content_type="audio/wav", stream=stream())

        assert invoked is False

    asyncio.run(scenario())


def test_faster_whisper_falls_back_to_cpu(monkeypatch, caplog) -> None:
    async def scenario() -> None:
        attempts: list[tuple[str, str]] = []

        class _FallbackModel(_RecordingModel):
            def __init__(
                self,
                model_size_or_path: str,
                device: str,
                compute_type: str,
                download_root: str | None = None,
            ) -> None:
                attempts.append((device, compute_type))
                if device != "cpu":
                    raise RuntimeError("Could not locate cudnn_ops64_9.dll")
                super().__init__(
                    model_size_or_path=model_size_or_path,
                    device=device,
                    compute_type=compute_type,
                    download_root=download_root,
                )

        monkeypatch.setattr(stt, "WhisperModel", _FallbackModel)

        with caplog.at_level("WARNING"):
            client = stt.FasterWhisperSpeechToTextClient(
                model="tiny",
                device="cuda",
                compute_type="default",
                cache_dir=None,
                voice_max_bytes=32,
            )

        async def stream() -> AsyncIterator[bytes]:
            yield b"audio"

        result = await client.transcribe(
            content_type="audio/wav",
            stream=stream(),
        )

        assert result.text == "hello world"
        assert attempts == [("cuda", "default"), ("cpu", "int8")]
        assert any(
            "falling back to cpu" in record.getMessage().lower() for record in caplog.records
        )

    asyncio.run(scenario())


def test_auto_device_prefers_cpu_when_cuda_missing(monkeypatch) -> None:
    async def scenario() -> None:
        class _CpuOnlyCTranslate2:
            @staticmethod
            def get_supported_devices():
                return ["cpu"]

        monkeypatch.setattr(stt, "ctranslate2", _CpuOnlyCTranslate2, raising=False)
        monkeypatch.setattr(stt, "WhisperModel", _RecordingModel)

        client = stt.FasterWhisperSpeechToTextClient(
            model="tiny",
            device="auto",
            compute_type="float16",
            cache_dir=None,
            voice_max_bytes=32,
        )

        assert client._model.device == "cpu"  # type: ignore[attr-defined]
        assert client._model.compute_type == "int8"  # type: ignore[attr-defined]

    asyncio.run(scenario())
