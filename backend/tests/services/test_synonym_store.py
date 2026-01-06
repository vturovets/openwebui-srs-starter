from pathlib import Path

import pytest

from backend.app.fixtures.filter_catalogue import FiltersCatalogue
from backend.app.services.synonym_store import SynonymStore

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_synonym_store_builds_inverted_index() -> None:
    catalogue = FiltersCatalogue(REPO_ROOT / "fixtures" / "filters_options_rules_test.csv")
    store = SynonymStore(catalogue)

    wifi_synonyms = store.synonyms_for("facilities", "wifi")
    assert "free wi fi" in wifi_synonyms
    assert "wireless internet" in wifi_synonyms

    index = store.inverted_index
    assert "wireless internet" in index
    assert ("facilities", "wifi") in index["wireless internet"]


def test_synonym_store_rejects_unknown_option(tmp_path: Path) -> None:
    csv_path = tmp_path / "filters.csv"
    csv_path.write_text(
        "\n".join(
            [
                "filterId,filterLabel,optionId,optionLabel,synonyms",
                "facilities,Facilities,wifi,Wi-Fi,",
            ]
        ),
        encoding="utf-8",
    )
    catalogue = FiltersCatalogue(csv_path)

    with pytest.raises(KeyError):
        SynonymStore(catalogue).synonyms_for("facilities", "unknown")
