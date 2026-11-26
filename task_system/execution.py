"""Run a trusted handler in a fresh interpreter with a bounded lifetime."""

import json
import logging
import signal
import sys
from contextlib import redirect_stdout
from subprocess import DEVNULL, PIPE, Popen, TimeoutExpired
from time import monotonic
from typing import Any
from uuid import UUID

from task_system.jobs import JobError, run_job
from task_system.logging import log_event

logger = logging.getLogger(__name__)


class AttemptTimeout(Exception):
    def __init__(self, seconds: float, pid: int, exit_code: int):
        super().__init__(f"Attempt exceeded its {seconds:g}s execution deadline.")
        self.pid = pid
        self.exit_code = exit_code


class AttemptProcessError(Exception):
    """The child interpreter exited without a valid handler outcome."""


def execute_attempt(
    job_id: UUID, job_type: str, payload: dict[str, Any], attempt: int, timeout_seconds: float
) -> dict[str, Any]:
    request = json.dumps({"type": job_type, "payload": payload, "attempt": attempt}).encode()
    deadline = monotonic() + timeout_seconds
    with Popen(
        [sys.executable, "-m", "task_system.execution", str(timeout_seconds)],
        stdin=PIPE,
        stdout=PIPE,
        stderr=DEVNULL,
    ) as process:
        log_event(
            logger, "handler_process_started", job_id=str(job_id), attempt=attempt, child_pid=process.pid,
        )
        try:
            output, _ = process.communicate(request, timeout=max(0, deadline - monotonic()))
        except TimeoutExpired:
            process.kill()
            exit_code = process.wait()
            raise AttemptTimeout(timeout_seconds, process.pid, exit_code) from None
        if hasattr(signal, "SIGALRM") and process.returncode == -signal.SIGALRM:
            raise AttemptTimeout(timeout_seconds, process.pid, process.returncode)
        if process.returncode != 0:
            raise AttemptProcessError(f"Handler process exited with code {process.returncode}.")

    try:
        reply = json.loads(output)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AttemptProcessError("Handler process returned invalid JSON.") from exc
    if isinstance(reply, dict):
        if isinstance(reply.get("error"), str):
            raise JobError(reply["error"])
        if isinstance(reply.get("result"), dict):
            return reply["result"]
    raise AttemptProcessError("Handler process returned an invalid outcome.")


def main() -> None:
    if hasattr(signal, "setitimer"):
        # Bound the direct child's lifetime if a standalone POSIX worker is killed.
        # The parent gets the first opportunity to terminate it and record the timeout.
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
        signal.setitimer(signal.ITIMER_REAL, float(sys.argv[1]) + 1)

    request = json.load(sys.stdin)
    try:
        with redirect_stdout(sys.stderr):
            result = run_job(request["type"], request["payload"], attempt=request["attempt"])
    except JobError as exc:
        reply = {"error": str(exc)}
    else:
        reply = {"result": result}
    json.dump(reply, sys.stdout)


if __name__ == "__main__":
    main()
