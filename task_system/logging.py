import json
import logging
from datetime import UTC, datetime


class WorkerLogFormatter(logging.Formatter):
    def __init__(self, worker: str):
        super().__init__()
        self.worker = worker

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
                "level": record.levelname.lower(),
                "worker": self.worker,
                "event": record.getMessage(),
                **getattr(record, "event_fields", {}),
            }
        )


def log_event(logger: logging.Logger, event: str, *, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"event_fields": fields})
