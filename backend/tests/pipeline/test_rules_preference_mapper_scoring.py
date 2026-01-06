from pathlib import Path

from backend.app.fixtures.filter_catalogue import FiltersCatalogue
from backend.app.pipeline.preferences_mapping import RulesPreferenceMapper
from backend.app.services.synonym_store import SynonymStore


REPO_ROOT = Path(__file__).resolve().parents[3]


def _build_mapper(*, threshold: float = 0.6, negation_penalty: float = 0.25) -> RulesPreferenceMapper:
    catalogue = FiltersCatalogue(REPO_ROOT / "fixtures" / "filters_options_rules_test.csv")
    synonyms = SynonymStore(catalogue)
    return RulesPreferenceMapper(
        catalogue,
        synonym_store=synonyms,
        threshold=threshold,
        negation_penalty=negation_penalty,
    )


def test_rules_mapper_scoring_sets_selection_flag_based_on_threshold() -> None:
    mapper = _build_mapper(threshold=0.65)

    status, selections, _ = mapper.map("wifi", language="en")

    assert status == "success"
    wifi_option = selections[0].options[0]
    assert wifi_option.selected is False

    status, selections, _ = mapper.map("wifi wifi", language="en")

    assert status == "success"
    wifi_option = selections[0].options[0]
    assert wifi_option.selected is True


def test_rules_mapper_applies_negation_penalty() -> None:
    mapper = _build_mapper(threshold=0.6, negation_penalty=0.5)

    status, selections, _ = mapper.map("no catering", language="en")

    assert status == "success"
    boards = next(selection for selection in selections if selection.filter_id == "boards")
    room_only = next(option for option in boards.options if option.id == "room_only")
    assert room_only.selected is False
    assert room_only.confidence is not None and room_only.confidence < 0.6
