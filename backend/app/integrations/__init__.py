"""Integration helpers for connecting the SRS backend to external systems."""

from .holiday_search_connector import (
    HolidaySearchAPIError,
    HolidaySearchConnector,
    ParseResult,
)
from .gemini import GeminiStructuredLLMClient
from .llm import (
    HolidaySearchLLMClient,
    LLMClientHandle,
    LLMClientRegistry,
    StructuredLLMClient,
)
from .openwebui_extension import HolidaySearchTool, HolidaySearchToolConfig

__all__ = [
    "HolidaySearchAPIError",
    "HolidaySearchConnector",
    "ParseResult",
    "StructuredLLMClient",
    "HolidaySearchLLMClient",
    "GeminiStructuredLLMClient",
    "LLMClientHandle",
    "LLMClientRegistry",
    "HolidaySearchTool",
    "HolidaySearchToolConfig",
]
