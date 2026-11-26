from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

JobType = Literal["word_count"]


class WordCountPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=100_000)


class JobError(Exception):
    """An error whose message is safe to expose in job status."""


def run_job(job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if job_type != "word_count":
        raise JobError(f"Unsupported job type: {job_type}")
    words = WordCountPayload.model_validate(payload).text.split()
    if not words:
        raise JobError("Text must contain at least one word.")
    return {"word_count": len(words)}


def retry_delay(attempt: int, base_seconds: float, max_seconds: float) -> float:
    """Return the delay after a failed attempt. Attempts are numbered from one."""
    return min(max_seconds, base_seconds * 2 ** (attempt - 1))
