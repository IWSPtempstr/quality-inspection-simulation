"""Minimal FastAPI ingress for immutable scheduling submissions."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status

from scheduler.api.schemas import ScheduleAccepted, ScheduleSubmission
from scheduler.conf.settings import SchedulerSettings
from scheduler.worker.runner import InProcessSchedulerWorker


def create_app(
    settings: SchedulerSettings,
    worker: InProcessSchedulerWorker | None = None,
) -> FastAPI:
    """Create the S4 ingress app with Bearer-only service authentication."""
    scheduler_worker = worker or InProcessSchedulerWorker(settings)
    app = FastAPI(title="scheduler-internal", version="1.0.0")

    async def require_service_bearer(
        authorization: str | None = Header(default=None),
    ) -> None:
        expected = settings.service_bearer_token
        if expected is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="scheduler service authentication is not configured",
            )
        token = authorization.removeprefix("Bearer ").strip() if authorization else ""
        if (
            not authorization
            or not authorization.startswith("Bearer ")
            or token != expected.get_secret_value()
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid scheduler service authentication",
            )

    @app.post(
        "/internal/v1/schedule",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=ScheduleAccepted,
        dependencies=[Depends(require_service_bearer)],
    )
    async def calculate_schedule(submission: ScheduleSubmission) -> ScheduleAccepted:
        scheduler_worker.submit(submission)
        return ScheduleAccepted(
            preview_id=submission.preview_id,
            preview_version=submission.preview_version,
            snapshot_id=submission.snapshot.snapshot_id,
        )

    @app.get("/healthz", include_in_schema=False)
    async def health() -> Response:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app
