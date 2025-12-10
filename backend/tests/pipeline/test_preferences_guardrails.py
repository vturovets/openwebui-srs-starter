from __future__ import annotations

import time

from backend.app.pipeline.preferences import PreferencesPipeline
from backend.app.pipeline.preferences_mapping import FilterSelection, PreferenceMappingStrategy


class _SlowPreferenceMapper(PreferenceMappingStrategy):
    """Strategy that deliberately exceeds the processing threshold."""

    def map(self, utterance: str, *, language: str):
        time.sleep(0.02)
        wifi_filter = self._catalogue.get_filter("facilities")
        selection = FilterSelection.from_catalogue(wifi_filter, wifi_filter.options[:1])
        mappings = [
            {
                "filterId": wifi_filter.id,
                "optionId": wifi_filter.options[0].id,
                "spans": [{"text": "wifi"}],
            }
        ]
        return "success", [selection], mappings


def test_preferences_pipeline_flags_threshold(monkeypatch):
    monkeypatch.setenv("PROCESSING_THRESHOLD_MS", "5")
    pipeline = PreferencesPipeline()
    pipeline._strategies = {"rules": _SlowPreferenceMapper(pipeline._filters_catalogue)}

    result = pipeline.run("need wifi", method="rules")

    assert result.timings["totalMs"] > pipeline._settings.processing_threshold_ms
    assert result.timings["thresholdBreached"] is True

