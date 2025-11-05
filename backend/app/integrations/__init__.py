"""Integration helpers for connecting the SRS backend to external systems."""

from .holiday_search_connector import (
    HolidaySearchAPIError,
    HolidaySearchConnector,
    ParseResult,
)
from .openwebui_extension import HolidaySearchTool, HolidaySearchToolConfig

__all__ = [
    "HolidaySearchAPIError",
    "HolidaySearchConnector",
    "ParseResult",
    "HolidaySearchTool",
    "HolidaySearchToolConfig",
]
