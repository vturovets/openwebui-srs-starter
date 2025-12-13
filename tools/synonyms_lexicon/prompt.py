from __future__ import annotations

from pathlib import Path

PROMPT_VERSION = "synonyms_lexicon_instructions_v1"
PROMPT_PATH = Path("prompts") / f"{PROMPT_VERSION}.txt"


def load_prompt_text() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")
