from pathlib import Path

import pytest

from backend.app.fixtures.filter_catalogue import FiltersCatalogue
from backend.app.services.synonym_store import SynonymStore

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_synonym_store_builds_inverted_index() -> None:
    catalogue = FiltersCatalogue(REPO_ROOT / "fixtures" / "filters_options.csv")
    store = SynonymStore(catalogue, REPO_ROOT / "fixtures" / "rule_based_synonyms.json")

    wifi_synonyms = store.synonyms_for("facilities", "wifi")
    assert "free wi fi" in wifi_synonyms
    assert "hotel wifi" in wifi_synonyms

    index = store.inverted_index
    assert "wireless internet" in index
    assert ("facilities", "wifi") in index["wireless internet"]


def test_synonym_store_rejects_unknown_option(tmp_path: Path) -> None:
    catalogue = FiltersCatalogue(REPO_ROOT / "fixtures" / "filters_options.csv")
    synonym_file = tmp_path / "synonyms.json"
    synonym_file.write_text(
        "{\"facilities\": {\"unknown\": [\"value\"]}}", encoding="utf-8"
    )

    with pytest.raises(ValueError):
        SynonymStore(catalogue, synonym_file)
