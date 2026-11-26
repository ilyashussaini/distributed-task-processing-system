# Distributed Task Processing System

A distributed background job processor with a React and TypeScript monitoring dashboard. FastAPI accepts requests, PostgreSQL stores job and attempt state via SQLAlchemy, and Redis Streams distributes jobs across Python 3.12 workers. Jobs include word counting and sales CSV validation and aggregation.


**Live Demo:** [Explore Taskflow](https://taskflow-demo-9mq.pages.dev/)

**Demo note:** Read-only dashboard with synthetic job data and real recorded performance benchmarks.


## Portfolio demo

Taskflow shows a job from HTTP submission through queueing, execution, retry, and a persisted result. The dashboard lets reviewers browse attempt history and compare measured throughput and latency across worker counts.

- **Workloads** · Word counting and bounded sales CSV validation with exact regional totals.
- **Recovery** · Renewable database leases, isolated execution deadlines, and tested worker-loss recovery.
- **Monitoring** · Job history, timing and retries, and a recorded 1-, 2-, and 4-worker benchmark.
- **Hosting** · A browser-only portfolio demo and a protected live Compose profile. [Deployment guide and cost estimates](docs/deployment.md)

![Taskflow desktop overview with sample job counts, throughput, and outcomes](docs/images/taskflow-desktop.jpg)

<details>
<summary>Mobile job details</summary>

<img src="docs/images/taskflow-mobile.jpg" width="390" alt="Taskflow failed CSV job and attempt details on mobile">

</details>

## Quick start

Install Docker with the Compose plugin, then run the following from the repository root.

```sh
cp .env.example .env
docker compose up -d --build --wait --scale worker=2
```

Compose runs the Alembic migration before starting the API and workers. Open **Taskflow** at <http://localhost:3000> or the interactive API docs at <http://localhost:8000/docs>. Use `docker compose logs -f api worker` to see requests and job attempts. Run `docker compose down` to stop the stack and retain its named data volumes.

## Monitoring dashboard

- Select **New job** to enter text or upload a sales CSV. The details panel follows the job through processing and shows the result or validation error. Whitespace-only word-count input exercises retries and failure.
- In **Jobs**, search by ID or job type, filter by status, and use the page controls. Open a row to inspect timestamps, the latest error, retry scheduling, and recorded attempts.
- In **Overview**, the five job counts represent retained history. Select a time range for recent throughput, terminal outcomes, and average processing time. **Analytics** adds duration percentiles, retry and failure counts, and a recorded comparison of throughput and latency with 1, 2, and 4 workers. Each open view polls every five seconds after its last response and labels stale data when the API becomes unavailable.

Throughput uses submission timestamps for submissions and terminal timestamps for outcomes. Success and failure rates divide each terminal outcome count by all terminal jobs in that range. Duration statistics use measured attempts started in the range and include handler process startup and cleanup. Queue wait, backoff, and abandoned attempts are excluded. Recent retry counts use recorded attempt numbers. Jobs from before migration `0002` keep their job counts, outcomes, and total attempts. Per-attempt timing and history accumulate from the migration onward.

For frontend development with Node.js 24, start the API and workers in Compose, then run Vite locally.

```sh
docker compose up -d --build --wait --scale worker=2 api worker
cd frontend
npm ci
npm run dev
```

Open <http://localhost:5173>. Vite forwards `/api` to localhost port 8000. Set `DASHBOARD_API_TARGET` to the API origin when using a different port. The built frontend uses Nginx to forward the same paths to FastAPI on the Compose network.

## Run the read-only demo

From `frontend/`, build with Node.js 24. The read-only demo uses synthetic jobs, statuses, and activity charts. The benchmark comparison in **Analytics** uses recorded throughput and latency from actual test runs with 1, 2, and 4 workers on the same generated CSV workload. The demo makes no API requests and provides no submission controls. [Benchmark methodology and measured results](#performance-benchmark)

```sh
npm ci
VITE_TASKFLOW_DEMO=true npm run build
VITE_TASKFLOW_DEMO=true npm exec vite preview -- --host 127.0.0.1
```

Open `http://127.0.0.1:4173`. For an approved static deployment, serve only `frontend/dist` from the demo build. The live setup uses the standard build and its same-origin API proxy. [Hosting and launch guide](docs/deployment.md)

## API

| Method | Path | Response |
| --- | --- | --- |
| POST | `/jobs` | `202 Accepted` with the job, a UUID, and a `Location` header |
| POST | `/jobs/csv` | Accepts a UTF-8 sales CSV as the raw `text/csv` request body and returns the same job response. |
| GET | `/jobs/{id}` | `200 OK` with current status, attempts, timestamps, result, and last error. Unknown UUIDs return `404`. |
| GET | `/jobs?limit=20&offset=0` | `200 OK` with a newest-first list of jobs. The maximum limit is 100. |
| GET | `/monitoring/overview?window=24h` | Lifetime counts, ranged performance statistics, and time buckets. Windows are `1h`, `24h`, `7d`, and `30d`. |
| GET | `/monitoring/jobs` | Jobs and matching total, with optional `limit`, `offset`, `status`, and `q` filters. |
| GET | `/monitoring/jobs/{id}` | The job and its recorded attempts from the same database snapshot. |

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

## Sales CSV jobs

Upload a [sample sales file](benchmarks/sample-sales.csv) in Taskflow or submit it through the API.

```sh
curl -i http://localhost:8000/jobs/csv \
  -H 'Content-Type: text/csv' \
  --data-binary @benchmarks/sample-sales.csv
```

Follow the returned `Location` to get order count, units sold, revenue, average order value, and the breakdown by region. Monetary results are two-decimal strings in the input currency, calculated in integer cents. The average rounds half up.

The upload accepts at most 512 KiB of uncompressed UTF-8, optionally with a byte-order mark. The worker validates the exact header set `order_id,region,quantity,unit_price` in any order, up to 10,000 rows and 64 distinct regions. IDs must be unique and contain up to 64 ASCII letters, digits, underscores, dots, or hyphens, starting with a letter or digit. Regions may contain up to 64 printable characters. Quantity must be an integer from 1 to 1,000,000. Prices range from 0 to 1,000,000 with up to two decimal places. Invalid data fails once with a row-specific error when applicable. Worker loss and execution timeouts still use the existing retry policy. Uploaded data follows the same PostgreSQL retention as other job inputs.

## Architecture and delivery

```mermaid
flowchart LR
    Browser --> Dashboard[React dashboard / Nginx]
    Dashboard -->|Submit or query| API[FastAPI]
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

Copy `.env.example` for local development. Shell environment variables override values from `.env`. Compose publishes PostgreSQL, Redis, the API, and the dashboard on loopback.

| Variable | Default | Purpose |
| --- | --- | --- |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `tasks`, `local-dev-password`, `tasks` | Local database credentials and name |
| `POSTGRES_PORT`, `REDIS_PORT`, `API_PORT`, `DASHBOARD_PORT` | `5432`, `6379`, `8000`, `3000` | Published host ports |
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

The integration suite runs migrations in isolated PostgreSQL schemas and uses unique Redis stream keys. The database user needs permission to create schemas. Tests for a service skip if its test URL is unset. They fail if the configured service is unreachable. The suite covers API validation, monitoring aggregates, attempt timing, retries, duplicate delivery, and worker recovery.

```sh
cd frontend
npm ci
npm run lint
npm test
npm run build
```

## Continuous integration

GitHub Actions runs on pull requests and pushes to `main`. The Python job runs Ruff and pytest with PostgreSQL 17 and Redis 7. The frontend job runs ESLint, Vitest, TypeScript, and the Vite production build. A separate job builds the Compose images from a clean checkout, checks the schema, then runs smoke tests and the two-worker recovery demo. Find all three jobs in the pull request's **Checks** tab. [CI workflow](.github/workflows/ci.yml)

Run the clean Compose build and smoke check from the repository root with the default local settings.

```sh
docker compose build --pull --no-cache
docker compose up -d --no-build --wait --scale worker=2
docker compose exec -T api alembic check
python3 tests/compose_smoke.py
SMOKE_BASE_URL=http://127.0.0.1:3000/api python3 tests/dashboard_smoke.py
docker compose down
```

Set `SMOKE_BASE_URL` when the API uses a different host port.

## Performance benchmark

Run from the repository root with Docker Compose, the Python dependencies from `requirements.txt`, and three free host ports. The benchmark creates a separate Compose project and scales it to 1, 2, and 4 workers. It keeps the stack running so you can inspect the jobs before cleanup.

```sh
export API_PORT=18010 POSTGRES_PORT=15439 REDIS_PORT=16389
python -m benchmarks.run --output /tmp/taskflow-benchmarks.json
docker compose -p taskflow-benchmark down
```

The runner uses the sample database credentials by default. Set `BENCHMARK_DATABASE_URL` to a host-accessible PostgreSQL connection URL if you changed them. Use `python -m benchmarks.run --help` to change the workload. To refresh the charts with your own full matrix, write the report to `frontend/src/data/benchmark-results.json` and rebuild the frontend.

Each configuration processes six warmup jobs and two measured bursts of 48 jobs with eight concurrent HTTP submissions. All 288 measured jobs use the same deterministic 6,000-row CSV. The runner records the file hash and uses read-only PostgreSQL observations scoped to the returned job IDs.

- **Queue wait** runs from job creation to the start of its first attempt. **End-to-end latency** runs from job creation to the terminal timestamp. Both use PostgreSQL timestamps, so they exclude the observer's polling delay.
- **Throughput** divides terminal jobs by the summed time from first creation to last terminal outcome in each burst. **Failure rate** divides failed jobs by observed terminal jobs. Submission errors and unfinished jobs have separate counts. Incomplete bursts suppress throughput and produce a failing command exit status.
- Group percentiles pool both runs and use linear interpolation. The JSON includes per-run results, sample counts, first-attempt execution percentiles, and the environment. [Measured benchmark report](frontend/src/data/benchmark-results.json)

### Measured results

| Workers | Jobs/s | Queue wait p50 / p95 / p99 (s) | End-to-end p50 / p95 / p99 (s) | Failed / processed |
| ---: | ---: | --- | --- | ---: |
| 1 | 2.175 | 11.50 / 21.65 / 23.02 | 11.92 / 22.07 / 23.38 | 0 / 96 |
| 2 | 3.301 | 7.11 / 13.17 / 13.62 | 7.88 / 13.69 / 14.11 | 0 / 96 |
| 4 | 2.636 | 8.74 / 16.13 / 18.39 | 9.78 / 18.40 / 19.50 | 0 / 96 |

The runs used a shared x86-64 Linux VM on an AMD EPYC 9V45. Docker reported three CPUs. The benchmark client and worker reported a two-CPU cgroup quota and an 8 GiB memory limit. The stack used Docker 29.9.2, Compose 2.40.3, Python 3.12.16 in the worker, PostgreSQL 17.12, and Redis 7.4.12. Each request uploaded 175,563 bytes. All 288 jobs were accepted and completed within the observation deadline.

Two workers delivered the highest throughput in this test. First-attempt median execution rose from 535 ms with two workers to 1,356 ms with four, alongside a longer queue wait. This is consistent with contention on the shared host. The runs used two bursts per configuration on one machine with co-located services, so the result applies to this workload and resource budget. The measured failure rate describes valid inputs in these bursts.

The database probe alternated 30 paired reads over the latest 50 jobs after warmup. Each full-row read retrieved 9,078,750 bytes of CSV payload text. At the PostgreSQL client boundary, p95 fell from 118.79 ms to 3.80 ms when the same reads omitted the payload. Job lists, detail views, and lease and outcome operations now omit inputs they do not use. Workers still load inputs when claiming a job. The latency comparison covers query transfer and decoding, while the scaling table measures whole job bursts with the projection in place.

## Two-worker recovery demo

Run this on an isolated Compose project with Python 3.12. The override enables demo jobs, gives each attempt a four-second deadline and a two-second renewable lease, and sets a one-second initial retry delay. The script sends `SIGKILL` to one worker container in the selected project during the worker-loss scenario and starts it again after verification.

```sh
export POSTGRES_PORT=15433 REDIS_PORT=16380 API_PORT=18001 DASHBOARD_PORT=18004
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
- The default Compose stack is for local development. The protected deployment profile applies authentication and retention on a single host with one PostgreSQL instance and one Redis instance. [Deployment guide](docs/deployment.md)
- The live indicator reflects API connectivity. Worker presence and capacity require independent worker telemetry. Offset pages can shift when jobs arrive or change status, and aggregate queries read the current PostgreSQL data on each refresh.


## Interview walkthrough

1. Open the read-only demo. Filter **Jobs** to **Failed**, inspect the row-specific CSV error, then open a completed job with two attempts. Explain how PostgreSQL stores the authoritative state and Redis distributes notifications.
2. On a local live stack, submit the sample CSV. Open the result and describe how one worker claims each attempt under a database lock. A child-process deadline bounds work. The lease identifies the worker that can write the outcome, and retry backoff gives transient failures time to clear.
3. Open **Analytics** and compare 1, 2, and 4 workers. Explain that each configuration ran two identical bursts after warmup, with queue wait and latency derived from persisted timestamps. Discuss why two workers performed best on the tested host and how omitting unused CSV data reduced PostgreSQL read latency.
4. Close with the trade-offs. A static public demo costs nothing to run and cannot enqueue work. The private live profile keeps the data services off public ports and adds authentication, quotas, and retention on one VM.
