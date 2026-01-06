from __future__ import annotations

import csv
import json
import logging
import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

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
        return cls(
            ID=str(payload.get("ID", "")),
            filterId=str(payload.get("filterId", "")),
            filterName=str(payload.get("filterName", "")),
            optionId=str(payload.get("optionId", "")),
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


def validate_headers(headers: Sequence[str]) -> List[str]:
    normalized = [h.replace("\ufeff", "") for h in headers]
    missing = [col for col in REQUIRED_COLUMNS if col not in normalized]
    if missing:
        raise InputValidationError(f"Missing required columns: {', '.join(missing)}")
    return normalized


def read_input_rows(path: Path) -> List[InputRow]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise InputValidationError("Input CSV has no headers")
        reader.fieldnames = validate_headers(reader.fieldnames)
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


def update_catalogue_synonyms(
    path: Path,
    lexicon_entries: Iterable[Mapping[str, object]],
    *,
    delimiter: str = ",",
) -> int:
    if not path.exists():
        raise FileNotFoundError(f"Catalogue file not found: {path}")
    if len(delimiter) != 1:
        raise ValueError("Catalogue delimiter must be a single character")

    synonym_index = {
        (str(entry.get("filterId")), str(entry.get("optionId"))): entry.get("synonyms", [])
        for entry in lexicon_entries
    }

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        if reader.fieldnames is None:
            raise InputValidationError("Catalogue CSV has no headers")
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    if "synonyms" not in fieldnames:
        fieldnames.append("synonyms")

    updated = 0
    for row in rows:
        key = (str(row.get("filterId", "")).strip(), str(row.get("optionId", "")).strip())
        if key not in synonym_index:
            continue
        synonyms = synonym_index[key]
        if not isinstance(synonyms, Iterable) or isinstance(synonyms, (str, bytes)):
            raise ValueError(f"Synonyms for {key} must be a list of strings")
        normalized = [str(value).strip() for value in synonyms if str(value).strip()]
        row["synonyms"] = "|".join(normalized)
        updated += 1

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)

    logger.info("Updated %s rows in catalogue %s", updated, path)
    return updated
