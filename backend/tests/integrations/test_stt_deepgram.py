import array
import asyncio
import io
import json
import math
import wave
from types import SimpleNamespace

import backend.app.integrations.stt as stt


class _StubResponse:
    def __init__(self, *, status_code: int, payload: dict[str, object]):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict[str, object]:
        return self._payload


def _sine_wave_wav_bytes(
    *,
    duration_seconds: float = 0.5,
    frequency_hz: float = 440.0,
    sample_rate: int = 16000,
) -> bytes:
    """Generate a mono WAV containing a simple sine wave."""

    frame_count = int(duration_seconds * sample_rate)
    amplitude = 32767
    samples = array.array(
        "h",
        (
            int(amplitude * math.sin(2 * math.pi * frequency_hz * index / sample_rate))
            for index in range(frame_count)
        ),
    )

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(samples.tobytes())

    return buffer.getvalue()


async def _collect_stream(stream) -> bytes:
    chunks: list[bytes] = []
    if hasattr(stream, "__aiter__"):
        async for chunk in stream:
            if chunk:
                chunks.append(bytes(chunk))
    else:
        for chunk in stream:
            if chunk:
                chunks.append(bytes(chunk))
    return b"".join(chunks)


class _RecordingAsyncClient:
    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout
        self.requests: list[dict[str, object]] = []

    async def __aenter__(self) -> "_RecordingAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, url: str, *, headers: dict[str, str], params: dict[str, str], content) -> _StubResponse:
        body = await _collect_stream(content)
        self.requests.append(
            {
                "url": url,
                "headers": headers,
                "params": params,
                "body": body,
            }
        )
        payload = {
            "results": {
                "channels": [
                    {
                        "alternatives": [
                            {
                                "transcript": "hello world",
                                "words": [
                                    {"word": "hello", "start": 0.0, "end": 0.48},
                                    {
                                        "punctuated_word": "world",
                                        "start": 0.48,
                                        "end": 0.96,
                                    },
                                ],
                            }
                        ]
                    }
                ]
            }
        }
        return _StubResponse(status_code=200, payload=payload)


class _AsyncClientFactory:
    def __init__(self) -> None:
        self.instances: list[_RecordingAsyncClient] = []

    def __call__(self, *, timeout: float) -> _RecordingAsyncClient:
        client = _RecordingAsyncClient(timeout=timeout)
        self.instances.append(client)
        return client


def test_deepgram_client_streams_audio_and_parses_transcript(monkeypatch) -> None:
    audio_bytes = _sine_wave_wav_bytes()

    factory = _AsyncClientFactory()
    monkeypatch.setattr(stt, "httpx", SimpleNamespace(AsyncClient=factory))

    async def scenario() -> None:
        client = stt.DeepgramSpeechToTextClient(api_key="dg-key", model="nova-lite", timeout=15.0)

        async def stream():
            chunk = 512
            for index in range(0, len(audio_bytes), chunk):
                yield audio_bytes[index : index + chunk]

        result = await client.transcribe(content_type="audio/wav", stream=stream())

        assert result.text == "hello world"
        assert [(word.word, word.start, word.end) for word in result.words] == [
            ("hello", 0.0, 0.48),
            ("world", 0.48, 0.96),
        ]

    asyncio.run(scenario())

    assert factory.instances, "the httpx.AsyncClient stub should be instantiated"
    recorded_client = factory.instances[-1]
    assert recorded_client.requests, "the stub client should record at least one request"
    request = recorded_client.requests[-1]
    assert request["headers"]["Content-Type"] == "audio/wav"
    assert request["params"]["model"] == "nova-lite"
    assert request["body"] == audio_bytes
