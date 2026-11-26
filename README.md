# Distributed Task Processing System

A Python 3.12 backend for submitting, executing, and tracking background jobs. FastAPI accepts requests, PostgreSQL stores job state and results via SQLAlchemy, and Redis Streams distributes jobs across worker processes. The first job type, `word_count`, counts whitespace-separated words.

## Quick start

Install Docker with the Compose plugin, then run the following from the repository root.

```sh
cp .env.example .env
docker compose up -d --build --wait --scale worker=2
```

Compose runs the Alembic migration before starting the API and workers. Open the interactive API docs at <http://localhost:8000/docs>. Use `docker compose logs -f api worker` to see requests and job attempts. Run `docker compose down` to stop the stack and retain its named data volumes.

## API

| Method | Path | Response |
| --- | --- | --- |
| POST | `/jobs` | `202 Accepted` with the job, a UUID, and a `Location` header |
| GET | `/jobs/{id}` | `200 OK` with current status, attempts, timestamps, result, and last error. Unknown UUIDs return `404`. |
| GET | `/jobs?limit=20&offset=0` | `200 OK` with a newest-first list of jobs. The maximum limit is 100. |

Submit a job, then poll its resource until it reaches a terminal state.

```sh
job_id=$(curl -fsS http://localhost:8000/jobs \
  -H 'Content-Type: application/json' \
  -d '{"type":"word_count","payload":{"text":"Hello background workers"}}' \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["id"])')

curl -fsS "http://localhost:8000/jobs/$job_id"
curl -fsS 'http://localhost:8000/jobs?limit=10'
```

The job finishes with `status: completed` and a result of `{"word_count":3}`. Empty text, invalid payloads, and unknown job types return `422`. Submit nonempty whitespace-only text to observe retries after a worker failure.

```sh
curl -i http://localhost:8000/jobs \
  -H 'Content-Type: application/json' \
  -d '{"type":"word_count","payload":{"text":"   "}}'
```

Follow the returned `Location`. With default settings, retries are scheduled approximately 2 and 4 seconds after the first and second failures. During backoff the job is `pending` and exposes `next_attempt_at` and the last error. After the final attempt, status becomes `failed` and `completed_at` is set.

## Architecture and delivery

```mermaid
flowchart LR
    Client -->|Submit or query| API[FastAPI]
    API -->|Persist and query jobs| DB[(PostgreSQL)]
    W1[Worker 1] <-->|Schedule, claim, and record| DB
    W2[Worker 2] <-->|Schedule, claim, and record| DB
    W1 <-->|Publish, read, and acknowledge| Stream[(Redis Stream)]
    W2 <-->|Publish, read, and acknowledge| Stream
```

1. **Submit.** The API commits the job and its dispatch deadline in PostgreSQL before returning. Submission can continue during a Redis outage.
2. **Dispatch.** Workers select due pending jobs with `FOR UPDATE SKIP LOCKED` and publish their IDs to a Redis stream. One consumer group shares deliveries across workers. A failed publish rolls back the dispatch transaction. Jobs that remain pending become eligible for redispatch after the configured interval.
3. **Execute.** Workers independently read deliveries and claim jobs using PostgreSQL row locks. A claim moves the job to `running`, increments its attempt count, and starts a lease. The worker renews the lease every third of its duration while the job runs. Each worker runs one job at a time. Two replicas can execute two distinct jobs concurrently.
4. **Record.** A worker with a live lease commits the result or failure before acknowledging the delivery it used to start the job. Failures either schedule a retry with capped exponential backoff or become terminal. The `completed_at` timestamp marks either terminal state.
5. **Recover.** Workers reclaim idle Redis deliveries and reschedule jobs whose database leases expire. PostgreSQL checks the attempt number and lease expiry before accepting a renewal, result, or failure. Duplicate notifications for running or terminal jobs, or jobs still in backoff, can be acknowledged safely because PostgreSQL retains the job and its schedule.

Delivery is **at least once**. Handlers should be idempotent because a job can run again after an attempt loses its lease before recording an outcome. The word-count handler is pure and its input is capped at 100,000 characters.

## Configuration

Copy `.env.example` for local development. Shell environment variables override values from `.env`. Compose publishes PostgreSQL, Redis, and the API on loopback.

| Variable | Default | Purpose |
| --- | --- | --- |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `tasks`, `local-dev-password`, `tasks` | Local database credentials and name |
| `POSTGRES_PORT`, `REDIS_PORT`, `API_PORT` | `5432`, `6379`, `8000` | Published host ports |
| `DATABASE_URL` | Built from `POSTGRES_*` settings | Optional PostgreSQL URL for host processes. Use the `postgresql+psycopg://` scheme. |
| `REDIS_URL` | Localhost on the host, `redis://redis:6379/0` in Compose | Redis connection URL |
| `REDIS_STREAM` | `task-system:jobs` | Stream shared by workers in the same deployment |
| `MAX_ATTEMPTS` | `3` | Total attempts including the first. Saved per job at submission. |
| `RETRY_BASE_SECONDS`, `RETRY_MAX_SECONDS` | `2`, `60` | Initial delay and maximum delay |
| `LEASE_SECONDS` | `30` | Time from the last successful claim or renewal until an unfinished attempt can be recovered. Redis also uses this interval for reclaiming idle deliveries. |
| `REDISPATCH_SECONDS` | `15` | Time before a pending job may be published again |
| `POLL_MS`, `DISPATCH_BATCH_SIZE` | `500`, `50` | Maximum idle Redis read wait and number of jobs scheduled per batch |

You can also run the Python processes on the host and keep PostgreSQL and Redis in Docker.

```sh
docker compose up -d --wait postgres redis
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
alembic upgrade head
uvicorn task_system.api:app --port 8000
```

In a separate terminal with the same virtual environment active, run `python -m task_system.worker` for each worker. Set `REDIS_URL` when using a non-default Redis port on the host.

## Tests

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m pytest -m 'not integration'

docker compose up -d --wait postgres redis
TEST_DATABASE_URL=postgresql+psycopg://tasks:local-dev-password@127.0.0.1:5432/tasks \
TEST_REDIS_URL=redis://127.0.0.1:6379/0 \
  python -m pytest -ra
```

The integration suite runs migrations in isolated PostgreSQL schemas and uses unique Redis stream keys. The database user needs permission to create schemas. Tests for a service skip if its test URL is unset. They fail if the configured service is unreachable. The suite covers API validation and persistence, concurrent execution, retries, lease renewal and expiry, duplicate delivery, and worker recovery.

## Continuous integration

GitHub Actions runs on pull requests and pushes to `main`. The Python job runs Ruff and both pytest suites on Python 3.12 with PostgreSQL 17 and Redis 7 service containers. A separate GitHub-hosted job builds the Docker Compose images from a clean checkout without a build cache, starts two worker replicas, checks the migrated schema, and exercises successful and failed jobs over HTTP. Find both jobs in the pull request's **Checks** tab. [CI workflow](.github/workflows/ci.yml)

Run the clean Compose build and smoke check from the repository root with the default local settings.

```sh
docker compose build --pull --no-cache
docker compose up -d --no-build --wait --scale worker=2
docker compose exec -T api alembic check
python3 tests/compose_smoke.py
docker compose down
```

Set `SMOKE_BASE_URL` when the API uses a different host port.

## Milestone 1 limitations

- A process pause or database outage longer than the remaining lease can let another worker start a retry while the original handler is still executing. The database rejects stale results. Handlers with external side effects need their own idempotency keys or safeguards.
- A responsive worker can keep renewing the lease of a hung handler until an operator stops the worker. Milestone 1 leaves execution deadlines and cancellation to the operator.
- Redis can receive repeated notifications during a backlog or broker interruption. The PostgreSQL claim and retry schedule govern which notifications can start an attempt.
- Compose uses a single PostgreSQL instance and a single Redis instance. The API is intended for local use without authentication, and stored job history has no automatic retention policy.
