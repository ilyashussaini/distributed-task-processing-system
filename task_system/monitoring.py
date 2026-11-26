from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, String, cast, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from task_system.models import AttemptStatus, Job, JobAttempt, JobStatus
from task_system.schemas import JobView

Window = Literal["1h", "24h", "7d", "30d"]
WINDOWS: dict[Window, tuple[timedelta, int]] = {
    "1h": (timedelta(minutes=5), 12),
    "24h": (timedelta(hours=1), 24),
    "7d": (timedelta(days=1), 7),
    "30d": (timedelta(days=1), 30),
}


class JobCounts(BaseModel):
    total: int = 0
    pending: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0


class ActivityBucket(BaseModel):
    start: datetime
    submitted: int = 0
    completed: int = 0
    failed: int = 0


class DurationStatistics(BaseModel):
    samples: int
    average_ms: float | None
    minimum_ms: float | None
    p95_ms: float | None
    maximum_ms: float | None


class PeriodStatistics(BaseModel):
    submitted: int
    completed: int
    failed: int
    success_rate: float | None
    failure_rate: float | None
    retry_attempts: int
    retried_jobs: int
    failed_attempts: int
    abandoned_attempts: int
    duration: DurationStatistics


class Overview(BaseModel):
    generated_at: datetime
    counts: JobCounts
    period: PeriodStatistics
    activity: list[ActivityBucket]


class JobPage(BaseModel):
    jobs: list[JobView]
    total: int


class AttemptView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    number: int
    status: AttemptStatus
    started_at: datetime
    finished_at: datetime | None
    duration_ms: float | None
    error: str | None


class JobDetails(BaseModel):
    job: JobView
    attempts: list[AttemptView]


def read_overview(session: Session, window: Window) -> Overview:
    width, bucket_count = WINDOWS[window]
    now = session.scalar(select(func.now())).astimezone(UTC)
    start = now - width * bucket_count
    counts = dict(session.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    activity = read_activity(session, start, now, width, bucket_count)
    duration = JobAttempt.duration_ms
    retry = JobAttempt.number > 1
    attempt_stats = session.execute(
        select(
            func.count().filter(retry),
            func.count(func.distinct(JobAttempt.job_id)).filter(retry),
            func.count().filter(JobAttempt.status == AttemptStatus.FAILED),
            func.count().filter(JobAttempt.status == AttemptStatus.ABANDONED),
            func.count(duration),
            func.avg(duration),
            func.min(duration),
            func.percentile_cont(0.95).within_group(duration),
            func.max(duration),
        ).where(JobAttempt.started_at >= start, JobAttempt.started_at < now)
    ).one()
    retries, retried_jobs, failed_attempts, abandoned_attempts, samples, avg, minimum, p95, maximum = (
        attempt_stats
    )
    completed = sum(bucket.completed for bucket in activity)
    failed = sum(bucket.failed for bucket in activity)
    terminal = completed + failed
    return Overview(
        generated_at=now,
        counts=JobCounts(total=sum(counts.values()), **counts),
        activity=activity,
        period=PeriodStatistics(
            submitted=sum(bucket.submitted for bucket in activity),
            completed=completed,
            failed=failed,
            success_rate=completed / terminal if terminal else None,
            failure_rate=failed / terminal if terminal else None,
            retry_attempts=retries,
            retried_jobs=retried_jobs,
            failed_attempts=failed_attempts,
            abandoned_attempts=abandoned_attempts,
            duration=DurationStatistics(
                samples=samples, average_ms=avg, minimum_ms=minimum, p95_ms=p95, maximum_ms=maximum,
            ),
        ),
    )


def read_activity(
    session: Session, start: datetime, now: datetime, width: timedelta, bucket_count: int,
) -> list[ActivityBucket]:
    buckets = {
        start + index * width: ActivityBucket(start=start + index * width)
        for index in range(bucket_count)
    }
    created = func.date_bin(width, Job.created_at, start, type_=DateTime(timezone=True))
    finished = func.date_bin(width, Job.completed_at, start, type_=DateTime(timezone=True))
    submitted = session.execute(
        select(created, func.count())
        .where(Job.created_at >= start, Job.created_at < now)
        .group_by(created)
    )
    for bucket, count in submitted:
        buckets[bucket].submitted = count
    finished_counts = session.execute(
        select(
            finished,
            func.count().filter(Job.status == JobStatus.COMPLETED),
            func.count().filter(Job.status == JobStatus.FAILED),
        )
        .where(Job.completed_at >= start, Job.completed_at < now)
        .group_by(finished)
    )
    for bucket, completed, failed in finished_counts:
        buckets[bucket].completed = completed
        buckets[bucket].failed = failed
    return list(buckets.values())


def monitoring_router(sessions: sessionmaker[Session]) -> APIRouter:
    router = APIRouter(prefix="/monitoring", tags=["monitoring"])

    @router.get("/overview")
    def overview(window: Window = "24h") -> Overview:
        with sessions() as session:
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            return read_overview(session, window)

    @router.get("/jobs")
    def jobs(
        limit: Annotated[int, Query(ge=1, le=100)] = 10,
        offset: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
        status: JobStatus | None = None,
        q: Annotated[str, Query(max_length=100)] = "",
    ) -> JobPage:
        filters = []
        if status is not None:
            filters.append(Job.status == status)
        if term := q.strip():
            filters.append(or_(
                cast(Job.id, String).icontains(term, autoescape=True),
                Job.type.icontains(term, autoescape=True),
                func.replace(Job.type, "_", " ").icontains(term, autoescape=True),
            ))
        with sessions() as session:
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            total = session.scalar(select(func.count()).select_from(Job).where(*filters))
            rows = session.scalars(
                select(Job).where(*filters).order_by(Job.created_at.desc(), Job.id.desc())
                .limit(limit).offset(offset)
            )
            return JobPage(jobs=[JobView.from_job(job) for job in rows], total=total)

    @router.get("/jobs/{job_id}")
    def details(job_id: UUID) -> JobDetails:
        with sessions() as session:
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            job = session.get(Job, job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Job not found")
            rows = session.scalars(
                select(JobAttempt).where(JobAttempt.job_id == job_id).order_by(JobAttempt.number)
            )
            return JobDetails(job=JobView.from_job(job), attempts=[AttemptView.model_validate(row) for row in rows])

    return router
