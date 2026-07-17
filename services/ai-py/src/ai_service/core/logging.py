import logging
from collections.abc import Mapping
from typing import Any

from ai_service.core.context import get_request_context
from ai_service.core.redaction import redact_mapping


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = get_request_context()
        record.correlation_id = context.correlation_id if context else "-"
        record.request_id = context.request_id if context else "-"
        return True


class RedactionFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if isinstance(record.args, Mapping):
            record.args = redact_mapping(dict(record.args))
        if hasattr(record, "payload") and isinstance(record.payload, Mapping):
            record.payload = redact_mapping(dict(record.payload))
        return super().format(record)


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler()
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(
        RedactionFormatter(
            fmt="%(levelname)s %(correlation_id)s %(request_id)s %(message)s",
        )
    )
    root.addHandler(handler)
    root.setLevel(level)


def log_payload(logger: logging.Logger, message: str, payload: Mapping[str, Any]) -> None:
    logger.info(message, extra={"payload": redact_mapping(dict(payload))})
