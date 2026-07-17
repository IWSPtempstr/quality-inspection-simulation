from collections.abc import Mapping
from typing import Any

SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "token",
        "password",
        "secret",
        "source_body",
        "query",
        "instruction",
    }
)


def redact_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        if not value:
            return value
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return redact_mapping(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def redact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, item in value.items():
        if key.lower() in SENSITIVE_KEYS:
            redacted[key] = redact_value(item)
            continue
        if isinstance(item, Mapping):
            redacted[key] = redact_mapping(item)
            continue
        if isinstance(item, list):
            redacted[key] = [redact_value(element) for element in item]
            continue
        redacted[key] = item
    return redacted
