from datetime import UTC, datetime, timedelta

from benchmarks.metrics import Burst, Observation, distribution, summarize
from benchmarks.workload import sales_csv
from task_system.csv_sales import summarize_sales


def test_fixture_is_deterministic_and_valid():
    assert sales_csv(200) == sales_csv(200)
    assert summarize_sales(sales_csv(200).decode())["orders"] == 200


def test_percentiles_interpolate_with_clear_empty_samples():
    assert distribution([]) == {"samples": 0, "p50": None, "p95": None, "p99": None}
    assert distribution([100, 0]) == {"samples": 2, "p50": 50, "p95": 95, "p99": 99}


def test_measurements_use_server_times_and_keep_failed_jobs_in_denominator():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    second = timedelta(seconds=1)
    jobs = [
        Observation("completed", start, start + 2 * second, start + second),
        Observation("failed", start + second, start + 4 * second, start + 2 * second),
    ]
    result = summarize([Burst(2, 0, jobs), Burst(2, 0, jobs)])
    assert result["queue_wait_ms"]["p95"] == 1000
    assert result["end_to_end_ms"]["p50"] == 2500
    assert result["jobs_per_second"] == 0.5
    assert result["failure_rate"] == 0.5

    incomplete = summarize([Burst(4, 1, jobs)])
    assert incomplete["submission_errors"] == incomplete["unfinished"] == 1
    assert incomplete["jobs_per_second"] is None
