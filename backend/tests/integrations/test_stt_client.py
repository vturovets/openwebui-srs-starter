import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.integrations import stt


class DummyWord:
    def __init__(self, word: str, start: float, end: float) -> None:
        self.word = word
        self.start = start
        self.end = end


class DummySegment:
    def __init__(self, text: str, words: list[DummyWord]) -> None:
        self.text = text
        self.words = words


class DummyModel:
    def __init__(self, model_size: str, **kwargs) -> None:
        self.model_size = model_size
        self.kwargs = kwargs
        DummyModel.instances.append(self)

    def transcribe(self, path: str, **kwargs):
        DummyModel.last_invocation = {"path": path, "kwargs": kwargs}
        with open(path, "rb") as handle:
            DummyModel.captured_bytes = handle.read()
        segments = [
            DummySegment(" Hello", [DummyWord("Hello", 0.0, 0.5)]),
            DummySegment("world", [DummyWord("world", 0.5, 1.0)]),
        ]
        return iter(segments), SimpleNamespace()


DummyModel.instances: list[DummyModel] = []
DummyModel.last_invocation: dict[str, object] = {}
DummyModel.captured_bytes: bytes = b""


async def _async_bytes_stream(chunks: list[bytes]):
    for chunk in chunks:
        await asyncio.sleep(0)
        yield chunk


def test_faster_whisper_transcribe_collects_stream(monkeypatch, tmp_path):
    monkeypatch.setattr(stt, "WhisperModel", DummyModel)
    DummyModel.instances.clear()
    DummyModel.last_invocation = {}
    DummyModel.captured_bytes = b""

    async def _run() -> stt.TranscriptionResult:
        client = stt.FasterWhisperSpeechToTextClient(
            model_size="tiny",
            device="cpu",
            compute_type="int8",
            download_root=tmp_path,
            beam_size=1,
            vad_filter=False,
        )

        audio_chunks = [b"abc", b"def"]
        return await client.transcribe(
            content_type="audio/wav",
            stream=_async_bytes_stream(audio_chunks),
        )

    result = asyncio.run(_run())

    assert result.text == "Hello world"
    assert [(word.word, word.start, word.end) for word in result.words] == [
        ("Hello", 0.0, 0.5),
        ("world", 0.5, 1.0),
    ]

    assert DummyModel.captured_bytes == b"abcdef"
    assert DummyModel.instances[0].model_size == "tiny"
    assert DummyModel.instances[0].kwargs["compute_type"] == "int8"
    assert DummyModel.instances[0].kwargs["device"] == "cpu"
    assert DummyModel.instances[0].kwargs["download_root"] == str(tmp_path)

    invocation = DummyModel.last_invocation
    assert invocation["kwargs"]["beam_size"] == 1
    assert invocation["kwargs"]["vad_filter"] is False
    assert invocation["kwargs"]["word_timestamps"] is True
    assert not Path(invocation["path"]).exists()


def test_faster_whisper_requires_dependency(monkeypatch):
    monkeypatch.setattr(stt, "WhisperModel", None)

    with pytest.raises(stt.SpeechToTextError):
        stt.FasterWhisperSpeechToTextClient()
