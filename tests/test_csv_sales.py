import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from benchmarks.workload import sales_csv
from task_system.api import create_app
from task_system.csv_sales import MAX_CSV_BYTES, MAX_ROWS, InvalidCSV, summarize_sales

HEADER = "order_id,region,quantity,unit_price\n"
VALID = HEADER + 'a,"South, East",2,1.10\nb,North,3,2.91\n'


def test_sales_result_uses_exact_totals_and_rounds_average_half_up():
    assert summarize_sales(VALID) == {
        "orders": 2,
        "units_sold": 5,
        "revenue": "10.93",
        "average_order_value": "5.47",
        "regions": [
            {"region": "North", "orders": 1, "units_sold": 3, "revenue": "8.73"},
            {"region": "South, East", "orders": 1, "units_sold": 2, "revenue": "2.20"},
        ],
    }


@pytest.mark.parametrize(("source", "message"), [
    ("order_id,region,quantity\n", "Expected the columns"),
    (HEADER, "at least one data row"),
    (HEADER + "a,North,2\n", "exactly four fields"),
    (HEADER + "a,North,2,1.00\na,South,3,2.00\n", "duplicate order_id"),
    (HEADER + "a,North,0,1.00\n", "invalid quantity"),
    (HEADER + "a,North,2,NaN\n", "invalid unit_price"),
    (HEADER + "a,North,2,1.001\n", "invalid unit_price"),
    (HEADER + "a,North,2,1000000.01\n", "unit_price limit"),
    (HEADER + 'a,"North,2,1.00\n', "could not be parsed"),
    (HEADER + "a,\x00,2,1.00\n", "invalid region"),
])
def test_invalid_sales_reports_a_safe_reason(source, message):
    with pytest.raises(InvalidCSV, match=message):
        summarize_sales(source)


def test_worker_side_resource_limits():
    with pytest.raises(InvalidCSV, match="10,000 data rows"):
        summarize_sales(sales_csv(MAX_ROWS + 1).decode())
    with pytest.raises(InvalidCSV, match="512 KiB"):
        summarize_sales("é" * MAX_CSV_BYTES)
    many_regions = HEADER + "".join(f"id-{index},Region {index},2,1.50\n" for index in range(65))
    with pytest.raises(InvalidCSV, match="64 distinct regions"):
        summarize_sales(many_regions)


@pytest.fixture
def csv_client(engine, settings):
    with TestClient(create_app(settings, engine=engine)) as client:
        yield client


@pytest.mark.integration
@pytest.mark.parametrize(("body", "headers", "expected"), [
    (b"wrong media", {"Content-Type": "application/json"}, 415),
    (b"unsupported compression", {"Content-Type": "text/csv", "Content-Encoding": "gzip"}, 415),
    (b"\xff\xfe", {"Content-Type": "text/csv"}, 422),
    (b" \n  ", {"Content-Type": "text/csv"}, 422),
    (b"x" * (MAX_CSV_BYTES + 1), {"Content-Type": "text/csv"}, 413),
])
def test_invalid_csv_upload_envelope_does_not_enqueue(csv_client, body, headers, expected):
    assert csv_client.post("/jobs/csv", content=body, headers=headers).status_code == expected
    assert csv_client.get("/jobs").json() == []


@pytest.mark.integration
def test_uploaded_csv_runs_in_worker_and_invalid_data_fails_once(csv_client, worker_factory):
    valid = csv_client.post(
        "/jobs/csv", content=b"\xef\xbb\xbf" + VALID.encode(),
        headers={"Content-Type": "text/csv; charset=utf-8"},
    )
    assert valid.status_code == 202
    worker = worker_factory()
    assert worker.run_once()
    job = csv_client.get(valid.headers["Location"]).json()
    assert job["type"] == "csv_sales_summary"
    assert job["status"] == "completed"
    assert job["result"]["revenue"] == "10.93"

    invalid = csv_client.post("/jobs/csv", content=HEADER, headers={"Content-Type": "text/csv"})
    assert invalid.status_code == 202
    assert worker.run_once()
    job = csv_client.get(invalid.headers["Location"]).json()
    assert job["status"] == "failed"
    assert job["attempts"] == 1 and job["max_attempts"] == 3
    assert job["error"] == "CSV must contain at least one data row."
    assert job["next_attempt_at"] is None
    attempt = csv_client.get(f"/monitoring/jobs/{job['id']}").json()["attempts"][0]
    assert attempt["status"] == "failed" and attempt["duration_ms"] > 0


@pytest.mark.integration
def test_job_reads_do_not_fetch_csv_payload(csv_client, engine):
    response = csv_client.post("/jobs/csv", content=VALID, headers={"Content-Type": "text/csv"})
    job_id = response.json()["id"]
    reads = []

    def capture(_conn, _cur, statement, _params, _context, _many):
        if statement.startswith("SELECT"):
            reads.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        for path in ("/jobs", f"/jobs/{job_id}", "/monitoring/jobs", f"/monitoring/jobs/{job_id}"):
            assert csv_client.get(path).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert reads and all("jobs.payload" not in query for query in reads)
