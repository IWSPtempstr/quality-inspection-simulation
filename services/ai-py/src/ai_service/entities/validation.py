from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel

from ai_service.entities.models import Citation


def ensure_citation_integrity(model: BaseModel) -> None:
    data = model.model_dump()
    evidence_available = _find_boolean(data, "evidence_available")
    citations = _find_citations(data)
    if evidence_available and not citations:
        raise ValueError("evidence_available_requires_citations")
    if not evidence_available and citations:
        raise ValueError("citations_require_evidence_available")


def _find_boolean(value: Any, key: str) -> bool | None:
    if isinstance(value, dict):
        for item_key, item_value in value.items():
            if item_key == key and isinstance(item_value, bool):
                return item_value
            nested = _find_boolean(item_value, key)
            if nested is not None:
                return nested
    if isinstance(value, list):
        for item in value:
            nested = _find_boolean(item, key)
            if nested is not None:
                return nested
    return None


def _find_citations(value: Any) -> list[Citation]:
    if isinstance(value, dict):
        if {"standard_title", "version", "clause", "page", "content"} <= set(value):
            return [Citation.model_validate(value)]
        result: list[Citation] = []
        for item_value in value.values():
            result.extend(_find_citations(item_value))
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(_find_citations(item))
        return result
    return []


def deduplicate_strings(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
