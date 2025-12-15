from __future__ import annotations

import argparse
import csv
import json
import logging
import random
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Sequence, Set

from dotenv import load_dotenv

from .combinations import DEFAULT_SIZE_WEIGHTS, generate_combinations
from .lexicon import LexiconLoader, LexiconOption
from .openai_client import EmbeddingsAPI, ResponsesAPI, build_centroids
from .sampler import sample_to_csv
from .scoring import compute_multi_metrics, purity_gate, score_option_similarity

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

DEFAULT_MODEL = "gpt-5.2"
DEFAULT_EMBED_MODEL = "text-embedding-3-small"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_RATE_LIMIT_SLEEP = 1.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_TIMEOUT = 60
DEFAULT_PURITY_MARGIN = 0.10
DEFAULT_PURITY_MIN_SCORE = 0.38
DEFAULT_MULTI_COVERAGE_FLAG = 0.30
DEFAULT_MULTI_SEPARATION_FLAG = 0.05
DEFAULT_MAX_UNIQUE_IDS = 150
EMBEDDING_BATCH_SIZE = 100


SINGLE_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "filterId": { "type": "string" },
                    "filterName": { "type": "string" },
                    "optionId": { "type": "string" },
                    "optionName": { "type": "string" },
                    "utterances": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "type": { "type": "string" },
                                "difficulty": { "type": "string" },
                                "utterance": { "type": "string" }
                            },
                            "required": ["type", "difficulty", "utterance"]
                        }
                    }
                },
                "required": ["id", "filterId", "filterName", "optionId", "optionName", "utterances"]
            }
        }
    },
    "required": ["results"]
}


MULTI_RESPONSE_SCHEMA = {

    "type": "object",
    "additionalProperties": False,
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "comboId": { "type": "string" },
                    "utterance": { "type": "string" },
                    "matched": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "id": { "type": "string" },
                                "filterId": { "type": "string" },
                                "filterName": { "type": "string" },
                                "optionId": { "type": "string" },
                                "optionName": { "type": "string" }
                            },
                            "required": ["id", "filterId", "filterName", "optionId", "optionName"]
                        }
                    }
                },
                "required": ["comboId", "utterance", "matched"]
            }
        }
    },
    "required": ["results"]
}


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Utterance dataset generator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    single = subparsers.add_parser("single", help="Generate single-option utterances")
    single.add_argument("--lexicon", required=True, help="Path to lexicon JSON/CSV")
    single.add_argument("--output", required=True, help="Output JSON file")
    single.add_argument("--max-per-option", type=int, default=3)
    single.add_argument("--model", default=DEFAULT_MODEL)
    single.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    single.add_argument("--rate-limit-sleep", type=float, default=DEFAULT_RATE_LIMIT_SLEEP)
    single.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES)
    single.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    single.add_argument(
        "--max-unique-ids",
        type=int,
        default=DEFAULT_MAX_UNIQUE_IDS,
        help="Maximum unique option IDs per batch",
    )
    single.add_argument(
        "--sample-size",
        type=int,
        help="Randomly sample this many unique option IDs from the lexicon before generation",
    )
    single.add_argument(
        "--sample-seed",
        type=int,
        help="Seed used when sampling options for reproducibility",
    )
    single.add_argument("--show-curl", action="store_true")
    single.add_argument("--dry-run", action="store_true")

    multi = subparsers.add_parser("multi", help="Generate multi-option utterances")
    multi.add_argument("--lexicon", required=True)
    multi.add_argument("--output", required=True)
    multi.add_argument("--count", type=int, default=20)
    multi.add_argument("--seed", type=int, default=13)
    multi.add_argument("--allow-same-filter", action="store_true")
    multi.add_argument(
        "--single-option-filter-id",
        action="append",
        dest="single_option_filter_ids",
        default=[],
        help=(
            "Filter IDs that should appear at most once per combo when using --allow-same-filter. "
            "Specify multiple times for multiple filters (e.g. --single-option-filter-id FILTER_A "
            "--single-option-filter-id FILTER_B)."
        ),
    )
    multi.add_argument("--model", default=DEFAULT_MODEL)
    multi.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    multi.add_argument("--rate-limit-sleep", type=float, default=DEFAULT_RATE_LIMIT_SLEEP)
    multi.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES)
    multi.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    multi.add_argument(
        "--max-unique-ids",
        type=int,
        default=DEFAULT_MAX_UNIQUE_IDS,
        help="Maximum unique option IDs per batch",
    )
    multi.add_argument("--show-curl", action="store_true")
    multi.add_argument("--dry-run", action="store_true")

    score = subparsers.add_parser("score", help="Score utterances against centroids")
    score.add_argument("--lexicon", required=True)
    score.add_argument("--utterances", required=True, help="JSONL of utterances to score")
    score.add_argument("--output", required=True, help="Path to scoring report")
    score.add_argument("--embedding-model", default=DEFAULT_EMBED_MODEL)
    score.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    score.add_argument("--purity-margin", type=float, default=DEFAULT_PURITY_MARGIN)
    score.add_argument("--purity-min-score", type=float, default=DEFAULT_PURITY_MIN_SCORE)
    score.add_argument("--multi-coverage-flag", type=float, default=DEFAULT_MULTI_COVERAGE_FLAG)
    score.add_argument("--multi-separation-flag", type=float, default=DEFAULT_MULTI_SEPARATION_FLAG)
    score.add_argument("--show-curl", action="store_true")

    sample = subparsers.add_parser("sample", help="Sample utterances into CSV")
    sample.add_argument("--single-file", help="Path to single-option utterances JSON")
    sample.add_argument(
        "--single-count",
        type=int,
        default=0,
        help="Number of single-option utterances to sample",
    )
    sample.add_argument("--multi-file", help="Path to multi-option utterances JSON")
    sample.add_argument(
        "--multi-count",
        type=int,
        default=0,
        help="Number of multi-option combos to sample",
    )
    sample.add_argument("--seed", type=int, help="Seed for deterministic sampling")
    sample.add_argument("--output", required=True, help="Output CSV path")

    return parser.parse_args(argv)


def _load_lexicon(path_str: str):
    path = Path(path_str)
    return LexiconLoader.load(path)


def _sample_options_by_id(
    options: Sequence[Dict[str, object]] | Sequence[object],
    sample_size: int | None,
    seed: int | None,
    extract_id: Callable[[object], str],
):
    if sample_size is None or sample_size <= 0:
        return list(options)

    id_to_item: Dict[str, object] = {}
    for option in options:
        option_id = extract_id(option)
        if option_id:
            id_to_item.setdefault(option_id, option)

    if not id_to_item:
        return []

    target_size = min(sample_size, len(id_to_item))
    rng = random.Random(seed)
    sampled_ids = rng.sample(sorted(id_to_item.keys()), target_size)
    return [id_to_item[sampled_id] for sampled_id in sampled_ids]


def _chunk_by_unique_option_ids(
    items: Sequence[Dict[str, object]],
    extract_ids: Callable[[Dict[str, object]], Iterable[str]],
    max_unique_ids: int = DEFAULT_MAX_UNIQUE_IDS,
) -> List[List[Dict[str, object]]]:
    batches: List[List[Dict[str, object]]] = []
    current_batch: List[Dict[str, object]] = []
    current_ids: Set[str] = set()

    for item in items:
        item_ids = set(extract_ids(item))
        if not item_ids:
            continue
        combined_ids = current_ids | item_ids
        if current_batch and len(combined_ids) > max_unique_ids:
            batches.append(current_batch)
            current_batch = []
            current_ids = set()
        current_batch.append(item)
        current_ids |= item_ids

    if current_batch:
        batches.append(current_batch)

    return batches


def _save_results(output_path: Path, results: List[Dict[str, object]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump({"results": results}, handle, ensure_ascii=False, indent=2)


def _chunked(items: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _load_utterance_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV utterance file missing headers")
        normalized_headers = [header.replace("\ufeff", "") for header in reader.fieldnames]
        reader.fieldnames = normalized_headers

        required = {"Utterance", "filterId", "filterName", "optionId", "optionName"}
        missing = required - set(normalized_headers)
        if missing:
            raise ValueError(
                "CSV utterance file is missing required columns: "
                f"{', '.join(sorted(missing))}"
            )
        rows: List[Dict[str, str]] = []
        for row in reader:
            rows.append({
                "Utterance": str(row.get("Utterance", "")).strip(),
                "filterId": str(row.get("filterId", "")).strip(),
                "filterName": str(row.get("filterName", "")).strip(),
                "optionId": str(row.get("optionId", "")).strip(),
                "optionName": str(row.get("optionName", "")).strip(),
            })
    return rows


def _embed_texts(texts: Sequence[str], embedder: EmbeddingsAPI) -> List[List[float]]:
    embeddings: List[List[float]] = []
    for batch in _chunked(list(texts), EMBEDDING_BATCH_SIZE):
        embeddings.extend(embedder.embed(batch))
    return embeddings


def _ensure_filter_names(
    *,
    results: List[Dict[str, object]],
    manifest_lookup: Dict[str, Dict[str, object]],
) -> None:
    for entry in results:
        combo_id = str(entry.get("comboId", ""))
        manifest_entry = manifest_lookup.get(combo_id, {})
        matched_options = manifest_entry.get("matched", []) or []
        options_by_id = {str(item.get("optionId", "")): item for item in matched_options}

        for match in entry.get("matched", []) or []:
            if match.get("filterName"):
                continue
            option_id = str(match.get("optionId", ""))
            manifest_match = options_by_id.get(option_id)
            if manifest_match and manifest_match.get("filterName"):
                match["filterName"] = manifest_match.get("filterName")


def _score_utterance_csv(
    *,
    utterances_path: Path,
    output_path: Path,
    centroids: Dict[str, List[float]],
    embedder: EmbeddingsAPI,
    options: Sequence[LexiconOption],
) -> None:
    rows = _load_utterance_csv(utterances_path)
    if not rows:
        logger.warning("No utterances found in %s; writing empty CSV", utterances_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "Utterance",
                    "filterId",
                    "filterName",
                    "optionId",
                    "optionName",
                    "target_similarity",
                    "top_option_id",
                    "top_option_name",
                    "top_similarity",
                    "best_non_target_similarity",
                    "similarity_gap",
                    "target_rank",
                    "is_target_top_match",
                ],
            )
            writer.writeheader()
        return

    logger.info("Embedding %s utterances for scoring", len(rows))
    utterance_texts = [row["Utterance"] for row in rows]
    utterance_embeddings = _embed_texts(utterance_texts, embedder)

    option_lookup = {option.optionId: option for option in options}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "Utterance",
                "filterId",
                "filterName",
                "optionId",
                "optionName",
                "target_similarity",
                "top_option_id",
                "top_option_name",
                "top_similarity",
                "best_non_target_similarity",
                "similarity_gap",
                "target_rank",
                "is_target_top_match",
            ],
        )
        writer.writeheader()

        for row, embedding in zip(rows, utterance_embeddings):
            target_option_id = row.get("optionId", "")
            if target_option_id not in centroids:
                logger.warning(
                    "Skipping utterance with unknown optionId %s: %s", target_option_id, row
                )
                continue

            similarity = score_option_similarity(
                utterance_embedding=embedding,
                option_centroids=centroids,
                target_option_id=target_option_id,
            )
            top_option = option_lookup.get(similarity.top_option_id)
            writer.writerow(
                {
                    "Utterance": row.get("Utterance", ""),
                    "filterId": row.get("filterId", ""),
                    "filterName": row.get("filterName", ""),
                    "optionId": target_option_id,
                    "optionName": row.get("optionName", ""),
                    "target_similarity": similarity.target_score,
                    "top_option_id": similarity.top_option_id,
                    "top_option_name": top_option.optionName if top_option else "",
                    "top_similarity": similarity.top_score,
                    "best_non_target_similarity": similarity.best_non_target_score,
                    "similarity_gap": similarity.margin_to_best_non_target,
                    "target_rank": similarity.target_rank or "",
                    "is_target_top_match": similarity.top_option_id == target_option_id,
                }
            )


def run_single(args: argparse.Namespace) -> None:
    options = _load_lexicon(args.lexicon)
    sampled_options = _sample_options_by_id(
        options,
        sample_size=args.sample_size,
        seed=args.sample_seed,
        extract_id=lambda option: str(getattr(option, "id", None) or getattr(option, "optionId", "")),
    )
    if not sampled_options:
        logger.warning("No options available after sampling; nothing to process")
        _save_results(Path(args.output), [])
        return
    if len(sampled_options) < len(options):
        logger.info(
            "Sampled %s/%s options using ids for single-option generation",
            len(sampled_options),
            len(options),
        )
        options = sampled_options
    if args.dry_run:
        logger.info("Dry run: %s options found", len(options))
        return

    instructions = (
        "Produce between 1 and 3 utterances per option. Include preference_only and mini_query "
        "types with easy/medium/hard difficulty spread. Enforce single-option purity."
    )
    rows = [option.to_payload() | {"max_per_option": args.max_per_option} for option in options]
    client = ResponsesAPI(
        model=args.model,
        temperature=args.temperature,
        timeout=args.timeout,
        max_retries=args.max_retries,
        rate_limit_sleep=args.rate_limit_sleep,
        schema=SINGLE_RESPONSE_SCHEMA,
        show_curl=args.show_curl,
    )
    batches = _chunk_by_unique_option_ids(
        rows,
        extract_ids=lambda item: [str(item.get("optionId", ""))],
        max_unique_ids=args.max_unique_ids,
    )
    aggregated_results: List[Dict[str, object]] = []
    output_path = Path(args.output)
    for index, batch in enumerate(batches, start=1):
        logger.info("Processing single batch %s/%s with %s options", index, len(batches), len(batch))
        response = client.generate(instructions, batch)
        aggregated_results.extend(response.get("results", []))
        _save_results(output_path, aggregated_results)
        logger.info(
            "Saved %s single-option results to %s after batch %s/%s",
            len(aggregated_results),
            output_path,
            index,
            len(batches),
        )
    if not batches:
        _save_results(output_path, aggregated_results)
    logger.info("Saved single-option dataset to %s", output_path)


def run_multi(args: argparse.Namespace) -> None:
    options = _load_lexicon(args.lexicon)
    combos = generate_combinations(
        options=options,
        total=args.count,
        seed=args.seed,
        size_weights=DEFAULT_SIZE_WEIGHTS,
        allow_same_filter=args.allow_same_filter,
        single_option_filter_ids=set(args.single_option_filter_ids or []),
    )
    manifest = [
        {
            "comboId": f"combo-{idx+1}",
            "matched": [option.to_payload() for option in combo.options],
        }
        for idx, combo in enumerate(combos)
    ]
    manifest_lookup = {entry["comboId"]: entry for entry in manifest}

    if args.dry_run:
        logger.info("Dry run: %s combos generated", len(manifest))
        return

    instructions = (
        "Write one natural-sounding utterance per combo that implicitly references all matched "
        "options. Blend the optionName values into a single coherent request without listing "
        "filter or option IDs."
    )
    client = ResponsesAPI(
        model=args.model,
        temperature=args.temperature,
        timeout=args.timeout,
        max_retries=args.max_retries,
        rate_limit_sleep=args.rate_limit_sleep,
        schema=MULTI_RESPONSE_SCHEMA,
        show_curl=args.show_curl,
    )
    batches = _chunk_by_unique_option_ids(
        manifest,
        extract_ids=lambda item: [match.get("optionId", "") for match in item.get("matched", [])],
        max_unique_ids=args.max_unique_ids,
    )

    aggregated_results: List[Dict[str, object]] = []
    output_path = Path(args.output)
    for index, batch in enumerate(batches, start=1):
        logger.info("Processing multi batch %s/%s with %s combos", index, len(batches), len(batch))
        response = client.generate(instructions, batch)
        batch_results = response.get("results", [])
        _ensure_filter_names(results=batch_results, manifest_lookup=manifest_lookup)
        aggregated_results.extend(batch_results)
        _save_results(output_path, aggregated_results)
        logger.info(
            "Saved %s multi-option results to %s after batch %s/%s",
            len(aggregated_results),
            output_path,
            index,
            len(batches),
        )
    if not batches:
        _save_results(output_path, aggregated_results)
    logger.info("Saved multi-option utterances to %s", output_path)


def run_score(args: argparse.Namespace) -> None:
    options = _load_lexicon(args.lexicon)
    embedder = EmbeddingsAPI(
        model=args.embedding_model,
        timeout=args.timeout,
        show_curl=args.show_curl,
    )
    centroids = build_centroids(options, embedder)

    utterances_path = Path(args.utterances)
    if utterances_path.suffix.lower() == ".csv":
        _score_utterance_csv(
            utterances_path=utterances_path,
            output_path=Path(args.output),
            centroids=centroids,
            embedder=embedder,
            options=options,
        )
        logger.info("Saved semantic closeness CSV to %s", args.output)
        return
    utterance_records = []
    with utterances_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            utterance_records.append(json.loads(line))

    report = []
    for record in utterance_records:
        embedding = record.get("embedding")
        option_ids = record.get("option_ids", [])
        if not embedding or not isinstance(embedding, list):
            logger.warning("Skipping record without embedding: %s", record)
            continue
        if len(option_ids) == 1:
            decision = purity_gate(
                utterance_embedding=embedding,
                target_option_id=option_ids[0],
                option_centroids=centroids,
                purity_min_score=args.purity_min_score,
                purity_margin=args.purity_margin,
            )
            report.append(record | {"purity": decision.__dict__})
        else:
            metrics = compute_multi_metrics(
                utterance_embedding=embedding,
                target_option_ids=option_ids,
                centroids=centroids,
                coverage_flag=args.multi_coverage_flag,
                separation_flag=args.multi_separation_flag,
            )
            report.append(record | {"multi": metrics})

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    logger.info("Saved scoring report to %s", output_path)


def run_sample(args: argparse.Namespace) -> None:
    if not args.single_file and not args.multi_file:
        logger.warning("No input files provided; writing empty CSV")
    sample_to_csv(
        output_path=Path(args.output),
        single_path=Path(args.single_file) if args.single_file else None,
        single_count=args.single_count,
        multi_path=Path(args.multi_file) if args.multi_file else None,
        multi_count=args.multi_count,
        seed=args.seed,
    )


def main(argv: List[str] | None = None) -> None:
    load_dotenv()
    args = parse_args(argv)
    if args.command == "single":
        run_single(args)
    elif args.command == "multi":
        run_multi(args)
    elif args.command == "score":
        run_score(args)
    elif args.command == "sample":
        run_sample(args)
    else:  # pragma: no cover - defensive
        raise SystemExit(1)
