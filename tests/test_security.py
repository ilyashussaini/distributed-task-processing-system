import json
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from task_system.api import create_app
from task_system.config import Settings
from task_system.security import MAX_BODY_BYTES

TOKEN = "test-api-token-with-32-ascii-characters"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BODY = {"type": "word_count", "payload": {"text": "authorized job"}}


def test_production_rejects_default_secrets_and_requires_https_origin():
    with pytest.raises(ValidationError, match="Production requires"):
        Settings(_env_file=None, app_env="production")

    config = dict(
        app_env="production", api_token=TOKEN, postgres_password="configured-test-password",
        redis_password="configured-redis-password", read_rate_per_minute=10, write_rate_per_minute=2,
    )
    with pytest.raises(ValidationError, match="HTTPS PUBLIC_ORIGIN"):
        Settings(_env_file=None, public_origin="http://tasks.example.com", **config)
    settings = Settings(_env_file=None, public_origin="https://tasks.example.com", **config)
    assert TOKEN not in repr(settings)
    assert "configured-test-password" not in repr(settings)


@pytest.mark.integration
def test_authentication_covers_job_and_monitoring_routes(engine):
    settings = Settings(_env_file=None, api_token=TOKEN, public_origin="https://tasks.example.com")
    with TestClient(create_app(settings, engine=engine)) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        for path in ("/jobs", "/monitoring/jobs", "/monitoring/overview"):
            rejection = client.get(path, headers={"Authorization": "Bearer unrelated"})
            assert rejection.status_code == 401
            assert rejection.headers["WWW-Authenticate"] == "Bearer"
        assert client.post("/jobs", json=BODY).status_code == 401
        assert client.post("/jobs/csv", content=b"example", headers={"Content-Type": "text/csv"}).status_code == 401

        cross_site = client.post("/jobs", headers={**AUTH, "Origin": "https://elsewhere.example"}, json=BODY)
        assert cross_site.status_code == 403
        assert client.get("/jobs", headers=AUTH).json() == []
        created = client.post("/jobs", headers={**AUTH, "Origin": "https://tasks.example.com"}, json=BODY)
        assert created.status_code == 202
        assert "no-store" in created.headers["Cache-Control"]
        assert client.get(created.headers["Location"], headers=AUTH).status_code == 200


@pytest.mark.integration
def test_json_body_limit_preserves_valid_word_count_limits(engine):
    settings = Settings(_env_file=None)
    with TestClient(create_app(settings, engine=engine)) as client:
        huge = b" " * (MAX_BODY_BYTES + 1)
        headers = {"Content-Type": "application/json"}
        assert client.post("/jobs", headers=headers, content=huge).status_code == 413
        assert client.post("/jobs", headers=headers, content=iter((huge[:1024], huge[1024:]))).status_code == 413
        assert client.get("/jobs").json() == []
        body = json.dumps({"type": "word_count", "payload": {"text": "\U0001f680" * 100_000}})
        assert client.post("/jobs", headers=headers, content=body).status_code == 202


@pytest.mark.integration
def test_redis_limits_are_shared_and_unauthorized_requests_use_no_quota(engine, redis_client):
    namespace = f"test-api-quota:{uuid.uuid4()}"
    settings = Settings(
        _env_file=None, redis_url=os.environ["TEST_REDIS_URL"], redis_stream=namespace,
        api_token=TOKEN, read_rate_per_minute=1, write_rate_per_minute=2,
    )
    try:
        with TestClient(create_app(settings, engine=engine)) as first, TestClient(create_app(settings, engine=engine)) as second:
            assert first.post("/jobs", json=BODY).status_code == 401
            assert first.post("/jobs", json=BODY, headers=AUTH).status_code == 202
            assert second.post("/jobs", json=BODY, headers=AUTH).status_code == 202
            response = first.post("/jobs", json=BODY, headers=AUTH)
            assert response.status_code == 429 and 1 <= int(response.headers["Retry-After"]) <= 60
            assert 0 < redis_client.ttl(f"{namespace}:http-quota:write") <= 60
            assert second.get("/jobs", headers=AUTH).status_code == 200
            assert first.get("/jobs", headers=AUTH).status_code == 429
            assert first.get("/healthz").status_code == 200
    finally:
        redis_client.delete(f"{namespace}:http-quota:read", f"{namespace}:http-quota:write")


@pytest.mark.integration
def test_configured_limits_fail_closed_when_redis_is_unavailable(engine, store):
    settings = Settings(_env_file=None, redis_url="redis://127.0.0.1:1/0", write_rate_per_minute=2)
    with TestClient(create_app(settings, engine=engine)) as client:
        assert client.post("/jobs", json=BODY).status_code == 503
        assert client.get("/healthz").status_code == 200
    assert store.list_jobs(10, 0) == []
