from __future__ import annotations

import logging
import re
from typing import Dict, Iterable, List, Tuple

from .schema import validate_response_item

logger = logging.getLogger(__name__)

CODE_FILTER_IDS = {"DEPARTUREAIRPORTS", "CARRIER"}
CODE_WHITELIST = {"AI", "HB", "BB", "RO"}
CODE_PATTERN = re.compile(r"\b[A-Z]{2,4}\b")


class ResponseValidationError(Exception):
    pass


def _contains_suspicious_code(text: str) -> bool:
    tokens = CODE_PATTERN.findall(text)
    return any(token.upper() not in CODE_WHITELIST for token in tokens)


def sanitize_synonyms(
    filter_id: str, synonyms: Iterable[str], max_synonyms: int
) -> Tuple[List[str], Dict[str, int]]:
    cleaned: List[str] = []
    removals = {"duplicates": 0, "codes": 0, "empties": 0}
    seen = set()
    for synonym in synonyms:
        if synonym is None:
            removals["empties"] += 1
            continue
        trimmed = synonym.strip()
        if not trimmed:
            removals["empties"] += 1
            continue
        if filter_id in CODE_FILTER_IDS and _contains_suspicious_code(trimmed):
            removals["codes"] += 1
            continue
        normalized = trimmed.lower()
        if normalized in seen:
            removals["duplicates"] += 1
            continue
        seen.add(normalized)
        cleaned.append(normalized)
        if len(cleaned) >= max_synonyms:
            break
    return cleaned, removals


def enforce_schema(response: Dict[str, object]) -> List[Dict[str, object]]:
    if not isinstance(response, dict):
        raise ResponseValidationError("Response must be an object with a 'results' array")

    results = response.get("results")
    if not isinstance(results, list):
        raise ResponseValidationError("'results' must be a list")

    errors: List[str] = []
    for idx, item in enumerate(results):
        if not isinstance(item, dict):
            errors.append(f"Item {idx}: Expected object, got {type(item).__name__}")
            continue
        item_errors = validate_response_item(item)
        if item_errors:
            errors.append(f"Item {idx}: {', '.join(item_errors)}")

    if errors:
        raise ResponseValidationError("; ".join(errors))

    return results
