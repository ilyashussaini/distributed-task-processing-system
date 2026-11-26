from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine
from starlette.concurrency import run_in_threadpool

from task_system.config import Settings
from task_system.csv_sales import CSV_JOB_TYPE, MAX_CSV_BYTES
from task_system.db import make_engine, make_sessions
from task_system.jobs import RecoveryDemoPayload, WordCountPayload
from task_system.monitoring import monitoring_router
from task_system.schemas import JobView
from task_system.store import JobStore


class WordCountSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["word_count"]
    payload: WordCountPayload


class RecoveryDemoSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["recovery_demo"]
    payload: RecoveryDemoPayload


JobSubmission = Annotated[WordCountSubmission | RecoveryDemoSubmission, Field(discriminator="type")]


def create_app(settings: Settings | None = None, *, engine: Engine | None = None) -> FastAPI:
    settings = settings or Settings()
    db_engine = engine if engine is not None else make_engine(settings)
    sessions = make_sessions(db_engine)
    store = JobStore(sessions, settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            if engine is None:
                db_engine.dispose()

    app = FastAPI(title="Distributed Task Processing System", version="1.0.0", lifespan=lifespan)

    @app.post("/jobs", response_model=JobView, status_code=status.HTTP_202_ACCEPTED)
    def submit_job(submission: JobSubmission, response: Response) -> JobView:
        if submission.type == "recovery_demo" and not settings.enable_recovery_demo:
            raise HTTPException(status_code=403, detail="Recovery demo jobs are disabled")
        job = store.create(submission.type, submission.payload.model_dump())
        response.headers["Location"] = f"/jobs/{job.id}"
        return JobView.from_job(job)

    @app.post(
        "/jobs/csv", response_model=JobView, status_code=status.HTTP_202_ACCEPTED,
        openapi_extra={"requestBody": {"required": True, "content": {
            "text/csv": {"schema": {"type": "string", "format": "binary"}},
        }}},
    )
    async def upload_csv(request: Request, response: Response) -> JobView:
        media = request.headers.get("content-type", "").partition(";")[0].strip().lower()
        encoding = request.headers.get("content-encoding", "identity").lower()
        if media != "text/csv" or encoding != "identity":
            raise HTTPException(status_code=415, detail="Upload an uncompressed text/csv file.")
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_CSV_BYTES:
                raise HTTPException(status_code=413, detail="CSV exceeds the 512 KiB limit.")
            data.extend(chunk)
        try:
            source = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=422, detail="CSV must be encoded as UTF-8.") from exc
        if not source.strip():
            raise HTTPException(status_code=422, detail="CSV is empty.")
        job = await run_in_threadpool(store.create, CSV_JOB_TYPE, {"csv": source})
        response.headers["Location"] = f"/jobs/{job.id}"
        return JobView.from_job(job)

    @app.get("/jobs/{job_id}", response_model=JobView)
    def get_job(job_id: UUID) -> JobView:
        job = store.get(job_id, include_payload=False)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
        return JobView.from_job(job)

    @app.get("/jobs", response_model=list[JobView])
    def list_jobs(
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
    ) -> list[JobView]:
        return [JobView.from_job(job) for job in store.list_jobs(limit, offset)]

    app.include_router(monitoring_router(sessions))
    return app


app = create_app()
