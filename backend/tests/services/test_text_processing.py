from backend.app.fixtures.filter_catalogue import FiltersCatalogue
from backend.app.services.text_processing import NegationHandler, TextPreprocessor


def test_preprocess_generates_expected_ngrams():
    preprocessor = TextPreprocessor(normalizer=FiltersCatalogue.normalize_label)

    result = preprocessor.preprocess("Wi-Fi in all rooms")

    assert result.cleaned_text == "wi fi in all rooms"
    assert result.tokens == ("wi", "fi", "in", "all", "rooms")
    assert "wi fi" in result.ngrams
    assert "wi fi in" in result.ngrams
    assert "in all rooms" == result.ngrams[-1]


def test_negation_applies_positive_alternative():
    handler = NegationHandler()

    cleaned, spans = handler.apply(
        "no catering but scuba required", normalizer=FiltersCatalogue.normalize_label
    )

    assert cleaned == "room only but scuba required"
    assert spans and spans[0].replacement == "room only"
