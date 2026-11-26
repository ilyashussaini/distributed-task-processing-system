import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from redis import Redis
from sqlalchemy import create_engine

from task_system.broker import RedisBroker
from task_system.config import Settings
from task_system.db import make_sessions
from task_system.store import JobStore
from task_system.worker import Worker


@pytest.fixture(scope="session")
def database_url():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return url


@pytest.fixture
def engine(database_url):
    schema = f"test_jobs_{uuid4().hex}"
    admin = create_engine(database_url)
    try:
        with admin.begin() as connection:
            connection.exec_driver_sql(f"CREATE SCHEMA {schema}")
        db = create_engine(database_url, connect_args={"options": f"-csearch_path={schema}"})
        try:
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            with db.begin() as connection:
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
            yield db
        finally:
            db.dispose()
            with admin.begin() as connection:
                connection.exec_driver_sql(f"DROP SCHEMA {schema} CASCADE")
    finally:
        admin.dispose()


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        redis_stream=f"test-task-system:{uuid4().hex}",
        max_attempts=3,
        retry_base_seconds=10,
        retry_max_seconds=60,
        lease_seconds=30,
        redispatch_seconds=15,
        poll_ms=20,
    )


@pytest.fixture
def store(engine, settings):
    return JobStore(make_sessions(engine), settings)


@pytest.fixture
def redis_client(settings):
    url = os.getenv("TEST_REDIS_URL")
    if not url:
        pytest.skip("TEST_REDIS_URL is required for Redis integration tests")
    with Redis.from_url(url, decode_responses=True, socket_timeout=3) as client:
        client.ping()
        try:
            yield client
        finally:
            client.delete(settings.redis_stream)


@pytest.fixture
def worker_factory(store, redis_client):
    def make_worker():
        broker = RedisBroker(
            redis_client,
            store.settings.redis_stream,
            uuid4().hex,
            int(store.settings.lease_seconds * 1000),
        )
        broker.ensure_group()
        return Worker(store, broker)

    return make_worker
