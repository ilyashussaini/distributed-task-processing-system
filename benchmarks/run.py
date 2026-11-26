"""Scale a dedicated Compose stack and benchmark a fixed CSV workload."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from benchmarks.history import profile_history
from benchmarks.metrics import summarize
from benchmarks.workload import run_burst, sales_csv
from task_system.csv_sales import MAX_CSV_BYTES, MAX_ROWS


def command(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def read_file(path: str) -> str | None:
    file = Path(path)
    return file.read_text().strip() if file.is_file() else None


def environment(compose: list[str]) -> dict:
    info = json.loads(command("docker", "info", "--format", "{{json .}}"))
    cpu = read_file("/proc/cpuinfo") or ""
    model = next(
        (line.partition(":")[2].strip() for line in cpu.splitlines() if line.startswith("model name")),
        platform.processor() or None,
    )
    return {
        "platform": platform.platform(),
        "cpu_model": model,
        "client_cpu_affinity": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        "client_cpu_quota": read_file("/sys/fs/cgroup/cpu.max"),
        "client_memory_limit_bytes": read_file("/sys/fs/cgroup/memory.max"),
        "docker_cpus": info["NCPU"],
        "docker_memory_bytes": info["MemTotal"],
        "docker_version": info["ServerVersion"],
        "compose_version": command("docker", "compose", "version", "--short"),
        "python": platform.python_version(),
        "worker_python": command(*compose, "exec", "-T", "worker", "python", "--version"),
        "worker_cpu_quota": command(
            *compose, "exec", "-T", "worker", "sh", "-c",
            "test ! -r /sys/fs/cgroup/cpu.max || cat /sys/fs/cgroup/cpu.max",
        ) or None,
        "worker_memory_limit_bytes": command(
            *compose, "exec", "-T", "worker", "sh", "-c",
            "test ! -r /sys/fs/cgroup/memory.max || cat /sys/fs/cgroup/memory.max",
        ) or None,
        "postgres": command(*compose, "exec", "-T", "postgres", "postgres", "--version"),
        "redis": command(*compose, "exec", "-T", "redis", "redis-server", "--version"),
        "source_revision": command("git", "rev-parse", "HEAD"),
        "benchmark_sources_dirty": bool(command(
            "git", "status", "--porcelain", "--", "task_system", "benchmarks", "migrations",
            "Dockerfile", "compose.yaml", "requirements.txt",
        )),
    }


def exit_if_invalid(parser: argparse.ArgumentParser, args: argparse.Namespace, data: bytes) -> None:
    if not 1 <= args.rows <= MAX_ROWS or len(data) > MAX_CSV_BYTES:
        parser.error(f"Choose a workload with up to {MAX_ROWS} rows and {MAX_CSV_BYTES} bytes.")
    if min(args.jobs, args.warmup, args.concurrency, args.repeats, args.timeout) < 1:
        parser.error("Jobs, warmup, concurrency, repeats, and timeout must be positive.")
    if len(set(args.replicas)) != len(args.replicas):
        parser.error("Specify each replica count once.")


def start_stack(compose: list[str], replicas: int, build: bool) -> None:
    subprocess.run(
        [
            *compose, "up", "-d", "--wait", "--wait-timeout", "120", "--scale", f"worker={replicas}",
            "--build" if build else "--no-build", "api", "worker",
        ],
        check=True,
    )
    running = command(*compose, "ps", "--status", "running", "-q", "worker").splitlines()
    if len(running) != replicas:
        raise RuntimeError(f"Expected {replicas} workers, found {len(running)}.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="taskflow-benchmark", help="Dedicated Compose project name")
    parser.add_argument("--replicas", nargs="+", type=int, choices=(1, 2, 4), default=[1, 2, 4])
    parser.add_argument("--jobs", type=int, default=48, help="Number of measured jobs per burst")
    parser.add_argument("--rows", type=int, default=6000, help="Sales rows per uploaded CSV")
    parser.add_argument("--concurrency", type=int, default=8, help="Parallel HTTP submissions")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--warmup", type=int, default=6, help="Unmeasured jobs per replica configuration")
    parser.add_argument("--timeout", type=int, default=180, help="Observation deadline in seconds per burst")
    parser.add_argument("--no-build", action="store_true", help="Use images already built for this Compose project")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.rows <= MAX_ROWS:
        parser.error(f"Rows must be between 1 and {MAX_ROWS}.")
    data = sales_csv(args.rows)
    exit_if_invalid(parser, args, data)

    compose = ["docker", "compose", "-p", args.project]
    report = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "workload": {
            "jobs_per_run": args.jobs, "rows_per_file": args.rows, "csv_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "concurrency": args.concurrency,
            "repetitions": args.repeats, "warmup_jobs": args.warmup,
        },
        "configurations": [],
    }
    for index, replicas in enumerate(args.replicas):
        start_stack(compose, replicas, build=index == 0 and not args.no_build)
        api_url = "http://" + command(*compose, "port", "api", "8000")
        db_port = command(*compose, "port", "postgres", "5432").rsplit(":", 1)[-1]
        db_url = os.getenv("BENCHMARK_DATABASE_URL") or (
            f"postgresql://tasks:local-dev-password@127.0.0.1:{db_port}/tasks"
        )

        if index == 0:
            report["environment"] = environment(compose)

        with psycopg.connect(db_url, autocommit=True, connect_timeout=5) as connection:
            connection.execute("SET default_transaction_read_only = on")
            warmup = run_burst(api_url, connection, data, args.warmup, args.concurrency, args.timeout)
            if summarize([warmup])["completed"] != args.warmup:
                report["interruption"] = f"Warmup failed for {replicas} workers."
                report["interruption_metrics"] = summarize([warmup])
                break

            bursts = []
            for repeat in range(args.repeats):
                burst = run_burst(api_url, connection, data, args.jobs, args.concurrency, args.timeout)
                bursts.append(burst)
                summary = summarize([burst])
                print(f"{replicas} worker(s), run {repeat + 1}: {json.dumps(summary)}", flush=True)
                if summary["unfinished"]:
                    report["interruption"] = "The stack did not drain before the observation deadline."
                    break
            report["configurations"].append({
                "replicas": replicas,
                "summary": summarize(bursts),
                "runs": [summarize([burst]) for burst in bursts],
            })
            if index == len(args.replicas) - 1:
                report["history_probe"] = profile_history(connection)
        if "interruption" in report:
            break

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    return int("interruption" in report or any(
        entry["summary"]["completed"] != entry["summary"]["requested"]
        for entry in report["configurations"]
    ))


if __name__ == "__main__":
    raise SystemExit(main())
