"""Definitions used by the benchmark report."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Observation:
    status: str
    created_at: datetime
    completed_at: datetime | None
    started_at: datetime | None
    duration_ms: float | None = None


@dataclass
class Burst:
    requested: int
    rejected: int
    observations: list[Observation]

    def span(self) -> float:
        finished = [job.completed_at for job in self.observations if job.completed_at is not None]
        if not finished:
            return 0
        return (max(finished) - min(job.created_at for job in self.observations)).total_seconds()


def percentile(ordered: list[float], fraction: float) -> float | None:
    if not ordered:
        return None
    index = (len(ordered) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower), 3)


def distribution(samples: list[float]) -> dict:
    ordered = sorted(samples)
    return {
        "samples": len(samples),
        "p50": percentile(ordered, 0.50),
        "p95": percentile(ordered, 0.95),
        "p99": percentile(ordered, 0.99),
    }


def summarize(bursts: list[Burst]) -> dict:
    observations = [job for run in bursts for job in run.observations]
    requested = sum(run.requested for run in bursts)
    rejected = sum(run.rejected for run in bursts)
    completed = sum(job.status == "completed" for job in observations)
    failed = sum(job.status == "failed" for job in observations)
    terminal = completed + failed
    unfinished = requested - rejected - terminal
    seconds = sum(run.span() for run in bursts)
    queue_wait = [
        (job.started_at - job.created_at).total_seconds() * 1_000
        for job in observations if job.started_at is not None
    ]
    end_to_end = [
        (job.completed_at - job.created_at).total_seconds() * 1_000
        for job in observations if job.completed_at is not None
    ]
    return {
        "requested": requested,
        "submission_errors": rejected,
        "unfinished": unfinished,
        "completed": completed,
        "failed": failed,
        "failure_rate": failed / terminal if terminal else None,
        "elapsed_seconds": round(seconds, 3),
        "jobs_per_second": round(terminal / seconds, 3) if terminal == requested and seconds > 0 else None,
        "queue_wait_ms": distribution(queue_wait),
        "end_to_end_ms": distribution(end_to_end),
        "first_attempt_execution_ms": distribution([
            job.duration_ms for job in observations if job.duration_ms is not None
        ]),
    }
