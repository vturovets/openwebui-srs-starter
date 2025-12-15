from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Sequence
import json
import csv


@dataclass
class LexiconOption:
    filterId: str
    filterName: str
    optionId: str
    optionName: str
    synonyms: List[str] = field(default_factory=list)
    id: str | None = None

    @classmethod
    def from_dict(cls, payload: dict) -> "LexiconOption":
        required = ["filterId", "filterName", "optionId", "optionName"]
        missing = [key for key in required if not str(payload.get(key, "")).strip()]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")
        synonyms = payload.get("synonyms", []) or []
        if not isinstance(synonyms, Sequence):
            raise ValueError("synonyms must be a list of strings")
        normalized_synonyms = [str(value).strip() for value in synonyms if str(value).strip()]
        record_id = (
            str(payload.get("ID") or payload.get("id") or payload.get("optionId") or "").strip()
            or None
        )
        return cls(
            filterId=str(payload["filterId"]),
            filterName=str(payload["filterName"]),
            optionId=str(payload["optionId"]),
            optionName=str(payload["optionName"]).strip(),
            synonyms=normalized_synonyms,
            id=record_id,
        )

    def to_payload(self) -> dict:
        return {
            "filterId": self.filterId,
            "filterName": self.filterName,
            "optionId": self.optionId,
            "optionName": self.optionName,
            "synonyms": list(self.synonyms),
            **({"id": self.id} if self.id else {}),
        }

    @property
    def terms(self) -> List[str]:
        return [self.optionName] + list(self.synonyms)


class LexiconLoader:
    @staticmethod
    def load(path: Path) -> List[LexiconOption]:
        if not path.exists():
            raise FileNotFoundError(f"Lexicon file not found: {path}")
        if path.suffix.lower() == ".json":
            return LexiconLoader._load_json(path)
        if path.suffix.lower() == ".csv":
            return LexiconLoader._load_csv(path)
        raise ValueError("Unsupported lexicon format; expected .json or .csv")

    @staticmethod
    def _load_json(path: Path) -> List[LexiconOption]:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, Iterable):
            raise ValueError("Lexicon JSON must contain a list of options")
        return [LexiconOption.from_dict(entry) for entry in payload]

    @staticmethod
    def _load_csv(path: Path) -> List[LexiconOption]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ValueError("CSV lexicon missing headers")
            normalized_headers = [h.replace("\ufeff", "") for h in reader.fieldnames]
            reader.fieldnames = normalized_headers
            required = {"filterId", "filterName", "optionId", "optionName"}
            missing = required - set(normalized_headers)
            if missing:
                raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")
            options = [LexiconOption.from_dict(row) for row in reader]
        return options
