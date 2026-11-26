from dataclasses import dataclass
from uuid import UUID

from redis import Redis
from redis.exceptions import ResponseError


@dataclass(frozen=True)
class Message:
    id: str
    job_id: str | None


class RedisBroker:
    group = "workers"

    def __init__(self, client: Redis, stream: str, consumer: str, reclaim_ms: int):
        self.client = client
        self.stream = stream
        self.consumer = consumer
        self.reclaim_ms = reclaim_ms
        self.reclaim_cursor = "0-0"

    def ensure_group(self) -> None:
        try:
            self.client.xgroup_create(self.stream, self.group, id="0-0", mkstream=True)
        except ResponseError as exc:
            if not str(exc).startswith("BUSYGROUP"):
                raise

    def publish(self, job_ids: list[UUID]) -> None:
        with self.client.pipeline() as pipe:
            for job_id in job_ids:
                pipe.xadd(self.stream, {"job_id": str(job_id)})
            pipe.execute()

    def read(self, block_ms: int) -> Message | None:
        cursor, reclaimed, _ = self.client.xautoclaim(
            self.stream, self.group, self.consumer, self.reclaim_ms,
            self.reclaim_cursor, count=1,
        )
        self.reclaim_cursor = cursor
        if reclaimed:
            message_id, fields = reclaimed[0]
            return Message(message_id, fields.get("job_id"))

        streams = self.client.xreadgroup(
            self.group, self.consumer, {self.stream: ">"}, count=1, block=block_ms
        )
        if streams:
            message_id, fields = streams[0][1][0]
            return Message(message_id, fields.get("job_id"))
        return None

    def acknowledge(self, message: Message) -> None:
        # This stream belongs to a single group. Remove entries after acknowledgment.
        with self.client.pipeline() as pipe:
            pipe.xack(self.stream, self.group, message.id)
            pipe.xdel(self.stream, message.id)
            pipe.execute()
