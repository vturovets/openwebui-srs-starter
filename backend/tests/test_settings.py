"""Unit tests for backend.app.config.Settings helpers."""

from __future__ import annotations
"""Tests for backend.app.config.Settings helpers."""

from pathlib import Path

from backend.app.config import Settings


def test_popularity_imputer_enabled_default() -> None:
    settings = Settings()
    assert settings.popularity_imputer_enabled is False


def test_popularity_imputer_enabled_hybrid_only() -> None:
    settings = Settings(llm_method="hybrid")

    assert settings.popularity_imputer_enabled is True


def test_popularity_imputer_disabled_when_method_not_hybrid() -> None:
    settings = Settings(llm_method="rules", popularity_imputer_enabled=True)

    assert settings.popularity_imputer_enabled is False


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
