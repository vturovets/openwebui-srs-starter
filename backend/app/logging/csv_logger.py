"""CSV logging utility for parse pipeline instrumentation."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence


def _is_sequence_of_values(value: object) -> bool:
    """Return True when value is a non-string sequence of CSV cell values."""

    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


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
    delimiter: str = ","
    _fieldnames: list[str] = field(init=False, repr=False)
    _multi_value_fields: set[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self._fieldnames = list(self.fieldnames)
        self.delimiter = str(self.delimiter)
        if len(self.delimiter) != 1:
            raise ValueError("CSV delimiter must be a single character")
        counts = Counter(self._fieldnames)
        self._multi_value_fields = {name for name, count in counts.items() if count > 1}

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

        occurrences: dict[str, int] = {}
        row_values: list[str] = []
        for name in self._fieldnames:
            index = occurrences.get(name, 0)
            occurrences[name] = index + 1

            raw_value = payload.get(name)
            if name in self._multi_value_fields and _is_sequence_of_values(raw_value):
                try:
                    value = raw_value[index]
                except IndexError:
                    value = ""
            else:
                value = raw_value if index == 0 else ""

            row_values.append(_serialise_value(value))

        with self.path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter=self.delimiter)
            if write_header:
                writer.writerow(self._fieldnames)
            writer.writerow(row_values)


__all__ = ["CSVLogger"]
