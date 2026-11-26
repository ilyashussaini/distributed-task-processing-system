"""Exercise and measure timeout and worker-loss recovery in a two-worker stack."""

import argparse
import json
from collections.abc import Callable
from datetime import UTC, datetime
from subprocess import run
from time import monotonic, sleep
from typing import Any

from compose_smoke import read, submit, wait_for_terminal


def command(*args: str) -> str:
    result = run(args, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"{' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def eventually[T](condition: Callable[[], T | None], description: str) -> T:
    deadline = monotonic() + 20
    while monotonic() < deadline:
        if value := condition():
            return value
        sleep(0.1)
    raise AssertionError(f"Timed out waiting for {description}")


def event(compose: list[str], job_id: str, name: str, attempt: int) -> dict[str, Any]:
    def find():
        logs = command(*compose, "logs", "--no-color", "--no-log-prefix", "worker")
        for line in logs.splitlines():
            if line.startswith("{"):
                entry = json.loads(line)
                if (entry.get("job_id"), entry.get("event"), entry.get("attempt")) == (
                    job_id, name, attempt,
                ):
                    return entry
        return None

    return eventually(find, f"{name} for job {job_id}, attempt {attempt}")


def word_count() -> dict[str, Any]:
    job = wait_for_terminal(submit("word_count", {"text": "unrelated work completes"}))
    assert job["status"] == "completed" and job["attempts"] == 1
    assert job["result"] == {"word_count": 3}
    return job


def hung_handler(compose: list[str]) -> None:
    path = submit("recovery_demo", {"mode": "hang"})
    job_id = read(path)["id"]
    first = event(compose, job_id, "handler_process_started", 1)
    unrelated = word_count()
    timeout = event(compose, job_id, "attempt_timed_out", 1)
    assert datetime.fromisoformat(unrelated["completed_at"]) < datetime.fromisoformat(
        timeout["timestamp"]
    )
    assert timeout["child_pid"] == first["child_pid"] and timeout["exit_code"] == -9

    job = wait_for_terminal(path)
    assert job["status"] == "failed" and job["attempts"] == 2
    second_timeout = event(compose, job_id, "attempt_timed_out", 2)
    assert second_timeout["exit_code"] == -9
    duration = datetime.fromisoformat(timeout["timestamp"]) - datetime.fromisoformat(first["timestamp"])
    print(
        f"Hung handler {job_id}: child {timeout['child_pid']} was killed in "
        f"{duration.total_seconds():.2f}s. Unrelated work completed before the deadline. "
        "The job failed after two timed-out attempts.",
        flush=True,
    )


def killed_worker(compose: list[str], containers: dict[str, str]) -> None:
    path = submit("recovery_demo", {"mode": "abandon_first_attempt"})
    job_id = read(path)["id"]
    first = event(compose, job_id, "handler_process_started", 1)
    container = containers[first["worker"]]
    command("docker", "kill", "--signal", "KILL", container)
    killed_at = datetime.now(UTC)
    try:
        assert command("docker", "inspect", "--format", "{{.State.ExitCode}}", container) == "137"
        unrelated = word_count()
        recovered = event(compose, job_id, "expired_attempt_recovered", 1)
        assert recovered["will_retry"] and recovered["worker"] != first["worker"]

        job = wait_for_terminal(path)
        assert job["status"] == "completed" and job["attempts"] == 2
        assert job["result"] == {"recovered_on_attempt": 2}
        completion = event(compose, job_id, "attempt_completed", 2)
        assert completion["worker"] == recovered["worker"]
        assert datetime.fromisoformat(unrelated["completed_at"]) < datetime.fromisoformat(
            job["completed_at"]
        )

        recovery = datetime.fromisoformat(recovered["timestamp"]) - killed_at
        finish = datetime.fromisoformat(job["completed_at"]) - killed_at
        print(
            f"Killed worker {first['worker']} during job {job_id}: worker {recovered['worker']} "
            f"recovered the lease in {recovery.total_seconds():.2f}s and completed attempt 2 in "
            f"{finish.total_seconds():.2f}s. Unrelated work completed first.",
            flush=True,
        )
    finally:
        command("docker", "start", container)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Compose project running the recovery override")
    parser.add_argument("--scenario", choices=("timeout", "worker-loss", "both"), default="both")
    args = parser.parse_args()
    compose = ["docker", "compose", "-p", args.project]
    ids = command(*compose, "ps", "--status", "running", "-q", "worker").splitlines()
    assert len(ids) == 2, "Start exactly two worker replicas with compose.recovery.yaml"
    containers = {
        command("docker", "inspect", "--format", "{{.Config.Hostname}}", container): container
        for container in ids
    }
    if args.scenario in ("timeout", "both"):
        hung_handler(compose)
    if args.scenario in ("worker-loss", "both"):
        killed_worker(compose, containers)


if __name__ == "__main__":
    main()
