from __future__ import annotations

import csv
import json
import logging
import os
from dataclasses import dataclass
import re
from hashlib import sha256
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ["ID", "filterId", "filterName", "optionId", "optionName"]


@dataclass
class InputRow:
    ID: str
    filterId: str
    filterName: str
    optionId: str
    optionName: str

    @classmethod
    def from_dict(cls, payload: Dict[str, str]) -> "InputRow":
        def _fallback_filter_id(filter_id: str, filter_name: str) -> str:
            if filter_id.strip():
                return filter_id.strip()

            normalized = re.sub(r"[^A-Za-z0-9]+", "_", filter_name).strip("_")
            if normalized:
                derived = normalized.upper()
                logger.warning(
                    "filterId missing for '%s', derived fallback '%s'", filter_name, derived
                )
                return derived
            return ""

        filter_name = str(payload.get("filterName", "")).strip()
        filter_id = _fallback_filter_id(str(payload.get("filterId", "")), filter_name)
        return cls(
            ID=str(payload.get("ID", "")).strip(),
            filterId=filter_id,
            filterName=filter_name,
            optionId=str(payload.get("optionId", "")).strip(),
            optionName=str(payload.get("optionName", "")).strip(),
        )

    def to_payload(self) -> Dict[str, str]:
        return {
            "ID": self.ID,
            "filterId": self.filterId,
            "filterName": self.filterName,
            "optionId": self.optionId,
            "optionName": self.optionName,
        }


class InputValidationError(Exception):
    pass


def validate_headers(headers: Sequence[str]) -> None:
    normalized = [h.replace("\ufeff", "") for h in headers]
    missing = [col for col in REQUIRED_COLUMNS if col not in normalized]
    if missing:
        raise InputValidationError(f"Missing required columns: {', '.join(missing)}")


def read_input_rows(path: Path) -> List[InputRow]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise InputValidationError("Input CSV has no headers")
        validate_headers(reader.fieldnames)
        rows = [InputRow.from_dict(row) for row in reader]
    logger.info("Loaded %s rows from %s", len(rows), path)
    return rows


def chunk_rows(rows: Sequence[InputRow], batch_size: int) -> Iterable[List[InputRow]]:
    for idx in range(0, len(rows), batch_size):
        yield list(rows[idx : idx + batch_size])


def load_existing_output(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_output(path: Path, data: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    logger.info("Wrote %s records to %s", len(data), path)


def write_metadata(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def compute_file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_processed_index(existing: List[Dict[str, str]]) -> Dict[Tuple[str, str], Dict[str, str]]:
    index: Dict[Tuple[str, str], Dict[str, str]] = {}
    for row in existing:
        index[(str(row.get("filterId")), str(row.get("optionId")))] = row
    return index
