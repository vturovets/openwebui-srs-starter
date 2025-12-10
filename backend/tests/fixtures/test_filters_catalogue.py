from pathlib import Path

import pytest

from backend.app.fixtures.filter_catalogue import FiltersCatalogue


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_filters_catalogue_loads_fixture() -> None:
    catalogue_path = REPO_ROOT / "fixtures" / "filters_options.csv"
    catalogue = FiltersCatalogue(catalogue_path)

    filters = catalogue.list_filters()
    assert filters
    facilities = catalogue.get_filter("facilities")
    assert facilities.label == "Facilities"
    option_ids = {option.id for option in facilities.options}
    assert {"wifi", "scuba"}.issubset(option_ids)


def test_filters_catalogue_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        FiltersCatalogue(tmp_path / "filters_options.csv")


def test_filters_catalogue_rejects_invalid_delimiter(monkeypatch) -> None:
    catalogue_path = REPO_ROOT / "fixtures" / "filters_options.csv"
    with pytest.raises(ValueError):
        FiltersCatalogue(catalogue_path, delimiter="::")
