"""Schema validation coverage for A1/A5 contract models."""

import pytest

from ai_service.entities.models import DiagnosisMemoryStatus, DiagnosisResult, KnowledgeAnswer


def test_knowledge_answer_requires_citations_when_evidence_exists() -> None:
    with pytest.raises(ValueError, match="citations are required"):
        KnowledgeAnswer(answer="Grounded", citations=(), evidence_available=True)


def test_diagnosis_without_evidence_requires_insufficient_confidence() -> None:
    with pytest.raises(ValueError, match="confidence must be insufficient"):
        DiagnosisResult(
            event_id="event-a",
            confidence="high",
            affected_orders=(),
            frozen_step_ids=(),
            sla_risks=(),
            affected_resources=(),
            evidence=(),
            resolved_case_ids=(),
            recommendations=(),
            evidence_gaps=(),
            memory_status=DiagnosisMemoryStatus(
                enabled=False,
                session_scoped=False,
                recent_turn_count=0,
                summary_available=False,
                compressed_turn_count=0,
            ),
            degraded=True,
            tool_calls=(),
        )
