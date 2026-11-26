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
3. **Execute.** Workers independently read deliveries and claim jobs using PostgreSQL row locks. A claim moves the job to `running`, increments its attempt count, and starts a lease. The worker renews the lease while one handler runs in a separate Python process. Two worker replicas can execute two jobs concurrently.
4. **Record.** The worker terminates and reaps the child when the execution deadline elapses. A worker with a live lease commits the outcome before acknowledging the delivery it used to start the job. Timeouts follow the same capped exponential backoff as other failures. The `completed_at` timestamp marks either terminal state.
5. **Recover.** Workers reclaim idle Redis deliveries and reschedule jobs whose database leases expire. PostgreSQL checks the attempt number and lease expiry before accepting a renewal, result, or failure. Duplicate notifications for running or terminal jobs, or jobs still in backoff, can be acknowledged safely because PostgreSQL retains the job and its schedule.

Worker logs are JSON lines. Filter by `job_id` and `attempt` to follow the handler process, timeout, retry, lease recovery, and final outcome across replicas. Timeout events include the child PID and exit code. The word-count handler is pure and its input is capped at 100,000 characters.

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
| `ATTEMPT_TIMEOUT_SECONDS` | `30` | Wall-clock budget for each handler process, including interpreter startup |
| `ENABLE_RECOVERY_DEMO` | `false` | Allow the API to accept synthetic recovery demo jobs |
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

GitHub Actions runs on pull requests and pushes to `main`. The Python job runs Ruff and both pytest suites on Python 3.12 with PostgreSQL 17 and Redis 7 service containers. A separate GitHub-hosted job builds the images from a clean checkout without a build cache, starts two workers, checks the schema, and runs the HTTP smoke test and recovery demo. Find both jobs in the pull request's **Checks** tab. [CI workflow](.github/workflows/ci.yml)

Run the clean Compose build and smoke check from the repository root with the default local settings.

```sh
docker compose build --pull --no-cache
docker compose up -d --no-build --wait --scale worker=2
docker compose exec -T api alembic check
python3 tests/compose_smoke.py
docker compose down
```

Set `SMOKE_BASE_URL` when the API uses a different host port.

## Two-worker recovery demo

Run this on an isolated Compose project with Python 3.12. The override enables demo jobs, gives each attempt a four-second deadline and a two-second renewable lease, and sets a one-second initial retry delay. The script sends `SIGKILL` to one worker container in the selected project during the worker-loss scenario and starts it again after verification.

```sh
export POSTGRES_PORT=15433 REDIS_PORT=16380 API_PORT=18001
export SMOKE_BASE_URL=http://127.0.0.1:18001
docker compose -p task-recovery-demo -f compose.yaml -f compose.recovery.yaml \
  up -d --build --wait --scale worker=2
python3.12 tests/recovery_demo.py --project task-recovery-demo --scenario timeout
python3.12 tests/recovery_demo.py --project task-recovery-demo --scenario worker-loss
docker compose -p task-recovery-demo logs --no-color --no-log-prefix worker
docker compose -p task-recovery-demo -f compose.yaml -f compose.recovery.yaml down
```

The timeout scenario submits a job whose handler hangs on every attempt. The script matches the started child PID to its `SIGKILL` exit, verifies the job reaches `failed` after two attempts, and confirms an unrelated word-count job completed before the first deadline. In the worker-loss scenario the script waits for the first child to start, kills its container, and verifies the surviving worker completes an unrelated job and then recovers the abandoned job on attempt 2.

Observed in a local Linux Compose run with the settings above. Times vary with heartbeat timing, polling, and host load.

| Measurement | Observed | Measured from |
| --- | --- | --- |
| Hung child killed and reaped | 4.01 s | Child process start |
| Abandoned lease recovered | 1.85 s | Return of the worker SIGKILL command |
| Abandoned job completed on attempt 2 | 3.29 s | Return of the worker SIGKILL command |

## Delivery limits

- Delivery remains **at least once**. If a process pause or database outage outlasts the lease, another worker can start a retry while the original handler is running. PostgreSQL rejects stale outcomes, but effects already performed by a handler can repeat. Use idempotency keys or transactional safeguards for external effects.
- Timeouts control the direct handler process. Handlers run with the worker's privileges and must manage any descendant processes they launch. The deadline cannot undo side effects or bound time spent waiting in the queue, on backoff, or for infrastructure recovery.
- Redis can receive repeated notifications during a backlog or broker interruption. The PostgreSQL claim and retry schedule govern which notifications can start an attempt.
- Compose uses a single PostgreSQL instance and a single Redis instance. The API is intended for local use without authentication, and stored job history has no automatic retention policy.
