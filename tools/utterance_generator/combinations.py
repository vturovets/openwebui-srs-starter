from __future__ import annotations

import itertools
import random
from dataclasses import dataclass
from typing import List, Sequence

from .lexicon import LexiconOption


@dataclass
class OptionCombo:
    options: List[LexiconOption]

    @property
    def option_ids(self) -> List[str]:
        return [option.optionId for option in self.options]

    @property
    def filter_ids(self) -> List[str]:
        return [option.filterId for option in self.options]


DEFAULT_SIZE_WEIGHTS = {2: 0.5, 3: 0.3, 4: 0.2}


def _pick_size(rand: random.Random, size_weights: dict[int, float]) -> int:
    bucket = sorted(size_weights.items())
    total = sum(weight for _, weight in bucket)
    threshold = rand.random() * total
    cumulative = 0.0
    for size, weight in bucket:
        cumulative += weight
        if threshold <= cumulative:
            return size
    return bucket[-1][0]


def generate_combinations(
    options: Sequence[LexiconOption],
    total: int,
    seed: int = 13,
    size_weights: dict[int, float] | None = None,
    allow_same_filter: bool = False,
) -> List[OptionCombo]:
    size_weights = size_weights or DEFAULT_SIZE_WEIGHTS
    rand = random.Random(seed)
    combos: List[OptionCombo] = []
    options_by_filter: dict[str, List[LexiconOption]] = {}
    for option in options:
        options_by_filter.setdefault(option.filterId, []).append(option)

    pool: List[List[LexiconOption]] = []
    if allow_same_filter:
        pool = [list(options)]
    else:
        ordered_filters = sorted(options_by_filter.keys())
        for count in range(2, min(len(ordered_filters), 4) + 1):
            for filter_ids in itertools.combinations(ordered_filters, count):
                pool.append([opt for fid in filter_ids for opt in options_by_filter[fid]])

    seen: set[tuple[str, ...]] = set()
    while len(combos) < total and pool:
        size = _pick_size(rand, size_weights)
        for _ in range(len(pool) * 2):
            group = rand.choice(pool)
            if len(group) < size:
                continue
            selection = rand.sample(group, size)
            if not allow_same_filter and len({opt.filterId for opt in selection}) != len(selection):
                continue
            key = tuple(sorted(opt.optionId for opt in selection))
            if key in seen:
                continue
            seen.add(key)
            combos.append(OptionCombo(options=sorted(selection, key=lambda opt: opt.optionId)))
            break
        else:
            break
    return combos
