from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from task_system.models import Job, JobStatus


class JobView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: str
    status: JobStatus
    attempts: int
    max_attempts: int
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None
    next_attempt_at: datetime | None = None

    @classmethod
    def from_job(cls, job: Job) -> "JobView":
        result = cls.model_validate(job)
        if job.status == JobStatus.PENDING:
            result.next_attempt_at = job.available_at
        return result
