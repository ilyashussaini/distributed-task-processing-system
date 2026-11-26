import logging
import signal
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Event, Thread
from uuid import UUID, uuid4

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from task_system.broker import Message, RedisBroker
from task_system.config import Settings
from task_system.db import make_engine, make_sessions
from task_system.jobs import JobError, run_job
from task_system.models import Job
from task_system.store import JobStore

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, store: JobStore, broker: RedisBroker):
        self.store = store
        self.broker = broker

    def run_once(self) -> bool:
        self.store.recover_expired()
        self.store.dispatch_due(self.broker.publish)
        message = self.broker.read(self.store.settings.poll_ms)
        if message is None:
            return False
        self._process(message)
        self.broker.acknowledge(message)
        return True

    def _process(self, message: Message) -> None:
        try:
            job_id = UUID(message.job_id or "")
        except ValueError:
            logger.warning("Discarding invalid Redis message %s", message.id)
            return

        job = self.store.claim(job_id)
        if job is None:
            return
        logger.info("Running job %s (attempt %s of %s)", job.id, job.attempts, job.max_attempts)
        with self._keep_lease_alive(job):
            self._execute(job)

    def _execute(self, job: Job) -> None:
        try:
            result = run_job(job.type, job.payload)
        except JobError as exc:
            logger.info("Job %s failed on attempt %s: %s", job.id, job.attempts, exc)
            recorded = self.store.fail(job, str(exc))
        except Exception:
            logger.exception("Unexpected error executing job %s", job.id)
            recorded = self.store.fail(job, "Unexpected job error.")
        else:
            recorded = self.store.complete(job, result)
        if not recorded:
            logger.warning(
                "Discarding outcome for job %s after attempt %s lost its lease", job.id, job.attempts
            )

    @contextmanager
    def _keep_lease_alive(self, job: Job) -> Iterator[None]:
        finished = Event()
        interval = self.store.settings.lease_seconds / 3

        def heartbeat() -> None:
            while not finished.wait(interval):
                try:
                    if not self.store.renew_lease(job):
                        return
                except SQLAlchemyError as exc:
                    logger.warning(
                        "Could not renew lease for job %s (%s)", job.id, type(exc).__name__
                    )

        thread = Thread(target=heartbeat, name="lease-heartbeat")
        thread.start()
        try:
            yield
        finally:
            finished.set()
            thread.join()

    def run(self, stop: Event) -> None:
        while not stop.is_set():
            try:
                self.broker.ensure_group()
                while not stop.is_set():
                    self.run_once()
            except (RedisError, SQLAlchemyError) as exc:
                logger.warning("Worker dependency unavailable (%s). Retrying.", type(exc).__name__)
                stop.wait(1)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings()
    engine = make_engine(settings)
    stop = Event()

    def stop_worker(_signum, _frame):
        stop.set()

    signal.signal(signal.SIGTERM, stop_worker)
    signal.signal(signal.SIGINT, stop_worker)
    consumer = f"{socket.gethostname()}-{uuid4().hex}"
    logger.info("Starting worker %s", consumer)
    try:
        with Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=4,
        ) as client:
            broker = RedisBroker(
                client, settings.redis_stream, consumer, int(settings.lease_seconds * 1000)
            )
            Worker(JobStore(make_sessions(engine), settings), broker).run(stop)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
