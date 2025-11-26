"""Unit tests for backend.app.config.Settings helpers."""

from __future__ import annotations
"""Tests for backend.app.config.Settings helpers."""

from pathlib import Path

from backend.app.config import Settings


def test_popularity_imputer_enabled_default() -> None:
    settings = Settings()
    assert settings.popularity_imputer_enabled is True


def test_resolve_popularity_data_path_relative_to_fixtures(tmp_path: Path) -> None:
    fixtures_dir = tmp_path / "fixtures_payloads"
    fixtures_dir.mkdir()

    settings = Settings(
        fixtures_dir=fixtures_dir,
        popularity_data_path="popularity_stats.json",
    )

    assert settings.resolve_popularity_data_path() == fixtures_dir / "popularity_stats.json"


def test_resolve_popularity_data_path_strips_default_prefix(tmp_path: Path) -> None:
    fixtures_dir = tmp_path / "fixtures_payloads"
    fixtures_dir.mkdir()

    settings = Settings(
        fixtures_dir=fixtures_dir,
        popularity_data_path="fixtures/popularity_stats.json",
    )

    assert settings.resolve_popularity_data_path() == fixtures_dir / "popularity_stats.json"


def test_resolve_popularity_data_path_absolute(tmp_path: Path) -> None:
    fixtures_dir = tmp_path / "fixtures_payloads"
    fixtures_dir.mkdir()

    absolute_path = tmp_path / "alternate" / "stats.json"
    settings = Settings(
        fixtures_dir=fixtures_dir,
        popularity_data_path=absolute_path,
    )

    assert settings.resolve_popularity_data_path() == absolute_path


def test_default_statistical_configuration() -> None:
    settings = Settings()

    assert settings.p95_outliers_threshold_ms == 10_000
    assert settings.min_sample_size == 1000
    assert settings.import_accuracy_threshold == 0.85
    assert settings.alpha == 0.05
