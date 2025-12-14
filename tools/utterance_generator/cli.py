from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import List

from dotenv import load_dotenv

from .combinations import DEFAULT_SIZE_WEIGHTS, generate_combinations
from .lexicon import LexiconLoader
from .openai_client import EmbeddingsAPI, ResponsesAPI, build_centroids
from .scoring import compute_multi_metrics, purity_gate

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


SINGLE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "filterId": {"type": "string"},
                    "filterName": {"type": "string"},
                    "optionId": {"type": "string"},
                    "optionName": {"type": "string"},
                    "utterances": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string"},
                                "difficulty": {"type": "string"},
                                "utterance": {"type": "string"},
                            },
                            "required": ["type", "difficulty", "utterance"],
                        },
                    },
                },
                "required": ["filterId", "optionId", "optionName", "utterances"],
            },
        }
    },
    "required": ["results"],
}


MULTI_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "comboId": {"type": "string"},
                    "utterance": {"type": "string"},
                    "matched": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "filterId": {"type": "string"},
                                "optionId": {"type": "string"},
                                "optionName": {"type": "string"},
                            },
                            "required": ["filterId", "optionId", "optionName"],
                        },
                    },
                },
                "required": ["comboId", "utterance", "matched"],
            },
        }
    },
    "required": ["results"],
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
    single.add_argument("--show-curl", action="store_true")
    single.add_argument("--dry-run", action="store_true")

    multi = subparsers.add_parser("multi", help="Generate multi-option combos")
    multi.add_argument("--lexicon", required=True)
    multi.add_argument("--output", required=True)
    multi.add_argument("--count", type=int, default=20)
    multi.add_argument("--seed", type=int, default=13)
    multi.add_argument("--allow-same-filter", action="store_true")

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

    return parser.parse_args(argv)


def _load_lexicon(path_str: str):
    path = Path(path_str)
    return LexiconLoader.load(path)


def run_single(args: argparse.Namespace) -> None:
    options = _load_lexicon(args.lexicon)
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
    response = client.generate(instructions, rows)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(response, handle, ensure_ascii=False, indent=2)
    logger.info("Saved single-option dataset to %s", output_path)


def run_multi(args: argparse.Namespace) -> None:
    options = _load_lexicon(args.lexicon)
    combos = generate_combinations(
        options=options,
        total=args.count,
        seed=args.seed,
        size_weights=DEFAULT_SIZE_WEIGHTS,
        allow_same_filter=args.allow_same_filter,
    )
    manifest = [
        {
            "comboId": f"combo-{idx+1}",
            "matched": [option.to_payload() for option in combo.options],
        }
        for idx, combo in enumerate(combos)
    ]
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump({"results": manifest}, handle, ensure_ascii=False, indent=2)
    logger.info("Saved %s combos to %s", len(manifest), output_path)


def run_score(args: argparse.Namespace) -> None:
    options = _load_lexicon(args.lexicon)
    embedder = EmbeddingsAPI(model=args.embedding_model, timeout=args.timeout)
    centroids = build_centroids(options, embedder)

    utterances_path = Path(args.utterances)
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


def main(argv: List[str] | None = None) -> None:
    load_dotenv()
    args = parse_args(argv)
    if args.command == "single":
        run_single(args)
    elif args.command == "multi":
        run_multi(args)
    elif args.command == "score":
        run_score(args)
    else:  # pragma: no cover - defensive
        raise SystemExit(1)
