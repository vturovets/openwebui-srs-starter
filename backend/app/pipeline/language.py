"""Language detection utilities for the NLP pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class LanguageDetectionResult:
    """Structured result for language detection."""

    language: str
    confidence: float


class LanguageDetector:
    """Very lightweight language detector constrained to English for v1."""

    _ENGLISH_STOPWORDS = {
        "the",
        "and",
        "to",
        "for",
        "with",
        "from",
        "of",
        "in",
        "on",
        "at",
        "this",
        "that",
        "trip",
        "holiday",
        "travel",
        "looking",
        "need",
        "want",
    }

    def __init__(self, allowed_languages: Iterable[str] | None = None) -> None:
        allowed = list(allowed_languages or ["en"])
        if not allowed:
            raise ValueError("At least one language must be allowed")
        self._allowed = {code.lower() for code in allowed}

    def detect(self, text: str) -> LanguageDetectionResult:
        """Detect whether the utterance is English using simple heuristics."""

        if not isinstance(text, str) or not text.strip():
            raise ValueError("Utterance must be a non-empty string for language detection")
        lower = text.lower()
        ascii_chars = sum(1 for char in text if ord(char) < 128 and not char.isspace())
        total_chars = sum(1 for char in text if not char.isspace())
        ascii_ratio = ascii_chars / total_chars if total_chars else 0.0

        stopword_hits = sum(1 for token in re.findall(r"[a-zA-Z']+", lower) if token in self._ENGLISH_STOPWORDS)
        alphabetic_tokens = sum(1 for token in re.findall(r"[a-zA-Z']+", lower))
        stopword_ratio = stopword_hits / alphabetic_tokens if alphabetic_tokens else 0.0

        if "en" not in self._allowed:
            raise ValueError("English is not enabled in allowed languages configuration")

        # Heuristic: high ASCII ratio and at least one common English word.
        if ascii_ratio >= 0.8 and stopword_hits > 0:
            return LanguageDetectionResult(language="en", confidence=min(1.0, 0.6 + stopword_ratio))

        # If the text is overwhelmingly ASCII letters, assume English as fallback.
        if ascii_ratio >= 0.95 and alphabetic_tokens > 0:
            return LanguageDetectionResult(language="en", confidence=0.5)

        raise ValueError("Unable to confirm supported language; only English is available for v1")


__all__ = ["LanguageDetector", "LanguageDetectionResult"]
