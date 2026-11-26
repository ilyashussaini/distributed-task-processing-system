import logging
import signal
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Event, Thread
from time import monotonic
from uuid import UUID, uuid4

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from task_system.broker import Message, RedisBroker
from task_system.config import Settings
from task_system.csv_sales import InvalidCSV
from task_system.db import make_engine, make_sessions
from task_system.execution import AttemptProcessError, AttemptTimeout, execute_attempt
from task_system.jobs import JobError
from task_system.logging import WorkerLogFormatter, log_event
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
            log_event(logger, "invalid_message", level=logging.WARNING, message_id=message.id)
            return

        job = self.store.claim(job_id)
        if job is None:
            return
        with self._keep_lease_alive(job):
            self._execute(job)

    def _execute(self, job: Job) -> None:
        fields = {"job_id": str(job.id), "attempt": job.attempts}
        timeout = self.store.settings.attempt_timeout_seconds
        log_event(logger, "attempt_started", job_type=job.type, timeout_seconds=timeout, **fields)
        started = monotonic()
        try:
            result = execute_attempt(job.id, job.type, job.payload, job.attempts, timeout)
        except AttemptTimeout as exc:
            duration_ms = (monotonic() - started) * 1000
            log_event(
                logger, "attempt_timed_out", level=logging.WARNING,
                child_pid=exc.pid, exit_code=exc.exit_code, timeout_seconds=timeout, **fields,
            )
            self._record_failure(job, str(exc), "timeout", duration_ms)
        except JobError as exc:
            self._record_failure(job, str(exc), "handler_error", (monotonic() - started) * 1000)
        except InvalidCSV as exc:
            self._record_failure(
                job, str(exc), "invalid_csv", (monotonic() - started) * 1000, retryable=False,
            )
        except (AttemptProcessError, OSError) as exc:
            duration_ms = (monotonic() - started) * 1000
            log_event(logger, "handler_process_error", level=logging.ERROR, error=str(exc), **fields)
            self._record_failure(job, "Unexpected job error.", "process_error", duration_ms)
        else:
            if self.store.complete(job, result, duration_ms=(monotonic() - started) * 1000):
                log_event(logger, "attempt_completed", **fields)
            else:
                log_event(logger, "attempt_outcome_discarded", level=logging.WARNING, **fields)

    def _record_failure(
        self, job: Job, error: str, reason: str, duration_ms: float, *, retryable: bool = True,
    ) -> None:
        fields = {"job_id": str(job.id), "attempt": job.attempts}
        if self.store.fail(job, error, duration_ms=duration_ms, retryable=retryable):
            log_event(
                logger, "attempt_failed", reason=reason,
                will_retry=retryable and job.attempts < job.max_attempts, **fields,
            )
        else:
            log_event(logger, "attempt_outcome_discarded", level=logging.WARNING, **fields)

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
                    log_event(
                        logger, "lease_renewal_failed", level=logging.WARNING,
                        job_id=str(job.id), attempt=job.attempts, error_type=type(exc).__name__,
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
                log_event(
                    logger, "dependency_unavailable", level=logging.WARNING,
                    error_type=type(exc).__name__,
                )
                stop.wait(1)


def main() -> None:
    hostname = socket.gethostname()
    handler = logging.StreamHandler()
    handler.setFormatter(WorkerLogFormatter(hostname))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    settings = Settings()
    engine = make_engine(settings)
    stop = Event()

    def stop_worker(_signum, _frame):
        stop.set()

    signal.signal(signal.SIGTERM, stop_worker)
    signal.signal(signal.SIGINT, stop_worker)
    consumer = f"{hostname}-{uuid4().hex}"
    log_event(logger, "worker_started", consumer=consumer)
    redis_url, redis_password = settings.redis_connection
    try:
        with Redis.from_url(
            redis_url,
            password=redis_password,
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
