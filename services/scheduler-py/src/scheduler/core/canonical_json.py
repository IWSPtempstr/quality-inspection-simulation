"""Canonical JSON and result hashing with no transport or persistence behavior."""

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from scheduler.contracts.candidate import ScheduleCandidate
from scheduler.entities.scheduling import NormalizedCandidate

_RFC3339_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON-compatible values with stable keys, lists, and UTC timestamps."""
    return json.dumps(
        _normalize_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def normalized_candidate(candidate: ScheduleCandidate) -> NormalizedCandidate:
    """Return the immutable candidate alongside its deterministic content hash."""
    payload = candidate.model_dump(mode="python")
    digest = sha256(canonical_json_bytes(payload)).hexdigest()
    return NormalizedCandidate(candidate=candidate, normalized_result_hash=f"sha256:{digest}")


def _normalize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("canonical JSON does not permit naive datetimes")
        utc_value = value.astimezone(UTC)
        return utc_value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, dict):
        return {key: _normalize_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, str) and _RFC3339_TIMESTAMP.fullmatch(value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return value
