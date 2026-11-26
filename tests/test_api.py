from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from task_system.api import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
def client(engine, settings):
    with TestClient(create_app(settings, engine=engine)) as test_client:
        yield test_client


def test_submit_persists_job_and_returns_location(client, store):
    payload = {"text": "queued example"}
    response = client.post("/jobs", json={"type": "word_count", "payload": payload})
    assert response.status_code == 202
    job = response.json()
    assert response.headers["location"] == f"/jobs/{job['id']}"
    assert job["status"] == "pending"
    assert job["attempts"] == 0
    assert job["max_attempts"] == 3
    assert job["created_at"] == job["next_attempt_at"]
    assert job["completed_at"] is None
    assert job["result"] is None
    assert job["error"] is None

    persisted = store.get(UUID(job["id"]))
    assert persisted.payload == payload
    assert persisted.created_at.tzinfo is not None
    retrieved = client.get(response.headers["location"])
    assert retrieved.status_code == 200
    assert retrieved.json() == job


def test_list_returns_newest_first_and_supports_pagination(client):
    assert client.get("/jobs").json() == []
    body = {"type": "word_count", "payload": {"text": "one two"}}
    ids = [client.post("/jobs", json=body).json()["id"] for _ in range(3)]

    response = client.get("/jobs", params={"limit": 1, "offset": 1})
    assert response.status_code == 200
    assert [job["id"] for job in response.json()] == [ids[1]]
    assert [job["id"] for job in client.get("/jobs").json()] == ids[::-1]
    assert client.get("/jobs", params={"limit": 101}).status_code == 422
    assert client.get("/jobs", params={"offset": -1}).status_code == 422


def test_get_handles_unknown_and_invalid_ids(client):
    assert client.get(f"/jobs/{uuid4()}").status_code == 404
    assert client.get("/jobs/not-a-uuid").status_code == 422


@pytest.mark.parametrize(
    "job",
    [
        {"type": "unsupported", "payload": {"text": "valid"}},
        {"type": "word_count", "payload": {"text": ""}},
        {"type": "word_count", "payload": {"text": "x" * 100_001}},
        {"type": "word_count", "payload": {"text": 123}},
        {"type": "word_count", "payload": {"text": "valid", "unexpected": 1}},
    ],
    ids=["type", "empty", "length", "number", "extra"],
)
def test_submit_rejects_invalid_input(client, job):
    assert client.post("/jobs", json=job).status_code == 422
    assert client.get("/jobs").json() == []
