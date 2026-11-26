from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from deploy.init_secrets import create_secrets
from task_system import retention
from task_system.models import Job, JobAttempt


def test_compose_secrets_have_restricted_parent_and_preserve_existing_files(tmp_path):
    secret_dir = tmp_path / "secrets"
    create_secrets(secret_dir, "$2a$14$" + "A" * 53)
    assert secret_dir.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o444 for path in secret_dir.iterdir())
    redis_password = (secret_dir / "redis_password").read_text().strip()
    assert f">{redis_password} " in (secret_dir / "redis_acl").read_text()
    token = (secret_dir / "api_token").read_text()
    with pytest.raises(FileExistsError):
        create_secrets(secret_dir, "$2a$14$" + "B" * 53)
    assert token == (secret_dir / "api_token").read_text()


@pytest.mark.integration
def test_retention_deletes_old_terminal_jobs_and_attempts_in_batches(store, monkeypatch):
    old_success = store.create("word_count", {"text": "test"})
    old_failure = store.create("word_count", {"text": "test"})
    recent = store.create("word_count", {"text": "test"})
    pending = store.create("word_count", {"text": "test"})
    running = store.create("word_count", {"text": "test"})
    assert store.complete(store.claim(old_success.id), {"word_count": 1})
    assert store.fail(store.claim(old_failure.id), "failure", retryable=False)
    assert store.complete(store.claim(recent.id), {"word_count": 1})
    assert store.claim(running.id)

    with store.sessions.begin() as session:
        session.execute(update(Job).values(created_at=func.now() - timedelta(days=40)))
        session.execute(
            update(Job).where(Job.id.in_((old_success.id, old_failure.id)))
            .values(completed_at=func.now() - timedelta(days=31))
        )

    monkeypatch.setattr(retention, "BATCH_SIZE", 1)
    assert retention.prune_jobs(store.sessions, 30) == 2
    assert retention.prune_jobs(store.sessions, 30) == 0
    assert {job.id for job in store.list_jobs(10, 0)} == {recent.id, pending.id, running.id}
    with store.sessions() as session:
        attempts = session.scalars(select(JobAttempt.job_id)).all()
    assert set(attempts) == {recent.id, running.id}
