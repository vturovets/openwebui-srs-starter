"""Service layer utilities for background job processing."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "GuardrailAction",
    "GuardrailOverloadError",
    "ImportProgress",
    "ImportJobRunner",
    "ImportSummary",
    "JobMetrics",
    "AutoCompletionService",
    "PopularityImputer",
]


def __getattr__(name: str) -> Any:  # pragma: no cover - thin import wrapper
    if name in {
        "GuardrailAction",
        "GuardrailOverloadError",
        "ImportProgress",
        "ImportJobRunner",
        "ImportSummary",
        "JobMetrics",
    }:
        module = import_module(".import_runner", __name__)
        return getattr(module, name)
    if name == "PopularityImputer":
        module = import_module(".popularity_imputer", __name__)
        return module.PopularityImputer
    if name == "AutoCompletionService":
        module = import_module(".auto_completion", __name__)
        return module.AutoCompletionService
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

