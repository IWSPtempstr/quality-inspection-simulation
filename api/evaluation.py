from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query, Request, status

from domain.schemas import DataResponse, OfflineEvaluationRunRequest
from services.evaluation_gate import evaluate_gate, gate_policy, gate_result_dict

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


@router.post("/offline/run", response_model=DataResponse)
def run_offline_evaluation(payload: OfflineEvaluationRunRequest, request: Request) -> DataResponse:
    if not request.app.state.settings.enable_offline_evaluation:
        raise HTTPException(status_code=404, detail="离线评测仅在 demo 模式启用")
    request.app.state.permission_service.require(request, "schedule:read")
    try:
        report = request.app.state.agent_evaluation_service.run_offline(payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="评测数据集不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    request.app.state.audit_service.record(
        request,
        action="agent_offline_evaluation_run",
        target_type="evaluation_dataset",
        target_id=payload.dataset_path,
        detail={
            "total_cases": report["summary"]["total_cases"],
            "passed_cases": report["summary"]["passed_cases"],
        },
    )
    return DataResponse(message="离线评测完成", data=report)


@router.post("/run", response_model=DataResponse)
def run_offline_evaluation_alias(payload: OfflineEvaluationRunRequest, request: Request) -> DataResponse:
    return run_offline_evaluation(payload, request)


@router.get("/gate/policy", response_model=DataResponse)
def get_evaluation_gate_policy(request: Request) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:read")
    return DataResponse(message="Evaluation gate policy 查询成功", data=gate_policy())


@router.post("/gate/check", response_model=DataResponse)
def check_evaluation_gate(payload: dict, request: Request) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:read")
    summary = payload.get("summary", payload)
    if not isinstance(summary, dict):
        raise HTTPException(status_code=400, detail="summary 必须是对象")
    return DataResponse(
        message="Evaluation gate 检查完成",
        data=gate_result_dict(evaluate_gate(summary)),
    )


@router.get("/failed-traces/eval-records", response_model=DataResponse)
def export_failed_trace_eval_records(
    request: Request,
    task_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    format: str = Query(default="json", pattern="^(json|jsonl)$"),
) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:read")
    records = request.app.state.agent_evaluation_service.failed_trace_eval_records(
        task_type=task_type,
        limit=limit,
    )
    request.app.state.audit_service.record(
        request,
        action="agent_failed_trace_eval_records_exported",
        target_type="agent_trace",
        target_id=task_type or "all",
        detail={"total": len(records), "format": format},
    )
    if format == "jsonl":
        content = "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
        return DataResponse(
            message="失败 Trace 评测样本导出成功",
            data={"format": "jsonl", "content": content, "total": len(records)},
        )
    return DataResponse(
        message="失败 Trace 评测样本导出成功",
        data={"format": "json", "items": records, "total": len(records)},
    )


@router.get("/traces", response_model=DataResponse)
def list_agent_traces(
    request: Request,
    task_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:read")
    return DataResponse(
        message="Agent Trace 查询成功",
        data=request.app.state.agent_evaluation_service.list_traces(
            task_type=task_type,
            status=status,
            limit=limit,
            offset=offset,
        ),
    )


@router.get("/traces/{trace_id}", response_model=DataResponse)
def get_agent_trace(trace_id: str, request: Request) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:read")
    trace = request.app.state.agent_evaluation_service.get_trace(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Agent Trace 不存在")
    return DataResponse(message="Agent Trace 查询成功", data=trace)


@router.get("/thresholds/status", response_model=DataResponse)
def get_evaluation_threshold_status(request: Request) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:read")
    return DataResponse(
        message="评测阈值状态查询成功",
        data=request.app.state.agent_evaluation_service.threshold_status(),
    )
