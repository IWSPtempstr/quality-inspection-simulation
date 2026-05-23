from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from domain.schemas import DataResponse, OfflineEvaluationRunRequest

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


@router.post("/offline/run", response_model=DataResponse)
def run_offline_evaluation(payload: OfflineEvaluationRunRequest, request: Request) -> DataResponse:
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
