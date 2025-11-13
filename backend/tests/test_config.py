"""Regression tests for the Settings helpers."""

from backend.app.config import Settings


def _lowered_allowed_types(settings: Settings) -> set[str]:
    return {ctype.lower() for ctype in settings.voice_allowed_content_types}


def test_settings_default_allowlist_includes_audio_mp4():
    settings = Settings()
    assert "audio/mp4" in _lowered_allowed_types(settings)


def test_settings_resetting_allowlist_preserves_audio_mp4():
    settings = Settings(voice_allowed_content_types=None)
    assert "audio/mp4" in _lowered_allowed_types(settings)

