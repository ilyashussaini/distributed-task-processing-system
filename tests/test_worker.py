from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from time import monotonic, sleep
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError
from sqlalchemy import func, select, update

from task_system import worker as worker_module
from task_system.api import create_app
from task_system.execution import AttemptProcessError
from task_system.jobs import run_job
from task_system.models import Job, JobStatus

pytestmark = pytest.mark.integration


def change_deadlines(store, job_id, **values):
    with store.sessions.begin() as session:
        session.execute(update(Job).where(Job.id == job_id).values(**values))


def make_retry_due(store, job_id):
    change_deadlines(store, job_id, dispatch_after=func.now(), available_at=func.now())


def database_time(store):
    with store.sessions() as session:
        return session.scalar(select(func.clock_timestamp()))


def test_worker_completes_api_job_and_ignores_duplicate_delivery(engine, store, worker_factory):
    worker = worker_factory()
    with TestClient(create_app(store.settings, engine=engine)) as client:
        response = client.post(
            "/jobs", json={"type": "word_count", "payload": {"text": "three example words"}}
        )
        job_id = UUID(response.json()["id"])
        assert worker.run_once()
        worker.broker.publish([job_id])
        assert worker.run_once()

        job = client.get(response.headers["location"]).json()
        assert job["status"] == "completed"
        assert job["attempts"] == 1
        assert job["result"] == {"word_count": 3}
        assert job["error"] is None
        assert job["completed_at"] >= job["created_at"]
        assert job["next_attempt_at"] is None

    broker = worker.broker
    assert broker.client.xpending(broker.stream, broker.group)["pending"] == 0
    assert broker.client.xlen(broker.stream) == 0


def test_two_workers_can_run_distinct_jobs_concurrently(store, worker_factory, monkeypatch):
    jobs = [store.create("word_count", {"text": text}) for text in ("one", "two words")]
    workers = [worker_factory(), worker_factory()]
    started = Barrier(3)
    release = Event()

    def wait_and_run(_job_id, job_type, payload, _attempt, _timeout):
        started.wait(timeout=5)
        assert release.wait(timeout=5)
        return run_job(job_type, payload)

    monkeypatch.setattr(worker_module, "execute_attempt", wait_and_run)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker.run_once) for worker in workers]
        try:
            started.wait(timeout=5)
            assert all(store.get(job.id).status == JobStatus.RUNNING for job in jobs)
        finally:
            release.set()
        assert all(future.result(timeout=5) for future in futures)

    completed = [store.get(job.id) for job in jobs]
    assert all(job.status == JobStatus.COMPLETED and job.attempts == 1 for job in completed)
    assert [job.result for job in completed] == [{"word_count": 1}, {"word_count": 2}]


def test_heartbeats_keep_long_running_attempt_exclusive(store, worker_factory, monkeypatch):
    first, second = worker_factory(), worker_factory()
    # Use a short database lease while keeping the normal Redis reclaim idle time.
    store.settings.lease_seconds = 2
    job = store.create("word_count", {"text": "slow job"})
    started = Event()
    release = Event()
    calls = []

    def slow_job(_job_id, job_type, payload, _attempt, _timeout):
        calls.append(job_type)
        if len(calls) == 1:
            started.set()
            assert release.wait(timeout=10)
        return run_job(job_type, payload)

    monkeypatch.setattr(worker_module, "execute_attempt", slow_job)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(first.run_once)
        try:
            assert started.wait(timeout=5)
            initial_expiry = store.get(job.id).lease_expires_at
            deadline = monotonic() + 5
            while database_time(store) < initial_expiry:
                assert monotonic() < deadline, "Database clock did not reach the initial expiry"
                sleep(0.05)

            second.broker.publish([job.id])
            assert second.run_once()
            current = store.get(job.id)
            assert current.status == JobStatus.RUNNING
            assert current.attempts == 1
            assert current.lease_expires_at > initial_expiry
        finally:
            release.set()
        assert future.result(timeout=5)

    assert calls == ["word_count"]
    completed = store.get(job.id)
    assert completed.status == JobStatus.COMPLETED
    assert completed.result == {"word_count": 2}


def test_worker_retries_with_backoff_then_fails_without_stopping(store, worker_factory):
    worker = worker_factory()
    job = store.create("word_count", {"text": " \t"})

    for attempt, seconds in [(1, 10), (2, 20)]:
        before = database_time(store)
        assert worker.run_once()
        after = database_time(store)
        pending = store.get(job.id)
        assert pending.status == JobStatus.PENDING
        assert pending.attempts == attempt
        assert pending.error == "Text must contain at least one word."
        assert pending.completed_at is None
        delay = timedelta(seconds=seconds)
        assert before + delay <= pending.available_at <= after + delay
        worker.broker.publish([job.id])
        assert worker.run_once()
        after_duplicate = store.get(job.id)
        assert after_duplicate.status == JobStatus.PENDING
        assert after_duplicate.attempts == attempt
        assert after_duplicate.available_at == pending.available_at
        assert not worker.run_once()
        make_retry_due(store, job.id)

    assert worker.run_once()
    failed = store.get(job.id)
    assert failed.status == JobStatus.FAILED
    assert failed.attempts == failed.max_attempts == 3
    assert failed.error == "Text must contain at least one word."
    assert failed.result is None
    assert failed.completed_at is not None

    valid = store.create("word_count", {"text": "still running"})
    assert worker.run_once()
    assert store.get(valid.id).status == JobStatus.COMPLETED


def test_transient_handler_error_can_recover_on_retry(store, worker_factory, monkeypatch):
    worker = worker_factory()
    job = store.create("word_count", {"text": "retry succeeded"})

    def raise_error(*_args):
        raise AttemptProcessError("internal details")

    with monkeypatch.context() as patch:
        patch.setattr(worker_module, "execute_attempt", raise_error)
        assert worker.run_once()
    assert store.get(job.id).error == "Unexpected job error."
    make_retry_due(store, job.id)

    assert worker.run_once()
    complete = store.get(job.id)
    assert complete.status == JobStatus.COMPLETED
    assert complete.attempts == 2
    assert complete.error is None
    assert complete.result == {"word_count": 2}


def test_execution_timeout_retries_and_worker_stays_available(store, worker_factory):
    normal_timeout = store.settings.attempt_timeout_seconds
    store.settings.attempt_timeout_seconds = 1
    worker = worker_factory()
    job = store.create("recovery_demo", {"mode": "abandon_first_attempt"})

    before = database_time(store)
    assert worker.run_once()
    after = database_time(store)
    pending = store.get(job.id)
    assert pending.status == JobStatus.PENDING
    assert pending.error == "Attempt exceeded its 1s execution deadline."
    assert pending.attempts == 1
    delay = timedelta(seconds=store.settings.retry_base_seconds)
    assert before + delay <= pending.available_at <= after + delay
    assert not worker.run_once()

    store.settings.attempt_timeout_seconds = normal_timeout
    make_retry_due(store, job.id)
    assert worker.run_once()
    completed = store.get(job.id)
    assert completed.status == JobStatus.COMPLETED
    assert completed.result == {"recovered_on_attempt": 2}
    assert completed.error is None


def test_failed_publish_rolls_back_dispatch_and_job_is_delivered(store, worker_factory):
    job = store.create("word_count", {"text": "broker recovered"})

    def unavailable(_ids):
        raise ConnectionError("Redis unavailable")

    with pytest.raises(ConnectionError):
        store.dispatch_due(unavailable)
    assert store.get(job.id).dispatch_after == job.dispatch_after

    assert worker_factory().run_once()
    assert store.get(job.id).status == JobStatus.COMPLETED


def test_worker_reclaims_message_left_unacknowledged(store, worker_factory):
    first = worker_factory().broker
    job = store.create("word_count", {"text": "reclaimed"})
    assert store.dispatch_due(first.publish) == 1
    message = first.read(block_ms=20)
    # Simulate a worker exit after receiving the message and before claiming the job.
    first.client.xclaim(
        first.stream, first.group, first.consumer, 0, [message.id], idle=first.reclaim_ms,
    )

    assert worker_factory().run_once()
    assert store.get(job.id).status == JobStatus.COMPLETED
    assert first.client.xpending(first.stream, first.group)["pending"] == 0


def test_lost_acknowledgment_does_not_repeat_completed_job(store, worker_factory, monkeypatch):
    first = worker_factory()
    job = store.create("word_count", {"text": "completed once"})

    def lose_ack(message):
        raise ConnectionError(f"Redis unavailable while acknowledging {message.id}")

    monkeypatch.setattr(first.broker, "acknowledge", lose_ack)
    with pytest.raises(ConnectionError):
        first.run_once()
    assert store.get(job.id).status == JobStatus.COMPLETED

    broker = first.broker
    pending = broker.client.xpending_range(broker.stream, broker.group, "-", "+", count=1)
    [delivery] = pending
    broker.client.xclaim(
        broker.stream, broker.group, broker.consumer, 0,
        [delivery["message_id"]], idle=broker.reclaim_ms,
    )
    assert worker_factory().run_once()
    completed = store.get(job.id)
    assert completed.status == JobStatus.COMPLETED
    assert completed.attempts == 1
    assert completed.result == {"word_count": 2}
    assert broker.client.xpending(broker.stream, broker.group)["pending"] == 0
    assert broker.client.xlen(broker.stream) == 0


def test_job_is_redispatched_after_stream_is_lost(store, worker_factory):
    first = worker_factory().broker
    job = store.create("word_count", {"text": "still durable"})
    assert store.dispatch_due(first.publish) == 1
    first.client.delete(first.stream)
    change_deadlines(store, job.id, dispatch_after=func.now())

    assert worker_factory().run_once()
    assert store.get(job.id).status == JobStatus.COMPLETED


def test_expired_lease_is_retried_and_old_attempt_cannot_commit(store):
    job = store.create("word_count", {"text": "worker lost"})
    first_attempt = store.claim(job.id)
    change_deadlines(store, job.id, lease_expires_at=func.now())
    assert not store.renew_lease(first_attempt)
    assert not store.complete(first_attempt, {"word_count": 999})
    assert not store.fail(first_attempt, "stale failure")
    assert store.get(job.id).status == JobStatus.RUNNING
    assert store.recover_expired() == 1
    pending = store.get(job.id)
    assert pending.status == JobStatus.PENDING
    assert pending.error == "Worker lease expired."
    assert store.claim(job.id) is None

    make_retry_due(store, job.id)
    second_attempt = store.claim(job.id)
    assert second_attempt.attempts == 2
    assert not store.renew_lease(first_attempt)
    assert not store.complete(first_attempt, {"word_count": 999})
    assert not store.fail(first_attempt, "stale failure")
    assert store.complete(second_attempt, {"word_count": 2})
    assert store.get(job.id).result == {"word_count": 2}


def test_final_expired_lease_marks_job_failed(store):
    store.settings.max_attempts = 1
    job = store.create("word_count", {"text": "one chance"})
    assert store.claim(job.id) is not None
    change_deadlines(store, job.id, lease_expires_at=func.now())

    assert store.recover_expired() == 1
    failed = store.get(job.id)
    assert failed.status == JobStatus.FAILED
    assert failed.attempts == 1
    assert failed.error == "Worker lease expired."
    assert failed.completed_at is not None
