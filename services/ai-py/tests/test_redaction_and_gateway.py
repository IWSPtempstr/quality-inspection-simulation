import logging

import pytest
from pydantic import BaseModel

from ai_service.clients.llm_gateway import StructuredLLMGateway
from ai_service.core.context import RequestContext, bind_request_context, clear_request_context
from ai_service.core.logging import RequestContextFilter
from ai_service.core.redaction import redact_mapping
from ai_service.entities.models import Citation, KnowledgeAnswer


class NestedEvidence(BaseModel):
    evidence_available: bool
    citations: list[Citation]


def test_redact_mapping_masks_sensitive_values() -> None:
    redacted = redact_mapping(
        {
            "query": "secret query",
            "nested": {"authorization": "Bearer abc"},
            "title": "visible",
        }
    )
    assert redacted == {
        "query": "[REDACTED]",
        "nested": {"authorization": "[REDACTED]"},
        "title": "visible",
    }


def test_gateway_validates_citations() -> None:
    gateway = StructuredLLMGateway()
    payload = {
        "answer": "ok",
        "citations": [
            {
                "standard_title": "ISO",
                "version": "2025",
                "clause": "1.2",
                "page": 3,
                "content": "quoted",
            }
        ],
        "evidence_available": True,
    }
    model = gateway.decode(payload, KnowledgeAnswer)
    assert model.evidence_available is True


def test_gateway_rejects_mismatched_evidence_flag() -> None:
    gateway = StructuredLLMGateway()
    with pytest.raises(ValueError):
        gateway.decode(
            {
                "answer": "bad",
                "citations": [],
                "evidence_available": True,
            },
            KnowledgeAnswer,
        )


def test_request_context_filter_sets_ids() -> None:
    bind_request_context(
        RequestContext(
            correlation_id="corr-1",
            request_id="req-1",
            path="/internal/v1/knowledge/query",
            method="POST",
        )
    )
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", (), None)
    try:
        accepted = RequestContextFilter().filter(record)
    finally:
        clear_request_context()
    assert accepted is True
    assert record.correlation_id == "corr-1"
    assert record.request_id == "req-1"
