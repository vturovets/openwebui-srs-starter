from __future__ import annotations

from typing import Any, Dict, List

SCHEMA_NAME = "synonyms_schema"

# JSON schema enforcing the structured output from the Responses API.
RESPONSE_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "results"
    ],
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "ID",
                    "filterName",
                    "filterId",
                    "optionId",
                    "optionName",
                    "synonyms",
                    "notes"
                ],
                "properties": {
                    "ID": {
                        "type": "string"
                    },
                    "filterName": {
                        "type": "string"
                    },
                    "filterId": {
                        "type": "string"
                    },
                    "optionId": {
                        "type": "string"
                    },
                    "optionName": {
                        "type": "string"
                    },
                    "synonyms": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        },
                        "maxItems": 10
                    },
                    "notes": {
                        "type": "string"
                    }
                }
            }
        }
    },
}


def validate_response_item(item: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    required_fields = ["ID", "filterName", "filterId", "optionId", "optionName", "synonyms", "notes"]
    for field in required_fields:
        if field not in item:
            errors.append(f"Missing required field: {field}")
    if "synonyms" in item and not isinstance(item["synonyms"], list):
        errors.append("'synonyms' must be a list")
    return errors
