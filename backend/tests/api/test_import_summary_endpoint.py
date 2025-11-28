from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.dependencies import get_settings
from backend.app.main import create_app


def _build_client(monkeypatch, env: dict[str, str]) -> TestClient:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    app = create_app()
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_import_summary_files():
    data_dir = Path("data")
    preexisting_files = set(data_dir.glob("import_summary_*.json")) if data_dir.exists() else set()
    yield
    if data_dir.exists():
        for path in data_dir.glob("import_summary_*.json"):
            if path not in preexisting_files:
                path.unlink()
        if not any(data_dir.iterdir()):
            data_dir.rmdir()


def _make_operation(total_ms: float, *, mismatched: bool = False) -> dict[str, object]:
    metadata: dict[str, object] = {
        "timings": {"totalMs": total_ms},
        "usage": {
            "components": [
                {
                    "usage": {
                        "tokensIn": 10,
                        "tokensOut": 5,
                        "apiCalls": 1,
                        "cpuMs": 2.5,
                        "ramMbSeconds": 1.2,
                    }
                }
            ]
        },
    }
    if mismatched:
        metadata["expectedValueMismatches"] = [
            {"label": "destination", "expected": "AMS", "actual": "LGW"}
        ]
    return {"status": "success", "metadata": metadata}


def test_import_summary_meets_targets(monkeypatch) -> None:
    client = _build_client(
        monkeypatch,
        {
            "MIN_SAMPLE_SIZE": "3",
            "IMPORT_P95_THRESHOLD_MS": "750",
            "IMPORT_ACCURACY_THRESHOLD": "0.5",
            "P95_OUTLIERS_THRESHOLD": "2000",
            "ALPHA": "0.1",
        },
    )

    try:
        payload = {
            "method": "rules-basic",
            "operations": [
                _make_operation(420.0),
                _make_operation(515.0),
                _make_operation(610.0),
            ],
        }
        response = client.post("/v1/import/summary", json=payload)
        assert response.status_code == 200

        summary = response.json()
        performance = summary["performance"]
        usage = summary["usage"]

        assert performance["requestCount"] == 3
        assert performance["p95"]["thresholdMs"] == 750
        assert performance["p95"]["inference"] == "meet-target"
        assert performance["p95"]["confidenceLevel"] == 0.9
        assert performance["accuracy"]["inference"] == "meet-target"
        assert performance["accuracy"]["threshold"] == 0.5

        assert usage == {
            "tokensIn": 30.0,
            "tokensOut": 15.0,
            "apiCalls": 3.0,
            "cpuMs": 7.5,
            "ramMbSeconds": 3.6,
        }
    finally:
        get_settings.cache_clear()


def test_import_summary_detects_regressions(monkeypatch) -> None:
    client = _build_client(
        monkeypatch,
        {
            "MIN_SAMPLE_SIZE": "3",
            "IMPORT_P95_THRESHOLD_MS": "500",
            "IMPORT_ACCURACY_THRESHOLD": "0.9",
            "P95_OUTLIERS_THRESHOLD": "2000",
            "ALPHA": "0.05",
        },
    )

    try:
        payload = {
            "method": "rules-basic",
            "operations": [
                _make_operation(820.0, mismatched=True),
                _make_operation(910.0, mismatched=True),
                _make_operation(950.0, mismatched=True),
                _make_operation(12_000.0),
            ],
        }
        response = client.post("/v1/import/summary", json=payload)
        assert response.status_code == 200

        performance = response.json()["performance"]
        assert performance["requestCount"] == 4
        assert performance["p95"]["inference"] == "above-target"
        assert performance["accuracy"]["inference"] == "below-target"
        assert performance["accuracy"]["pValue"] < 0.05
    finally:
        get_settings.cache_clear()


def test_import_summary_reports_insufficient_sample(monkeypatch) -> None:
    client = _build_client(
        monkeypatch,
        {
            "MIN_SAMPLE_SIZE": "5",
            "IMPORT_P95_THRESHOLD_MS": "750",
            "IMPORT_ACCURACY_THRESHOLD": "0.85",
        },
    )

    try:
        payload = {
            "method": "rules-basic",
            "operations": [
                _make_operation(400.0),
                _make_operation(500.0),
                _make_operation(600.0),
            ],
        }
        response = client.post("/v1/import/summary", json=payload)
        assert response.status_code == 200

        performance = response.json()["performance"]
        assert performance["requestCount"] == 3
        assert performance["p95"]["inference"] == "insufficient-data"
        assert performance["accuracy"]["inference"] == "insufficient-data"
        assert performance["p95"]["ciLowMs"] is None
        assert performance["accuracy"]["pValue"] is None
    finally:
        get_settings.cache_clear()


def test_import_summary_persists_payload(monkeypatch) -> None:
    client = _build_client(
        monkeypatch,
        {
            "MIN_SAMPLE_SIZE": "3",
            "IMPORT_P95_THRESHOLD_MS": "750",
            "IMPORT_ACCURACY_THRESHOLD": "0.5",
            "P95_OUTLIERS_THRESHOLD": "2000",
            "ALPHA": "0.1",
        },
    )

    data_dir = Path("data")
    preexisting_files = set(data_dir.glob("import_summary_*.json")) if data_dir.exists() else set()

    try:
        payload = {
            "method": "rules-basic",
            "operations": [
                _make_operation(420.0),
                _make_operation(515.0),
                _make_operation(610.0),
            ],
        }
        response = client.post("/v1/import/summary", json=payload)

        assert response.status_code == 200

        new_files = [
            path
            for path in data_dir.glob("import_summary_*.json")
            if path not in preexisting_files
        ]
        assert len(new_files) == 1

        saved_payload = json.loads(new_files[0].read_text())
        assert saved_payload == payload
    finally:
        get_settings.cache_clear()
