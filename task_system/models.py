from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, DateTime, Index, String, Text, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_jobs_status",
        ),
        CheckConstraint(
            "attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts",
            name="ck_jobs_attempts",
        ),
        Index("ix_jobs_created_at_id", "created_at", "id"),
        Index("ix_jobs_status_dispatch_after", "status", "dispatch_after"),
        Index("ix_jobs_status_lease_expires_at", "status", "lease_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int]
    max_attempts: Mapped[int]
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    dispatch_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
