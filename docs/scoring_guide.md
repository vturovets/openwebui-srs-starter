# Semantic closeness scoring guide

This guide explains how to run the semantic closeness scoring flow in `tools/utterance_generator` for CSV utterance datasets.

## Prerequisites
- Install dependencies (from repo root):
  ```bash
  pip install -e .
  ```
- Export your OpenAI API key before running:
  ```bash
  export OPENAI_API_KEY="your-key"
  ```

## Inputs
- **Lexicon**: JSON or CSV accepted by `LexiconLoader` (same format used for utterance generation).
- **Utterance CSV**: Must include the following columns:
  - `Utterance`
  - `filterId`
  - `filterName`
  - `optionId`
  - `optionName`

  Rows with unknown `optionId` values (not present in the lexicon) are skipped with a warning.

## Running CSV scoring
From the repository root:
```bash
python -m tools.utterance_generator score \
  --lexicon fixtures/lexicon.csv \
  --utterances data/utterances.csv \
  --output data/semantic_scores.csv \
  --embedding-model text-embedding-3-small
```

Key flags:
- `--embedding-model`: Embedding model for centroid and utterance vectors (defaults to `text-embedding-3-small`).
- `--purity-margin` / `--purity-min-score`: Thresholds used only for JSONL scoring mode.
- `--show-curl`: Print equivalent curl requests for debugging.

## Output columns (CSV)
- `target_similarity`: Cosine similarity between the utterance and the target option centroid.
- `top_option_id` / `top_option_name`: Highest-scoring option.
- `top_similarity`: Cosine similarity for the best match.
- `best_non_target_similarity`: Best similarity for any non-target option.
- `similarity_gap`: `target_similarity - best_non_target_similarity` (positive values mean the target is ahead).
- `target_rank`: 1-based position of the target among all options.
- `is_target_top_match`: Whether the target option is the top match.

## JSONL scoring (legacy)
The `score` command also accepts JSONL inputs that already contain `embedding` and `option_ids` fields per line. In that mode it emits a JSON report with purity or multi-option metrics instead of the CSV columns above.
