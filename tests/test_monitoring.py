from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, update

from task_system.api import create_app
from task_system.models import Job

pytestmark = pytest.mark.integration


@pytest.fixture
def client(engine, settings):
    with TestClient(create_app(settings, engine=engine)) as test_client:
        yield test_client


def change_job(store, job_id, **values):
    with store.sessions.begin() as session:
        session.execute(update(Job).where(Job.id == job_id).values(**values))


def test_empty_overview_has_no_implied_rates_or_durations(client):
    response = client.get("/monitoring/overview", params={"window": "1h"})
    assert response.status_code == 200
    data = response.json()
    assert data["counts"] == dict(total=0, pending=0, running=0, completed=0, failed=0)
    assert data["period"]["success_rate"] is None
    assert data["period"]["failure_rate"] is None
    assert data["period"]["duration"] == dict(
        samples=0, average_ms=None, minimum_ms=None, p95_ms=None, maximum_ms=None,
    )
    assert len(data["activity"]) == 12
    starts = [datetime.fromisoformat(bucket["start"]) for bucket in data["activity"]]
    assert starts[0] == datetime.fromisoformat(data["generated_at"]) - timedelta(hours=1)
    assert starts[1] - starts[0] == timedelta(minutes=5)
    assert all(bucket["submitted"] == bucket["completed"] == bucket["failed"] == 0
               for bucket in data["activity"])
    assert client.get("/monitoring/overview", params={"window": "invalid"}).status_code == 422


def test_overview_uses_terminal_timestamps_and_measured_attempts(client, store):
    assert store.settings.max_attempts == 3
    retried = store.create("word_count", {"text": "retry and succeed"})
    assert store.fail(store.claim(retried.id), "Transient error.", duration_ms=25)
    change_job(store, retried.id, available_at=func.now(), dispatch_after=func.now())
    assert store.complete(store.claim(retried.id), {"word_count": 3}, duration_ms=75)

    store.settings.max_attempts = 1
    failed = store.create("word_count", {"text": " "})
    assert store.fail(store.claim(failed.id), "No words.", duration_ms=100)
    store.settings.max_attempts = 3

    abandoned = store.create("word_count", {"text": "worker lost"})
    old_claim = store.claim(abandoned.id)
    change_job(store, abandoned.id, lease_expires_at=func.now())
    assert store.recover_expired() == 1
    assert not store.complete(old_claim, {"word_count": 2}, duration_ms=999)

    running = store.create("word_count", {"text": "in progress"})
    assert store.claim(running.id)

    legacy = store.create("word_count", {"text": "legacy"})
    change_job(
        store, legacy.id,
        status="completed", attempts=2, created_at=func.now() - timedelta(hours=2), completed_at=func.now(),
    )

    response = client.get("/monitoring/overview", params={"window": "1h"})
    assert response.status_code == 200
    data = response.json()
    assert data["counts"] == dict(total=5, pending=1, running=1, completed=2, failed=1)
    period = data["period"]
    assert (period["submitted"], period["completed"], period["failed"]) == (4, 2, 1)
    assert period["success_rate"] == pytest.approx(2 / 3)
    assert period["failure_rate"] == pytest.approx(1 / 3)
    assert (period["retry_attempts"], period["retried_jobs"]) == (1, 1)
    assert (period["failed_attempts"], period["abandoned_attempts"]) == (2, 1)
    assert period["duration"] == pytest.approx(dict(
        samples=3, average_ms=200 / 3, minimum_ms=25, p95_ms=97.5, maximum_ms=100,
    ))
    assert data["activity"][-1]["completed"] == 2

    details = client.get(f"/monitoring/jobs/{abandoned.id}").json()
    assert details["job"]["status"] == "pending"
    assert details["job"]["next_attempt_at"]
    assert details["attempts"][0]["status"] == "abandoned"
    assert details["attempts"][0]["duration_ms"] is None
    assert details["attempts"][0]["error"] == "Worker lease expired."
    assert client.get(f"/monitoring/jobs/{legacy.id}").json()["attempts"] == []


def test_job_history_filters_searches_and_paginates(client, store):
    first = store.create("word_count", {"text": "first"})
    second = store.create("word_count", {"text": "second"})
    other = store.create("recovery_demo", {"mode": "hang"})
    assert store.complete(store.claim(second.id), {"word_count": 1})

    filtered = client.get("/monitoring/jobs", params={"q": "Word count", "limit": 1, "offset": 1})
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 2
    assert [job["id"] for job in filtered.json()["jobs"]] == [str(first.id)]
    pending = client.get("/monitoring/jobs", params={"status": "pending"}).json()
    assert pending["total"] == 2
    assert {job["id"] for job in pending["jobs"]} == {str(first.id), str(other.id)}
    by_id = client.get("/monitoring/jobs", params={"q": str(second.id)[:8], "status": "completed"}).json()
    assert by_id["total"] == 1
    assert by_id["jobs"][0]["id"] == str(second.id)
    assert client.get("/monitoring/jobs", params={"q": "%"}).json()["total"] == 0
    assert client.get("/monitoring/jobs", params={"status": "unknown"}).status_code == 422


def test_worker_job_details_include_measured_processing_time(client, store, worker_factory):
    job = store.create("word_count", {"text": "actual timing"})
    assert worker_factory().run_once()

    response = client.get(f"/monitoring/jobs/{job.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["job"]["result"] == {"word_count": 2}
    [attempt] = data["attempts"]
    assert attempt["number"] == 1
    assert attempt["status"] == "completed"
    assert attempt["duration_ms"] > 0
    assert datetime.fromisoformat(attempt["finished_at"]) >= datetime.fromisoformat(attempt["started_at"])
    assert client.get(f"/monitoring/jobs/{uuid4()}").status_code == 404


def test_attempt_migration_preserves_existing_jobs(client, engine, store):
    migration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with engine.begin() as connection:
        migration.attributes["connection"] = connection
        command.downgrade(migration, "0001")

    job = store.create("word_count", {"text": "existing job"})
    change_job(store, job.id, status="completed", attempts=1, completed_at=func.now(), result={"word_count": 2})

    with engine.begin() as connection:
        migration.attributes["connection"] = connection
        command.upgrade(migration, "head")

    result = client.get(f"/monitoring/jobs/{job.id}")
    assert result.status_code == 200
    assert result.json()["job"]["result"] == {"word_count": 2}
    assert result.json()["attempts"] == []
    assert client.get("/monitoring/overview").json()["period"]["duration"]["samples"] == 0
