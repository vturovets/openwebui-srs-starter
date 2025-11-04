"""CSV logging utility for parse pipeline instrumentation."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, MutableMapping, Sequence


def _serialise_value(value: object) -> str:
    """Serialise complex values for CSV output while preserving readability."""

    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


@dataclass(slots=True)
class CSVLogger:
    """Append structured rows to a UTF-8 CSV file with a stable header."""

    path: Path
    fieldnames: Sequence[str]

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self._fieldnames = list(self.fieldnames)

    def log(self, payload: Mapping[str, object]) -> None:
        """Append a log entry ensuring headers exist and directories are created."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        file_exists = self.path.exists()
        write_header = False
        if not file_exists:
            write_header = True
        else:
            try:
                write_header = self.path.stat().st_size == 0
            except OSError:
                write_header = True

        row: MutableMapping[str, str] = {}
        for name in self._fieldnames:
            row[name] = _serialise_value(payload.get(name))

        with self.path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self._fieldnames, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerow(row)


__all__ = ["CSVLogger"]
