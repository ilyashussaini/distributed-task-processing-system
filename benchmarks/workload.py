"""A reproducible sales dataset generator and burst client."""

import csv
import json
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from time import monotonic, sleep
from urllib.request import Request, urlopen
from uuid import UUID

from psycopg import Connection

from benchmarks.metrics import Burst, Observation

REGIONS = ("Central", "North", "South", "West", "North East", "South East")
OBSERVATION_SQL = """
SELECT j.status, j.created_at, j.completed_at, a.started_at, a.duration_ms
FROM jobs AS j
LEFT JOIN job_attempts AS a ON a.job_id = j.id AND a.number = 1
WHERE j.id = ANY(%s)
"""


def sales_csv(rows: int) -> bytes:
    buffer = StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(("order_id", "region", "quantity", "unit_price"))
    for index in range(rows):
        cents = 100 + (index * 173 % 49_900)
        writer.writerow((
            f"order-{index:05d}", REGIONS[index % len(REGIONS)], 1 + (index * 7 % 25),
            f"{cents // 100}.{cents % 100:02d}",
        ))
    return buffer.getvalue().encode()


def upload(api_url: str, data: bytes) -> UUID | None:
    request = Request(
        f"{api_url}/jobs/csv", data=data, method="POST", headers={"Content-Type": "text/csv"},
    )
    try:
        with urlopen(request, timeout=15) as response:
            if response.status == 202:
                return UUID(json.load(response)["id"])
    except (OSError, ValueError, KeyError) as exc:
        print(f"CSV submission failed: {exc}", flush=True)
    return None


def run_burst(
    api_url: str, connection: Connection, data: bytes, jobs: int, concurrency: int, timeout: float,
) -> Burst:
    deadline = monotonic() + timeout
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        job_ids = [
            job_id for job_id in executor.map(lambda _: upload(api_url, data), range(jobs))
            if job_id is not None
        ]
    while True:
        observations = [
            Observation(*row) for row in connection.execute(OBSERVATION_SQL, (job_ids,)).fetchall()
        ]
        if (
            len(observations) == len(job_ids)
            and all(job.completed_at is not None for job in observations)
        ) or monotonic() >= deadline:
            break
        sleep(0.2)
    return Burst(jobs, jobs - len(job_ids), observations)
