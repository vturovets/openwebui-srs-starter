"""Integration tests covering the import CLI utility."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts import run_import


REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPO_ROOT / "fixtures"


@pytest.mark.integration
def test_run_import_cli_outputs_summary_and_logs(tmp_path: Path, monkeypatch, capsys) -> None:
    batch = [
        {"text": "Book a trip from Amsterdam to Italy", "mode": "dialog"},
        {"text": "Find holidays to Spain in October"},
    ]
    batch_path = tmp_path / "batch.json"
    batch_path.write_text(json.dumps(batch), encoding="utf-8")

    summary_path = tmp_path / "summary.csv"
    csv_path = tmp_path / "requests.csv"

    monkeypatch.setenv("CSV_PATH", str(csv_path))
    monkeypatch.setenv("IMPORT_SUMMARY_PATH", str(summary_path))
    monkeypatch.setenv("FIXTURES_DIR", str(FIXTURES_DIR))

    exit_code = run_import.main([str(batch_path)])
    assert exit_code == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert payload["counts"]["requests"] == len(batch)
    assert payload["status"] in {"success", "partial"}
    assert payload["durations"]["jobMs"] >= 0.0
    assert payload["latency"]["p50Ms"] is None or payload["latency"]["p50Ms"] >= 0.0

    assert summary_path.is_file()
    with summary_path.open("r", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        rows = list(reader)

    assert len(rows) == 2
    header, values = rows
    status_index = header.index("Status")
    request_index = header.index("Requests")
    assert values[status_index] == payload["status"]
    assert values[request_index] == str(len(batch))
