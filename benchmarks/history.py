"""Measure what the database client pays to fetch job history with and without input CSVs."""

from time import perf_counter

from psycopg import Connection

from benchmarks.metrics import distribution

HISTORY_FROM = " FROM jobs ORDER BY created_at DESC, id DESC LIMIT %s"
PROJECTION = (
    "id, type, status, attempts, max_attempts, result, error, created_at, completed_at, "
    "available_at, dispatch_after, lease_expires_at"
)


def profile_history(connection: Connection, limit: int = 50, reads: int = 30) -> dict:
    payloads = connection.execute(
        "SELECT count(*), coalesce(sum(bytes), 0) FROM "
        "(SELECT octet_length(payload::text) AS bytes" + HISTORY_FROM + ") AS sample",
        (limit,),
    ).fetchone()
    if payloads is None:
        raise RuntimeError("History probe did not return a sample.")
    full = "SELECT *" + HISTORY_FROM
    projected = "SELECT " + PROJECTION + HISTORY_FROM
    timings: dict[str, list[float]] = {"full_row": [], "metadata_only": []}
    for query in (full, projected):
        connection.execute(query, (limit,)).fetchall()
    for index in range(reads):
        queries = [("full_row", full), ("metadata_only", projected)]
        if index % 2:
            queries.reverse()
        for name, query in queries:
            start = perf_counter()
            connection.execute(query, (limit,)).fetchall()
            timings[name].append((perf_counter() - start) * 1000)
    return {
        "rows_per_read": payloads[0],
        "payload_bytes_per_full_read": payloads[1],
        "full_row_ms": distribution(timings["full_row"]),
        "metadata_only_ms": distribution(timings["metadata_only"]),
    }
