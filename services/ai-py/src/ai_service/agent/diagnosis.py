from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ai_service.core.context import RequestContext
from ai_service.entities.models import (
    Citation,
    DiagnosisEventSnapshot,
    DiagnosisOrderSnapshot,
    DiagnosisRequest,
    DiagnosisResourceSnapshot,
    DiagnosisResult,
    DiagnosisScheduleSnapshot,
)
from ai_service.entities.retrieval import RetrievalHit, RetrievalMetadataFilter, RetrievalQuery
from ai_service.services.knowledge import KnowledgeService, build_hybrid_retrieval

TOOL_LIMIT = 5
type DiagnosisToolName = Literal[
    "get_event_snapshot",
    "get_order_snapshot",
    "get_resource_snapshot",
    "get_schedule_snapshot",
    "search_standards",
    "search_resolved_cases",
]
type DiagnosisConfidence = Literal["high", "medium", "low", "insufficient"]


@dataclass
class DiagnosisToolbox:
    request: DiagnosisRequest
    knowledge_service: KnowledgeService
    tool_calls: list[DiagnosisToolName] = field(default_factory=list)
    evidence_gaps: list[str] = field(default_factory=list)
    degraded: bool = False

    def get_event_snapshot(self) -> DiagnosisEventSnapshot | None:
        self._record("get_event_snapshot")
        if self.request.event_snapshot is None:
            self.evidence_gaps.append("Event snapshot was not provided.")
        return self.request.event_snapshot

    def get_order_snapshot(self, order_ids: tuple[str, ...]) -> list[DiagnosisOrderSnapshot]:
        self._record("get_order_snapshot")
        by_id = {snapshot.order_id: snapshot for snapshot in self.request.order_snapshots}
        snapshots = [by_id[order_id] for order_id in order_ids if order_id in by_id]
        if order_ids and not snapshots:
            self.evidence_gaps.append("Affected order snapshots were not provided.")
        return snapshots

    def get_resource_snapshot(
        self,
        resource_ids: tuple[str, ...],
    ) -> list[DiagnosisResourceSnapshot]:
        self._record("get_resource_snapshot")
        by_id = {snapshot.resource_id: snapshot for snapshot in self.request.resource_snapshots}
        snapshots = [by_id[resource_id] for resource_id in resource_ids if resource_id in by_id]
        if resource_ids and not snapshots:
            self.evidence_gaps.append("Affected resource snapshots were not provided.")
        return snapshots

    def get_schedule_snapshot(self) -> DiagnosisScheduleSnapshot | None:
        self._record("get_schedule_snapshot")
        if self.request.schedule_snapshot is None:
            self.evidence_gaps.append("Schedule snapshot was not provided.")
        return self.request.schedule_snapshot

    def search_standards(
        self,
        *,
        query_text: str,
    ) -> list[Citation]:
        self._record("search_standards")
        result = build_hybrid_retrieval(
            retrieval_service=self.knowledge_service.retrieval_service,
            reranker=self.knowledge_service.reranker,
            query=RetrievalQuery(
                corpus="standards",
                text=query_text,
                limit=50,
                filters=RetrievalMetadataFilter(access_scopes=("global",)),
                correlation_id=self.request.session_id,
            ),
        )
        citations = _citations_from_hits(result.hits[:5])
        if not citations:
            self.evidence_gaps.append("No cited standards were retrieved for this event.")
        if result.degraded and not citations:
            self.degraded = True
        return citations

    def search_resolved_cases(
        self,
        *,
        query_text: str,
        event_snapshot: DiagnosisEventSnapshot,
    ) -> list[str]:
        self._record("search_resolved_cases")
        result = self.knowledge_service.retrieval_service.hybrid_search(
            RetrievalQuery(
                corpus="resolved_cases",
                text=query_text,
                limit=5,
                filters=RetrievalMetadataFilter(
                    center_id=self.request.center_id,
                    access_scopes=(f"center:{self.request.center_id}",),
                    equipment_ids=event_snapshot.equipment_ids,
                    project_codes=event_snapshot.project_codes,
                    event_types=(event_snapshot.event_type,),
                    review_state="approved",
                ),
                correlation_id=self.request.session_id,
            )
        )
        case_ids = [hit.document_id for hit in result.hits[:5]]
        if result.degraded and not case_ids:
            self.degraded = True
        if not case_ids:
            self.evidence_gaps.append("No reviewed exception cases matched this event.")
        return case_ids

    def _record(self, tool_name: DiagnosisToolName) -> None:
        if len(self.tool_calls) >= TOOL_LIMIT:
            raise ToolBudgetExceededError("diagnosis tool-call budget exceeded")
        self.tool_calls.append(tool_name)


class ToolBudgetExceededError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExceptionDiagnosisAgent:
    knowledge_service: KnowledgeService

    def diagnose(self, *, payload: DiagnosisRequest, context: RequestContext) -> DiagnosisResult:
        _ = context
        toolbox = DiagnosisToolbox(request=payload, knowledge_service=self.knowledge_service)
        try:
            return self._diagnose(payload=payload, toolbox=toolbox)
        except ToolBudgetExceededError:
            return DiagnosisResult(
                event_id=payload.event_id,
                affected_orders=[],
                frozen_step_ids=[],
                sla_risks=[],
                affected_resources=[],
                evidence=[],
                resolved_case_ids=[],
                recommendations=[],
                evidence_gaps=["Diagnosis tool budget was exceeded."],
                confidence="insufficient",
                degraded=True,
                tool_calls=toolbox.tool_calls,
            )

    def _diagnose(
        self,
        *,
        payload: DiagnosisRequest,
        toolbox: DiagnosisToolbox,
    ) -> DiagnosisResult:
        event_snapshot = toolbox.get_event_snapshot()
        if event_snapshot is None:
            return DiagnosisResult(
                event_id=payload.event_id,
                affected_orders=[],
                frozen_step_ids=[],
                sla_risks=[],
                affected_resources=[],
                evidence=[],
                resolved_case_ids=[],
                recommendations=[],
                evidence_gaps=toolbox.evidence_gaps,
                confidence="insufficient",
                degraded=True,
                tool_calls=toolbox.tool_calls,
            )

        affected_orders = self._affected_orders(event_snapshot=event_snapshot, toolbox=toolbox)
        schedule_snapshot = toolbox.get_schedule_snapshot()
        affected_resources = self._affected_resources(
            event_snapshot=event_snapshot,
            affected_orders=affected_orders,
            toolbox=toolbox,
        )
        query_text = self._search_text(
            event_snapshot=event_snapshot,
            affected_orders=affected_orders,
        )
        citations = toolbox.search_standards(query_text=query_text)
        resolved_case_ids = toolbox.search_resolved_cases(
            query_text=query_text,
            event_snapshot=event_snapshot,
        )

        frozen_step_ids = list(schedule_snapshot.frozen_step_ids) if schedule_snapshot else []
        sla_risks = (
            [risk.model_dump() for risk in schedule_snapshot.sla_risks] if schedule_snapshot else []
        )
        recommendations = self._recommendations(
            citations=citations,
            resolved_case_ids=resolved_case_ids,
            frozen_step_ids=frozen_step_ids,
            sla_risks=sla_risks,
            degraded=toolbox.degraded,
        )

        return DiagnosisResult(
            event_id=payload.event_id,
            affected_orders=affected_orders,
            frozen_step_ids=frozen_step_ids,
            sla_risks=sla_risks,
            affected_resources=affected_resources,
            evidence=citations,
            resolved_case_ids=resolved_case_ids,
            recommendations=recommendations,
            evidence_gaps=toolbox.evidence_gaps,
            confidence=_confidence(
                citations=citations,
                resolved_case_ids=resolved_case_ids,
                degraded=toolbox.degraded,
            ),
            degraded=toolbox.degraded,
            tool_calls=toolbox.tool_calls,
        )

    def _affected_orders(
        self,
        *,
        event_snapshot: DiagnosisEventSnapshot,
        toolbox: DiagnosisToolbox,
    ) -> list[dict[str, str]]:
        if not event_snapshot.affected_order_ids:
            return []
        snapshots = toolbox.get_order_snapshot(event_snapshot.affected_order_ids)
        if snapshots:
            return [snapshot.model_dump(mode="json") for snapshot in snapshots]
        return [{"order_id": order_id} for order_id in event_snapshot.affected_order_ids]

    def _affected_resources(
        self,
        *,
        event_snapshot: DiagnosisEventSnapshot,
        affected_orders: list[dict[str, str]],
        toolbox: DiagnosisToolbox,
    ) -> list[dict[str, str]]:
        resource_ids = event_snapshot.affected_resource_ids or event_snapshot.equipment_ids
        should_call_resource_tool = bool(resource_ids) and not affected_orders
        if should_call_resource_tool:
            snapshots = toolbox.get_resource_snapshot(resource_ids)
            if snapshots:
                return [snapshot.model_dump(mode="json") for snapshot in snapshots]
        return [{"resource_id": resource_id} for resource_id in resource_ids]

    def _search_text(
        self,
        *,
        event_snapshot: DiagnosisEventSnapshot,
        affected_orders: list[dict[str, str]],
    ) -> str:
        tokens = [event_snapshot.summary, event_snapshot.event_type, *event_snapshot.project_codes]
        tokens.extend(order.get("title", "") for order in affected_orders)
        text = " ".join(token.strip() for token in tokens if token and token.strip())
        if text:
            return text
        if event_snapshot.related_step_ids:
            return " ".join(event_snapshot.related_step_ids)
        if event_snapshot.affected_order_ids:
            return " ".join(event_snapshot.affected_order_ids)
        return event_snapshot.event_type

    def _recommendations(
        self,
        *,
        citations: list[Citation],
        resolved_case_ids: list[str],
        frozen_step_ids: list[str],
        sla_risks: list[dict[str, object]],
        degraded: bool,
    ) -> list[str]:
        recommendations: list[str] = []
        if frozen_step_ids:
            recommendations.append(
                f"Keep the {len(frozen_step_ids)} frozen steps unchanged while triaging the event."
            )
        if sla_risks:
            recommendations.append(
                f"Review {len(sla_risks)} order-level SLA risks before changing the schedule."
            )
        if citations:
            lead = citations[0]
            recommendations.append(
                f"Start with {lead.standard_title} clause {lead.clause} on page {lead.page}."
            )
        if resolved_case_ids:
            recommendations.append(
                f"Compare this event against reviewed cases: {', '.join(resolved_case_ids[:3])}."
            )
        if degraded:
            recommendations.append(
                "Treat this diagnosis as degraded and confirm it against deterministic event data."
            )
        if not recommendations:
            recommendations.append("Gather more event, schedule, and reviewed-case evidence.")
        return recommendations


def _citations_from_hits(hits: list[RetrievalHit]) -> list[Citation]:
    citations: list[Citation] = []
    for hit in hits:
        standard_title = hit.metadata.get("standard_title")
        version = hit.metadata.get("standard_version")
        clause = hit.metadata.get("clause")
        page = hit.metadata.get("page")
        if not (
            isinstance(standard_title, str)
            and isinstance(version, str)
            and isinstance(clause, str)
            and isinstance(page, int)
            and page >= 1
        ):
            continue
        citations.append(
            Citation(
                standard_title=standard_title,
                version=version,
                clause=clause,
                page=page,
                content=hit.content,
            )
        )
    return citations


def _confidence(
    *,
    citations: list[Citation],
    resolved_case_ids: list[str],
    degraded: bool,
) -> DiagnosisConfidence:
    if not citations:
        return "insufficient"
    if citations and resolved_case_ids and not degraded:
        return "high"
    if citations and not degraded:
        return "medium"
    return "low"
