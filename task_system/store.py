from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from task_system.config import Settings
from task_system.jobs import retry_delay
from task_system.models import Job, JobStatus


class JobStore:
    def __init__(self, sessions: sessionmaker[Session], settings: Settings):
        self.sessions = sessions
        self.settings = settings

    def create(self, job_type: str, payload: dict[str, Any]) -> Job:
        job = Job(
            id=uuid4(),
            type=job_type,
            payload=payload,
            status=JobStatus.PENDING,
            attempts=0,
            max_attempts=self.settings.max_attempts,
        )
        with self.sessions.begin() as session:
            session.add(job)
        return job

    def get(self, job_id: UUID) -> Job | None:
        with self.sessions() as session:
            return session.get(Job, job_id)

    def list_jobs(self, limit: int, offset: int) -> list[Job]:
        with self.sessions() as session:
            query = select(Job).order_by(Job.created_at.desc(), Job.id.desc())
            return list(session.scalars(query.limit(limit).offset(offset)))

    def dispatch_due(self, publish: Callable[[list[UUID]], None]) -> int:
        with self.sessions.begin() as session:
            now = session.scalar(select(func.now()))
            query = (
                select(Job.id)
                .where(Job.status == JobStatus.PENDING, Job.dispatch_after <= now)
                .order_by(Job.dispatch_after, Job.id)
                .limit(self.settings.dispatch_batch_size)
                .with_for_update(skip_locked=True)
            )
            job_ids = list(session.scalars(query))
            if job_ids:
                # Roll back the dispatch deadline if Redis publishing fails.
                publish(job_ids)
                dispatch_after = now + timedelta(seconds=self.settings.redispatch_seconds)
                session.execute(
                    update(Job).where(Job.id.in_(job_ids)).values(dispatch_after=dispatch_after)
                )
            return len(job_ids)

    def claim(self, job_id: UUID) -> Job | None:
        with self.sessions.begin() as session:
            job = session.get(Job, job_id, with_for_update=True)
            if job is None or job.status != JobStatus.PENDING:
                return None
            now = session.scalar(select(func.clock_timestamp()))
            if job.available_at > now:
                return None
            job.status = JobStatus.RUNNING
            job.attempts += 1
            job.lease_expires_at = now + timedelta(seconds=self.settings.lease_seconds)
            return job

    def complete(self, claim: Job, result: dict[str, Any]) -> bool:
        with self.sessions.begin() as session:
            attempt = self._lock_live_attempt(session, claim)
            if attempt is None:
                return False
            job, now = attempt
            job.status = JobStatus.COMPLETED
            job.result = result
            job.error = None
            job.completed_at = now
            job.lease_expires_at = None
            return True

    def fail(self, claim: Job, error: str) -> bool:
        with self.sessions.begin() as session:
            attempt = self._lock_live_attempt(session, claim)
            if attempt is None:
                return False
            job, now = attempt
            self._record_failure(job, error, now)
            return True

    def renew_lease(self, claim: Job) -> bool:
        with self.sessions.begin() as session:
            attempt = self._lock_live_attempt(session, claim)
            if attempt is None:
                return False
            job, now = attempt
            job.lease_expires_at = now + timedelta(seconds=self.settings.lease_seconds)
            return True

    def recover_expired(self) -> int:
        with self.sessions.begin() as session:
            now = session.scalar(select(func.now()))
            query = (
                select(Job)
                .where(Job.status == JobStatus.RUNNING, Job.lease_expires_at <= now)
                .order_by(Job.lease_expires_at, Job.id)
                .limit(self.settings.dispatch_batch_size)
                .with_for_update(skip_locked=True)
            )
            jobs = list(session.scalars(query))
            for job in jobs:
                self._record_failure(job, "Worker lease expired.", now)
            return len(jobs)

    @staticmethod
    def _lock_live_attempt(session: Session, claim: Job) -> tuple[Job, datetime] | None:
        job = session.get(Job, claim.id, with_for_update=True)
        if (
            job is None
            or job.status != JobStatus.RUNNING
            or job.attempts != claim.attempts
            or job.lease_expires_at is None
        ):
            return None
        # Check the database clock after acquiring the row lock.
        now = session.scalar(select(func.clock_timestamp()))
        if job.lease_expires_at <= now:
            return None
        return job, now

    def _record_failure(self, job: Job, error: str, now: datetime) -> None:
        job.error = error
        job.lease_expires_at = None
        if job.attempts >= job.max_attempts:
            job.status = JobStatus.FAILED
            job.completed_at = now
            return

        delay = retry_delay(
            job.attempts, self.settings.retry_base_seconds, self.settings.retry_max_seconds
        )
        job.status = JobStatus.PENDING
        job.available_at = now + timedelta(seconds=delay)
        job.dispatch_after = job.available_at
