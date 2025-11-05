"""Language detection utilities for the NLP pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Sequence

try:  # pragma: no cover - exercised in integration tests
    from langdetect import DetectorFactory, LangDetectException, detect_langs
except ModuleNotFoundError:  # pragma: no cover - fallback when dependency unavailable
    DetectorFactory = None  # type: ignore[assignment]
    LangDetectException = Exception  # type: ignore[assignment]
    detect_langs = None
else:  # pragma: no cover - simple configuration
    DetectorFactory.seed = 0


_FALLBACK_STOPWORDS: dict[str, Sequence[str]] = {
    "en": (
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
        "around",
        "family",
        "book",
    ),
    "nl": (
        "de",
        "het",
        "een",
        "naar",
        "vanaf",
        "vakantie",
        "op",
        "voor",
        "nachten",
        "dagen",
        "flexibiliteit",
        "ik",
        "zoek",
        "met",
        "uit",
    ),
    "fr": (
        "je",
        "cherche",
        "des",
        "vacances",
        "pour",
        "avec",
        "jours",
        "nuits",
        "départ",
        "vers",
        "flexibilité",
        "les",
        "au",
        "de",
    ),
}


@dataclass(frozen=True)
class LanguageDetectionResult:
    """Structured result for language detection."""

    language: str
    confidence: float


class LanguageDetector:
    """Wrapper around ``langdetect`` that enforces pipeline constraints."""

    def __init__(self, allowed_languages: Iterable[str] | None = None) -> None:
        allowed = list(allowed_languages or ["en"])
        if not allowed:
            raise ValueError("At least one language must be allowed")
        self._allowed = {code.lower() for code in allowed}

        self._langdetect_available = detect_langs is not None
        self._fallback_profiles = {
            lang: set(words) for lang, words in _FALLBACK_STOPWORDS.items()
        }

    def _filter_allowed(self, candidates: List[object]) -> List[object]:
        filtered: List[object] = []
        for candidate in candidates:
            lang = getattr(candidate, "lang", "").lower()
            if lang in self._allowed:
                filtered.append(candidate)
        return filtered

    def _detect_with_langdetect(self, text: str) -> LanguageDetectionResult:
        try:
            candidates = detect_langs(text)
        except LangDetectException as exc:  # pragma: no cover - defensive branch
            raise ValueError("Unable to detect language from utterance") from exc

        allowed_candidates = self._filter_allowed(list(candidates))

        if allowed_candidates:
            best_allowed = max(allowed_candidates, key=lambda item: float(getattr(item, "prob", 0.0)))
            return LanguageDetectionResult(language=best_allowed.lang.lower(), confidence=float(best_allowed.prob))

        if candidates:
            best_overall = max(candidates, key=lambda item: float(getattr(item, "prob", 0.0)))
            raise ValueError(f"Detected language '{best_overall.lang}' is not permitted")

        raise ValueError("Language detector did not return any candidates")

    def _tokenize(self, text: str) -> List[str]:
        return [token for token in re.findall(r"[A-Za-zÀ-ÿ']+", text.lower()) if token]

    def _detect_with_fallback(self, text: str) -> LanguageDetectionResult:
        tokens = self._tokenize(text)
        if not tokens:
            raise ValueError("Unable to detect language from utterance")

        scores: dict[str, float] = {}
        for language, stopwords in self._fallback_profiles.items():
            hits = sum(1 for token in tokens if token in stopwords)
            if hits:
                scores[language] = hits / len(tokens)

        if not scores:
            alpha_chars = [char for char in text if char.isalpha()]
            ascii_chars = [char for char in alpha_chars if ord(char) < 128]
            ratio = len(ascii_chars) / len(alpha_chars) if alpha_chars else 0.0
            if "en" in self._allowed and ratio >= 0.6:
                confidence = ratio if ratio > 0 else 0.5
                return LanguageDetectionResult(language="en", confidence=confidence)
            raise ValueError("Unable to detect language from utterance")

        allowed_scores = {lang: score for lang, score in scores.items() if lang in self._allowed}
        if allowed_scores:
            total = sum(allowed_scores.values())
            best_lang, best_score = max(allowed_scores.items(), key=lambda item: item[1])
            confidence = best_score / total if total else best_score
            return LanguageDetectionResult(language=best_lang, confidence=confidence)

        best_lang, _ = max(scores.items(), key=lambda item: item[1])
        raise ValueError(f"Detected language '{best_lang}' is not permitted")

    def detect(self, text: str) -> LanguageDetectionResult:
        """Detect the utterance language using a probabilistic model."""

        if not isinstance(text, str) or not text.strip():
            raise ValueError("Utterance must be a non-empty string for language detection")
        if self._langdetect_available:
            return self._detect_with_langdetect(text)
        return self._detect_with_fallback(text)


__all__ = ["LanguageDetector", "LanguageDetectionResult"]
