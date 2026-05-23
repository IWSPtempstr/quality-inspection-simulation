from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from domain.schemas import DataResponse, DatasetReplayStartRequest

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


@router.get("", response_model=DataResponse)
def list_datasets(request: Request) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:read")
    return DataResponse(message="数据集列表查询成功", data=request.app.state.dataset_replay_service.list_datasets())


@router.get("/{dataset_name}/summary", response_model=DataResponse)
def dataset_summary(dataset_name: str, request: Request) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:read")
    try:
        summary = request.app.state.dataset_replay_service.summary(dataset_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="数据集不存在") from exc
    return DataResponse(message="数据集摘要查询成功", data=summary)


@router.post("/{dataset_name}/replay/start", response_model=DataResponse, status_code=status.HTTP_201_CREATED)
def start_dataset_replay(dataset_name: str, payload: DatasetReplayStartRequest, request: Request) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:write")
    try:
        run = request.app.state.dataset_replay_service.start(dataset_name, payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="数据集不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    request.app.state.audit_service.record(
        request,
        action="dataset_replay_started",
        target_type="dataset_replay",
        target_id=run["id"],
        detail={
            "dataset_name": dataset_name,
            "total_orders": run["total_orders"],
            "speed_minutes_per_second": run["speed_minutes_per_second"],
        },
    )
    return DataResponse(message="数据集回放已创建", data=run)


@router.post("/replay/{run_id}/tick", response_model=DataResponse)
def tick_dataset_replay(run_id: str, request: Request) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:write")
    run = request.app.state.dataset_replay_service.tick(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="回放批次不存在")
    if run["status"] == "completed":
        action = "dataset_replay_completed"
    elif run["status"] == "failed":
        action = "dataset_replay_failed"
    else:
        action = "dataset_replay_ticked"
    request.app.state.audit_service.record(
        request,
        action=action,
        target_type="dataset_replay",
        target_id=run_id,
        detail={
            "status": run["status"],
            "imported_orders": run["imported_orders"],
            "latest_order_id": run.get("latest_order_id"),
        },
    )
    return DataResponse(message="数据集回放 Tick 已处理", data=run)


@router.post("/replay/{run_id}/step", response_model=DataResponse)
def step_dataset_replay(run_id: str, request: Request) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:write")
    run = request.app.state.dataset_replay_service.step(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="回放批次不存在")
    if run["status"] == "completed":
        action = "dataset_replay_completed"
    elif run["status"] == "failed":
        action = "dataset_replay_failed"
    else:
        action = "dataset_replay_stepped"
    request.app.state.audit_service.record(
        request,
        action=action,
        target_type="dataset_replay",
        target_id=run_id,
        detail={"status": run["status"], "imported_orders": run["imported_orders"]},
    )
    return DataResponse(message="数据集回放已单步推进", data=run)


@router.post("/replay/{run_id}/pause", response_model=DataResponse)
def pause_dataset_replay(run_id: str, request: Request) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:write")
    run = request.app.state.dataset_replay_service.pause(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="回放批次不存在")
    request.app.state.audit_service.record(
        request,
        action="dataset_replay_paused",
        target_type="dataset_replay",
        target_id=run_id,
        detail={"status": run["status"], "imported_orders": run["imported_orders"]},
    )
    return DataResponse(message="数据集回放已暂停", data=run)


@router.post("/replay/{run_id}/resume", response_model=DataResponse)
def resume_dataset_replay(run_id: str, request: Request) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:write")
    run = request.app.state.dataset_replay_service.resume(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="回放批次不存在")
    request.app.state.audit_service.record(
        request,
        action="dataset_replay_resumed",
        target_type="dataset_replay",
        target_id=run_id,
        detail={"status": run["status"], "imported_orders": run["imported_orders"]},
    )
    return DataResponse(message="数据集回放已续跑", data=run)


@router.get("/replay/{run_id}", response_model=DataResponse)
def get_dataset_replay(run_id: str, request: Request) -> DataResponse:
    request.app.state.permission_service.require(request, "schedule:read")
    run = request.app.state.dataset_replay_service.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="回放批次不存在")
    return DataResponse(message="数据集回放查询成功", data=run)


@router.get("/replay/{run_id}/stream")
def stream_dataset_replay(run_id: str, request: Request) -> StreamingResponse:
    request.app.state.permission_service.require(request, "schedule:read")
    if request.app.state.dataset_replay_service.get(run_id) is None:
        raise HTTPException(status_code=404, detail="回放批次不存在")
    return StreamingResponse(
        iter([request.app.state.dataset_replay_service.stream_events(run_id)]),
        media_type="text/event-stream",
    )
