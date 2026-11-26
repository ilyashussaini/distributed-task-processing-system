from threading import Event
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WordCountPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=100_000)


class RecoveryDemoPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["hang", "abandon_first_attempt"]


class JobError(Exception):
    """An error whose message is safe to expose in job status."""


def run_job(job_type: str, payload: dict[str, Any], *, attempt: int = 1) -> dict[str, Any]:
    if job_type == "recovery_demo":
        mode = RecoveryDemoPayload.model_validate(payload).mode
        if mode == "hang" or attempt == 1:
            Event().wait()
        return {"recovered_on_attempt": attempt}
    if job_type != "word_count":
        raise JobError(f"Unsupported job type: {job_type}")
    words = WordCountPayload.model_validate(payload).text.split()
    if not words:
        raise JobError("Text must contain at least one word.")
    return {"word_count": len(words)}


def retry_delay(attempt: int, base_seconds: float, max_seconds: float) -> float:
    """Return the delay after a failed attempt. Attempts are numbered from one."""
    return min(max_seconds, base_seconds * 2 ** (attempt - 1))
