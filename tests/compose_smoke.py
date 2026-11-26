"""Check the live Compose stack with only the Python standard library."""

import json
import os
from time import monotonic, sleep
from urllib.request import Request, urlopen

BASE_URL = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def submit(text: str) -> str:
    request = Request(
        f"{BASE_URL}/jobs",
        data=json.dumps({"type": "word_count", "payload": {"text": text}}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        assert response.status == 202
        job = json.load(response)
        assert job["status"] == "pending"
        location = response.headers["Location"]
        assert location == f"/jobs/{job['id']}"
        return location


def read(path: str):
    with urlopen(f"{BASE_URL}{path}", timeout=5) as response:
        assert response.status == 200
        return json.load(response)


def wait_for_terminal(path: str) -> dict:
    deadline = monotonic() + 30
    while monotonic() < deadline:
        job = read(path)
        if job["status"] in {"completed", "failed"}:
            assert job["completed_at"]
            return job
        sleep(0.2)
    raise AssertionError(f"Job did not reach a terminal state: {path}")


def main() -> None:
    completed = wait_for_terminal(submit("Hello background workers"))
    assert completed["status"] == "completed"
    assert completed["attempts"] == 1
    assert completed["result"] == {"word_count": 3}

    failed = wait_for_terminal(submit("   "))
    assert failed["status"] == "failed"
    assert failed["attempts"] == 3
    assert failed["error"] == "Text must contain at least one word."

    ids = [job["id"] for job in read("/jobs?limit=2")]
    assert ids == [failed["id"], completed["id"]]
    print("Compose smoke test passed: submission, processing, retries, and listing.")


if __name__ == "__main__":
    main()
