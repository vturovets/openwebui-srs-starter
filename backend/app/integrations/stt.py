"""Speech-to-text client abstractions used by the voice endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Iterable, Protocol

try:  # pragma: no cover - exercised in integration scenarios
    import httpx
except ModuleNotFoundError:  # pragma: no cover - handled at runtime if missing
    httpx = None  # type: ignore[assignment]


class SpeechToTextError(RuntimeError):
    """Raised when a speech-to-text provider returns an error."""


@dataclass(slots=True)
class TranscribedWord:
    """Individual word timing returned by the STT provider."""

    word: str
    start: float
    end: float


@dataclass(slots=True)
class TranscriptionResult:
    """Structured transcription payload returned by a client."""

    text: str
    words: list[TranscribedWord]


class SpeechToTextClient(Protocol):
    """Protocol implemented by STT clients."""

    async def transcribe(
        self,
        *,
        content_type: str,
        stream: AsyncIterator[bytes] | Iterable[bytes],
    ) -> TranscriptionResult:
        """Stream audio bytes to the provider and return a transcript."""


class DeepgramSpeechToTextClient:
    """Minimal Deepgram client that streams audio to the REST API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "nova-2-general",
        base_url: str = "https://api.deepgram.com/v1/listen",
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("A Deepgram API key is required")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._timeout = timeout

    async def transcribe(
        self,
        *,
        content_type: str,
        stream: AsyncIterator[bytes] | Iterable[bytes],
    ) -> TranscriptionResult:
        if httpx is None:  # pragma: no cover - requires optional dependency
            raise SpeechToTextError("httpx must be installed to use the Deepgram STT client")

        headers = {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": content_type,
        }
        params = {"model": self._model, "smart_format": "true"}

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                self._base_url,
                headers=headers,
                params=params,
                content=stream,
            )

        if response.status_code >= 400:
            detail = response.text
            raise SpeechToTextError(
                f"Deepgram transcription failed with status {response.status_code}: {detail}",
            )

        payload = response.json()
        transcript, words = self._parse_payload(payload)
        return TranscriptionResult(text=transcript, words=words)

    def _parse_payload(self, payload: object) -> tuple[str, list[TranscribedWord]]:
        if not isinstance(payload, dict):
            raise SpeechToTextError("Unexpected Deepgram response format")

        try:
            channels = payload["results"]["channels"]
            first_channel = channels[0]
            alternative = first_channel["alternatives"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise SpeechToTextError("Deepgram response missing transcript data") from exc

        transcript = str(alternative.get("transcript", "")).strip()
        words_payload = alternative.get("words", [])

        words: list[TranscribedWord] = []
        if isinstance(words_payload, list):
            for item in words_payload:
                if not isinstance(item, dict):
                    continue
                word_text = str(item.get("word") or item.get("punctuated_word") or "").strip()
                if not word_text:
                    continue
                try:
                    start = float(item.get("start", 0.0))
                    end = float(item.get("end", start))
                except (TypeError, ValueError):
                    start, end = 0.0, 0.0
                words.append(TranscribedWord(word=word_text, start=start, end=end))

        return transcript, words


__all__ = [
    "DeepgramSpeechToTextClient",
    "SpeechToTextClient",
    "SpeechToTextError",
    "TranscribedWord",
    "TranscriptionResult",
]

