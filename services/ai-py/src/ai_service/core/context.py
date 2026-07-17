import contextvars
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestContext:
    correlation_id: str
    request_id: str
    path: str
    method: str

    @classmethod
    def from_headers(
        cls,
        *,
        path: str,
        method: str,
        correlation_id: str | None,
        request_id: str | None,
    ) -> "RequestContext":
        return cls(
            correlation_id=correlation_id or str(uuid.uuid4()),
            request_id=request_id or str(uuid.uuid4()),
            path=path,
            method=method,
        )


_request_context: contextvars.ContextVar[RequestContext | None] = contextvars.ContextVar(
    "request_context",
    default=None,
)


def bind_request_context(context: RequestContext) -> None:
    _request_context.set(context)


def get_request_context() -> RequestContext | None:
    return _request_context.get()


def clear_request_context() -> None:
    _request_context.set(None)
