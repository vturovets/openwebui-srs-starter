"""Pytest configuration for ensuring the package root is importable."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


if "multipart" not in sys.modules:
    multipart_stub = ModuleType("multipart")
    multipart_stub.__dict__["__version__"] = "0.0-test"
    multipart_submodule = ModuleType("multipart.multipart")

    def _parse_options_header(value: str):  # pragma: no cover - helper for FastAPI import guard
        raise RuntimeError("python-multipart is required for form parsing")

    multipart_submodule.parse_options_header = _parse_options_header
    multipart_stub.multipart = multipart_submodule  # type: ignore[attr-defined]
    sys.modules["multipart"] = multipart_stub
    sys.modules["multipart.multipart"] = multipart_submodule
