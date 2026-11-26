import pytest

from task_system.jobs import JobError, retry_delay, run_job


@pytest.mark.parametrize(
    ("text", "count"),
    [("one two three", 3), ("\tone\n two\u00a0three  ", 3), ("café", 1)],
)
def test_word_count(text, count):
    assert run_job("word_count", {"text": text}) == {"word_count": count}


def test_word_count_rejects_whitespace_only():
    with pytest.raises(JobError, match="must contain at least one word"):
        run_job("word_count", {"text": " \n\t"})


def test_unknown_type_raises_job_error():
    with pytest.raises(JobError, match="Unsupported job type"):
        run_job("unknown", {"text": "example"})


@pytest.mark.parametrize(("attempt", "expected"), [(1, 2), (2, 4), (3, 8), (4, 10), (5, 10)])
def test_retry_delay_grows_exponentially_up_to_cap(attempt, expected):
    assert retry_delay(attempt, base_seconds=2, max_seconds=10) == expected
