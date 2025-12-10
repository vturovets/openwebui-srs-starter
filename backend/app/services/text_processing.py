"""Text preprocessing and negation handling utilities."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence, Tuple


@dataclass(frozen=True)
class PreprocessResult:
    """Result container for normalized text and generated n-grams."""

    cleaned_text: str
    tokens: Tuple[str, ...]
    ngrams: Tuple[str, ...]


@dataclass(frozen=True)
class NegationSpan:
    """Span of text where a negation cue was detected."""

    phrase: str
    start: int
    end: int
    replacement: str | None = None


class TextPreprocessor:
    """Normalize free text and generate n-grams for downstream matching."""

    _DEFAULT_NORMALIZE_PATTERN = re.compile(r"[^\w\s]+")

    def __init__(
        self,
        *,
        normalizer: Callable[[str], str] | None = None,
        max_ngram: int = 3,
        lemmatizer: Callable[[str], str] | None = None,
    ) -> None:
        if max_ngram < 1:
            raise ValueError("max_ngram must be at least 1")
        self._max_ngram = max_ngram
        self._normalizer = normalizer or self._default_normalizer
        self._lemmatizer = lemmatizer

    def _default_normalizer(self, text: str) -> str:
        normalized = self._DEFAULT_NORMALIZE_PATTERN.sub(" ", text.lower())
        return " ".join(normalized.split())

    def preprocess(self, text: str) -> PreprocessResult:
        cleaned = self._normalizer(text)
        tokens = cleaned.split()
        if self._lemmatizer:
            tokens = [self._lemmatizer(token) for token in tokens]
        ngrams = self._build_ngrams(tokens)
        return PreprocessResult(cleaned_text=cleaned, tokens=tuple(tokens), ngrams=ngrams)

    def _build_ngrams(self, tokens: Sequence[str]) -> Tuple[str, ...]:
        phrases: list[str] = []
        limit = min(len(tokens), self._max_ngram)
        for size in range(1, limit + 1):
            for idx in range(len(tokens) - size + 1):
                phrases.append(" ".join(tokens[idx : idx + size]))
        return tuple(phrases)


class NegationHandler:
    """Detect negation cues and map them to positive alternatives."""

    _NEGATION_PATTERN = re.compile(
        r"\b(no|not|without|don['’]?t)\s+(?P<phrase>[\w\s]{1,80}?)(?=(?:,|;|\.|\band\b|\bbut\b|$))",
        flags=re.IGNORECASE,
    )

    def __init__(self, alternatives: Mapping[str, str] | None = None) -> None:
        defaults = {"catering": "room only"}
        if alternatives:
            defaults.update({key.lower(): value for key, value in alternatives.items() if value})
        self._alternatives = defaults

    def detect(self, text: str) -> Tuple[NegationSpan, ...]:
        spans: list[NegationSpan] = []
        for match in self._NEGATION_PATTERN.finditer(text):
            phrase = (match.group("phrase") or "").strip()
            spans.append(
                NegationSpan(
                    phrase=phrase,
                    start=match.start(),
                    end=match.end(),
                    replacement=self._find_replacement(phrase),
                )
            )
        return tuple(spans)

    def apply(self, text: str, *, normalizer: Callable[[str], str] | None = None) -> tuple[str, Tuple[NegationSpan, ...]]:
        spans = self.detect(text)
        if not spans:
            cleaned = normalizer(text) if normalizer else text
            return cleaned, spans

        pieces: list[str] = []
        cursor = 0
        for span in spans:
            pieces.append(text[cursor : span.start])
            replacement = span.replacement if span.replacement is not None else span.phrase
            matched_text = text[span.start : span.end]
            if matched_text.endswith(" ") and not replacement.endswith(" "):
                replacement = replacement + " "
            pieces.append(replacement)
            cursor = span.end
        pieces.append(text[cursor:])
        replaced = "".join(pieces)
        cleaned = normalizer(replaced) if normalizer else replaced
        return cleaned, spans

    def _find_replacement(self, phrase: str) -> str | None:
        lowered = phrase.lower()
        for keyword, replacement in self._alternatives.items():
            if keyword in lowered:
                return replacement
        return None


__all__ = [
    "NegationHandler",
    "NegationSpan",
    "PreprocessResult",
    "TextPreprocessor",
]
