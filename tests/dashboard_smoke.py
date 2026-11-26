"""Verify the built dashboard and its same-origin API proxy."""

from urllib.request import urlopen

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
    print("Dashboard smoke test passed through the same-origin proxy.")


if __name__ == "__main__":
    main()
