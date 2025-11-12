"""Speech-to-text client abstractions used by the voice endpoint."""

from __future__ import annotations

import io
import logging
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Iterable, Protocol

import anyio

try:  # pragma: no cover - exercised in integration scenarios
    import httpx
except ModuleNotFoundError:  # pragma: no cover - handled at runtime if missing
    httpx = None  # type: ignore[assignment]

try:  # pragma: no cover - exercised in integration scenarios
    from faster_whisper import WhisperModel
except ModuleNotFoundError:  # pragma: no cover - handled at runtime if missing
    WhisperModel = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)

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


class FasterWhisperSpeechToTextClient:
    """Transcribe audio locally using ``faster-whisper``.

    This client buffers the incoming audio stream into memory while enforcing the
    ``voice_max_bytes`` limit that the API layer already validates. Transcription is
    executed in a worker thread so that FastAPI handlers remain responsive. The
    ``faster-whisper`` runtime relies on ``ffmpeg`` being available on ``PATH`` to
    decode common audio formats.
    """

    def __init__(
        self,
        *,
        model: str,
        device: str,
        compute_type: str,
        cache_dir: Path | str | None,
        voice_max_bytes: int,
        beam_size: int = 5,
    ) -> None:
        if WhisperModel is None:  # pragma: no cover - requires optional dependency
            raise RuntimeError(
                "faster-whisper must be installed to use the fallback STT engine",
            )

        download_root = str(cache_dir) if cache_dir is not None else None
        self._model = self._initialise_model(
            model=model,
            device=device,
            compute_type=compute_type,
            download_root=download_root,
        )
        self._voice_max_bytes = max(int(voice_max_bytes), 0)
        self._beam_size = beam_size

    async def transcribe(
        self,
        *,
        content_type: str,
        stream: AsyncIterator[bytes] | Iterable[bytes],
    ) -> TranscriptionResult:
        buffer = io.BytesIO()
        remaining = self._voice_max_bytes

        async def _consume_async(iterator: AsyncIterator[bytes]) -> None:
            nonlocal remaining
            async for chunk in iterator:
                if not chunk:
                    continue
                remaining -= len(chunk)
                if remaining < 0:
                    raise SpeechToTextError("Audio payload exceeds maximum allowed size")
                buffer.write(bytes(chunk))

        def _consume_sync(iterator: Iterable[bytes]) -> None:
            nonlocal remaining
            for chunk in iterator:
                if not chunk:
                    continue
                remaining -= len(chunk)
                if remaining < 0:
                    raise SpeechToTextError("Audio payload exceeds maximum allowed size")
                buffer.write(bytes(chunk))

        if hasattr(stream, "__aiter__"):
            await _consume_async(stream)  # type: ignore[arg-type]
        else:
            _consume_sync(stream)

        size = buffer.tell()
        if size <= 0:
            raise SpeechToTextError("Audio stream was empty")

        buffer.seek(0)
        audio_bytes = buffer.read()
        suffix = self._suffix_from_content_type(content_type)

        try:
            transcript_text, words = await anyio.to_thread.run_sync(
                self._run_transcription,
                audio_bytes,
                suffix,
            )
        except Exception as exc:  # pragma: no cover - depends on optional dependency
            raise SpeechToTextError("Failed to transcribe audio using faster-whisper") from exc
        finally:
            buffer.close()
        return TranscriptionResult(text=transcript_text, words=words)

    def _initialise_model(
        self,
        *,
        model: str,
        device: str,
        compute_type: str,
        download_root: str | None,
    ) -> WhisperModel:
        try:
            return WhisperModel(
                model_size_or_path=model,
                device=device,
                compute_type=compute_type,
                download_root=download_root,
            )
        except Exception as exc:  # pragma: no cover - depends on optional dependency
            fallback = self._cpu_fallback(device=device, compute_type=compute_type, exc=exc)
            if fallback is None:
                raise
            fallback_device, fallback_compute_type = fallback
            logger.warning(
                "Failed to load faster-whisper on device '%s' (%s); falling back to CPU",
                device,
                exc,
            )
            return WhisperModel(
                model_size_or_path=model,
                device=fallback_device,
                compute_type=fallback_compute_type,
                download_root=download_root,
            )

    def _cpu_fallback(
        self,
        *,
        device: str,
        compute_type: str,
        exc: Exception,
    ) -> tuple[str, str] | None:
        if device.strip().lower() == "cpu":
            return None

        message = str(exc).lower()
        trigger_tokens = ("cudnn", "cublas", "cuda")
        if not any(token in message for token in trigger_tokens):
            return None

        fallback_compute_type = self._cpu_compute_type(compute_type)
        return "cpu", fallback_compute_type

    @staticmethod
    def _cpu_compute_type(configured: str) -> str:
        normalized = configured.strip().lower()
        if normalized in {"", "default", "auto"}:
            return "int8"
        if "float16" in normalized or "fp16" in normalized:
            return "int8"
        return configured

    def _suffix_from_content_type(self, content_type: str) -> str:
        normalized = content_type.split(";", 1)[0].strip().lower()
        return {
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
            "audio/mpeg": ".mp3",
            "audio/mp3": ".mp3",
            "audio/ogg": ".ogg",
            "audio/webm": ".webm",
            "video/webm": ".webm",
            "audio/flac": ".flac",
        }.get(normalized, ".tmp")

    def _run_transcription(self, audio_bytes: bytes, suffix: str) -> tuple[str, list[TranscribedWord]]:
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = Path(tmp.name)

            segments, _info = self._model.transcribe(  # type: ignore[operator]
                str(tmp_path),
                beam_size=self._beam_size,
                word_timestamps=True,
            )
        finally:
            if tmp_path is not None:
                with suppress(Exception):
                    tmp_path.unlink(missing_ok=True)

        transcript_parts: list[str] = []
        words: list[TranscribedWord] = []

        for segment in segments:
            text = str(getattr(segment, "text", ""))
            if text:
                transcript_parts.append(text)

            segment_words = getattr(segment, "words", None)
            if segment_words is None:
                continue
            for item in segment_words:
                word_text = str(getattr(item, "word", "")).strip()
                if not word_text:
                    continue
                start = getattr(item, "start", 0.0)
                end = getattr(item, "end", start)
                try:
                    start_f = float(start)
                except (TypeError, ValueError):
                    start_f = 0.0
                try:
                    end_f = float(end)
                except (TypeError, ValueError):
                    end_f = start_f
                words.append(TranscribedWord(word=word_text, start=start_f, end=end_f))

        transcript_text = "".join(transcript_parts).strip()
        return transcript_text, words


__all__ = [
    "DeepgramSpeechToTextClient",
    "FasterWhisperSpeechToTextClient",
    "SpeechToTextClient",
    "SpeechToTextError",
    "TranscribedWord",
    "TranscriptionResult",
]

