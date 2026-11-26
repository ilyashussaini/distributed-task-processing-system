"""Prune expired terminal jobs in short transactions."""

import argparse
import logging
from datetime import timedelta
from time import sleep

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from task_system.config import Settings
from task_system.db import make_engine, make_sessions
from task_system.models import Job, JobStatus

log = logging.getLogger(__name__)
BATCH_SIZE = 300


def prune_jobs(sessions: sessionmaker[Session], days: int) -> int:
    if days < 1:
        raise ValueError("Retention must be at least one day.")
    cutoff = func.now() - timedelta(days=days)
    expired = (
        select(Job.id)
        .where(Job.status.in_((JobStatus.COMPLETED, JobStatus.FAILED)), Job.completed_at < cutoff)
        .order_by(Job.completed_at, Job.id)
        .limit(BATCH_SIZE)
        .with_for_update(skip_locked=True)
    )
    removed = 0
    while True:
        with sessions.begin() as session:
            result = session.execute(delete(Job).where(Job.id.in_(expired)).execution_options(synchronize_session=False))
            batch = result.rowcount
        removed += batch
        if batch < BATCH_SIZE:
            return removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", action="store_true", help="Run every six hours.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    settings = Settings()
    engine = make_engine(settings)
    try:
        sessions = make_sessions(engine)
        while True:
            log.info("Pruned %d terminal jobs past %d days", prune_jobs(sessions, settings.retention_days), settings.retention_days)
            if not args.loop:
                return
            sleep(6 * 3600)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
