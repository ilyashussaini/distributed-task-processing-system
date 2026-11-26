"""Verify the built dashboard and its same-origin API proxy."""

import json
from pathlib import Path
from urllib.request import Request, urlopen

from compose_smoke import BASE_URL, read, submit, wait_for_terminal


def main() -> None:
    with urlopen(BASE_URL.removesuffix("/api"), timeout=5) as response:
        page = response.read().decode()
    assert "Taskflow" in page and '/assets/' in page

    path = submit("word_count", {"text": "dashboard proxy works"})
    job = wait_for_terminal(path)
    assert job["status"] == "completed" and job["result"] == {"word_count": 3}

    history = read(f"/monitoring/jobs?q={job['id']}&status=completed")
    assert history["total"] == 1 and history["jobs"][0]["id"] == job["id"]
    details = read(f"/monitoring/jobs/{job['id']}")
    assert details["job"]["id"] == job["id"]
    assert details["attempts"][0]["duration_ms"] > 0
    overview = read("/monitoring/overview?window=1h")
    assert overview["period"]["completed"] >= 1
    assert overview["period"]["duration"]["samples"] >= 1

    csv = Path(__file__).resolve().parents[1] / "benchmarks" / "sample-sales.csv"
    upload = Request(f"{BASE_URL}/jobs/csv", data=csv.read_bytes(), headers={"Content-Type": "text/csv"})
    with urlopen(upload, timeout=5) as response:
        assert response.status == 202
        assert json.load(response)["type"] == "csv_sales_summary"
        csv_location = response.headers["Location"]
    csv_job = wait_for_terminal(csv_location)
    assert csv_job["status"] == "completed"
    assert csv_job["result"]["revenue"] == "105.71"
    print("Dashboard smoke test passed through the same-origin proxy.")


if __name__ == "__main__":
    main()
