from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest

from tools.synonyms_lexicon import cli
from tools.synonyms_lexicon import openai_client
from tools.synonyms_lexicon.io import InputValidationError, chunk_rows, read_input_rows
from tools.synonyms_lexicon.validate import sanitize_synonyms


class DummyClient:
    def __init__(self, payloads: List[List[dict]]):
        self.payloads = payloads
        self.calls = 0
        self.model = "dummy"
        self.temperature = 0.0

    def generate(self, instructions: str, rows: List[dict], max_synonyms: int) -> List[dict]:
        del instructions, rows, max_synonyms
        index = min(self.calls, len(self.payloads) - 1)
        result = self.payloads[index]
        self.calls += 1
        return result

    def build_curl(self, instructions: str, rows: List[dict], max_synonyms: int) -> str:
        del instructions, max_synonyms
        return f"curl --data {json.dumps(rows)}"


def write_csv(tmp_path: Path, headers: list[str], rows: list[list[str]]) -> Path:
    path = tmp_path / "data.csv"
    path.write_text(
        "\n".join([",".join(headers)] + [",".join(row) for row in rows]),
        encoding="utf-8-sig",
    )
    return path


def test_bom_header_and_trimmed_option(tmp_path: Path) -> None:
    csv_path = write_csv(
        tmp_path,
        ["\ufeffID", "filterId", "filterName", "optionId", "optionName"],
        [["1", "DEPARTUREAIRPORTS", "Depart", "10", " JFK "]],
    )
    rows = read_input_rows(csv_path)
    assert rows[0].optionName == "JFK"


def test_missing_columns_raise(tmp_path: Path) -> None:
    csv_path = write_csv(tmp_path, ["ID", "filterId"], [["1", "A"]])
    with pytest.raises(InputValidationError):
        read_input_rows(csv_path)


def test_chunk_rows_preserves_order() -> None:
    rows = [cli.InputRow(str(i), "F", "Filter", str(i), f"Option {i}") for i in range(5)]
    batches = list(chunk_rows(rows, batch_size=2))
    assert [[r.ID for r in batch] for batch in batches] == [["0", "1"], ["2", "3"], ["4"]]


def test_sanitize_synonyms_filters_codes_and_duplicates() -> None:
    synonyms = ["JFK", "AI", "All Incl", "JFK", "  ai  ", "deal"]
    cleaned, removals = sanitize_synonyms("DEPARTUREAIRPORTS", synonyms, max_synonyms=10)
    assert cleaned == ["ai", "all incl", "deal"]
    assert removals == {"duplicates": 1, "codes": 2, "empties": 0}


def test_resume_merges_existing_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    csv_path = write_csv(
        tmp_path,
        ["ID", "filterId", "filterName", "optionId", "optionName"],
        [["1", "F1", "Filter", "O1", "One"], ["2", "F2", "Filter", "O2", "Two"]],
    )
    existing_output = [
        {"ID": "1", "filterId": "F1", "filterName": "Filter", "optionId": "O1", "optionName": "One", "synonyms": ["one"]}
    ]
    output_path = tmp_path / "out.json"
    output_path.write_text(json.dumps(existing_output), encoding="utf-8")

    dummy_client = DummyClient(
        [
            [
                {
                    "ID": "2",
                    "filterId": "F2",
                    "filterName": "Filter",
                    "optionId": "O2",
                    "optionName": "Two",
                    "synonyms": ["Second"],
                    "notes": "",
                }
            ]
        ]
    )

    args = cli.parse_args([
        "--input",
        str(csv_path),
        "--output",
        str(output_path),
        "--batch-size",
        "1",
        "--model",
        "dummy",
    ])

    def mock_read_input_rows(path: Path):
        assert path == csv_path
        return read_input_rows(csv_path)

    monkeypatch.setattr(cli, "read_input_rows", mock_read_input_rows)
    monkeypatch.setattr(cli, "ResponsesAPI", lambda **kwargs: dummy_client)
    cli.run(args)

    merged = json.loads(output_path.read_text(encoding="utf-8"))
    assert [entry["optionId"] for entry in merged] == ["O1", "O2"]
    assert merged[1]["synonyms"] == ["second"]


def test_process_batches_saves_raw(tmp_path: Path) -> None:
    rows = [cli.InputRow("1", "F", "Filter", "O", "Option")]
    client = DummyClient(
        [
            [
                {
                    "ID": "1",
                    "filterId": "F",
                    "filterName": "Filter",
                    "optionId": "O",
                    "optionName": "Option",
                    "synonyms": ["value"],
                    "notes": "",
                }
            ]
        ]
    )
    raw_dir = tmp_path / "raw"
    results = cli.process_batches([rows], client, "instr", 5, raw_dir)
    assert results[0]["synonyms"] == ["value"]
    saved = json.loads((raw_dir / "batch_1.json").read_text(encoding="utf-8"))
    assert saved["response"][0]["synonyms"] == ["value"]
    assert saved["request"]["curl"].startswith("curl --data [")


def test_generate_optionally_prints_curl(capsys, monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyResponses:
        def __init__(self) -> None:
            self.calls = 0

        def create(self, **payload):
            self.calls += 1

            class DummyResponse:
                output_parsed = [{"content": "example"}]

            return DummyResponse()

    dummy = DummyResponses()

    class DummyOpenAI:
        def __init__(self, timeout: int) -> None:
            assert timeout == 1
            self.responses = dummy

    monkeypatch.setattr(openai_client, "OpenAI", DummyOpenAI)
    monkeypatch.setattr(openai_client, "OpenAIError", Exception)

    client = openai_client.ResponsesAPI(
        model="dummy",
        temperature=0.0,
        timeout=1,
        max_retries=0,
        rate_limit_sleep=0.1,
        show_curl=True,
    )

    result = client.generate("instructions", [{"content": "example"}], max_synonyms=3)

    assert dummy.calls == 1
    assert result[0]["content"] == "example"
    output = capsys.readouterr().out
    assert "curl https://api.openai.com/v1/responses" in output
    assert "\"instructions\": \"instructions\"" in output
