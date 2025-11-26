"""Tests covering the backend dependency singletons."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from backend.app import dependencies


def _clear_dependency_caches() -> None:
    for cache in (
        dependencies.get_dialog_orchestrator,
        dependencies.get_pipeline,
        dependencies.get_llm_client,
        dependencies.get_stt_client,
        dependencies.get_csv_logger,
        dependencies.get_methods_catalog,
        dependencies.get_settings,
    ):
        cache.cache_clear()


def test_dependency_settings_propagate_default_targets(monkeypatch, tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("CSV_PATH", str(tmp_path / "logs" / "pipeline.csv"))
    monkeypatch.setenv("FIXTURES_DIR", str(repo_root / "fixtures"))
    monkeypatch.setenv("IMPORT_MAX_CONCURRENCY", "12")
    monkeypatch.setenv("IMPORT_BATCH_SIZE", "25")
    monkeypatch.setenv("IMPORT_CPU_THRESHOLD", "75.5")
    monkeypatch.setenv("IMPORT_MEMORY_THRESHOLD_MB", "2048")
    monkeypatch.setenv("IMPORT_PAUSE_SECONDS", "0.25")

    _clear_dependency_caches()

    try:
        settings = dependencies.get_settings()
        assert settings.import_p95_threshold_ms == 750
        assert settings.import_p95_sample_size == 1000
        assert settings.import_p95_significance == 0.95
        assert settings.import_max_concurrency == 12
        assert settings.import_batch_size == 25
        assert settings.import_cpu_threshold == 75.5
        assert settings.import_memory_threshold_mb == 2048
        assert settings.import_pause_seconds == 0.25

        pipeline = dependencies.get_pipeline()
        assert pipeline._settings is settings  # type: ignore[attr-defined]
        assert pipeline._settings.import_p95_threshold_ms == settings.import_p95_threshold_ms  # type: ignore[attr-defined]

        orchestrator = dependencies.get_dialog_orchestrator()
        assert orchestrator._settings is settings  # type: ignore[attr-defined]

        logger = dependencies.get_csv_logger()
        assert logger.delimiter == settings.csv_delimiter
    finally:
        _clear_dependency_caches()


def test_get_stt_client_uses_fallback_when_deepgram_key_missing(monkeypatch, tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]

    monkeypatch.setenv("VOICE_ENABLED", "true")
    monkeypatch.setenv("STT_ENGINE", "deepgram")
    monkeypatch.setenv("FIXTURES_DIR", str(repo_root / "fixtures"))
    monkeypatch.setenv("CSV_PATH", str(tmp_path / "logs" / "voice.csv"))
    monkeypatch.setenv("VOICE_MAX_BYTES", "4096")
    monkeypatch.setenv("FALLBACK_WHISPER_MODEL", "medium.en")
    monkeypatch.setenv("FALLBACK_WHISPER_DEVICE", "cuda")
    monkeypatch.setenv("FALLBACK_WHISPER_COMPUTE_TYPE", "int8_float16")
    monkeypatch.setenv("FALLBACK_WHISPER_CACHE_DIR", str(tmp_path / "models"))
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)

    created: list[dict[str, object]] = []

    def _stub_fallback_client(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(dependencies, "FasterWhisperSpeechToTextClient", _stub_fallback_client)

    _clear_dependency_caches()

    try:
        client = dependencies.get_stt_client()
        assert client is not None
        assert created, "fallback client should be instantiated"
        params = created[-1]
        assert params["model"] == "medium.en"
        assert params["device"] == "cuda"
        assert params["compute_type"] == "int8_float16"
        assert params["voice_max_bytes"] == 4096
        assert Path(params["cache_dir"]) == tmp_path / "models"
    finally:
        _clear_dependency_caches()
