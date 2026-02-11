from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run nf orchestrator + worker locally.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8080, help="Bind port (default: 8080).")
    parser.add_argument("--db-path", default="", help="SQLite DB path (default: nf_orchestrator.sqlite3).")
    parser.add_argument("--api-token", default="", help="Optional NF_ORCHESTRATOR_TOKEN for API calls.")
    parser.add_argument("--no-worker", action="store_true", help="Do not start a worker process.")
    parser.add_argument("--worker-procs", type=int, default=1, help="Number of worker processes (default: 1).")
    parser.add_argument("--max-heavy-jobs", type=int, default=1, help="Max concurrent heavy jobs.")
    parser.add_argument("--poll-interval", type=float, default=1.0, help="Worker poll interval seconds.")
    parser.add_argument("--lease-seconds", type=int, default=30, help="Worker lease seconds.")
    return parser.parse_args()


def _resolve_db_path(repo_root: Path, db_path_raw: str) -> Path | None:
    db_path_raw = db_path_raw.strip()
    if not db_path_raw:
        return None
    path = Path(db_path_raw).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path


def _spawn_worker(repo_root: Path, *, poll_interval: float, lease_seconds: int) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(repo_root) + (os.pathsep + pythonpath if pythonpath else "")
    code = (
        "from modules.nf_workers import run_worker\n"
        f"run_worker(poll_interval={poll_interval!r}, lease_seconds={lease_seconds!r})\n"
    )
    return subprocess.Popen([sys.executable, "-c", code], env=env)


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    db_path = _resolve_db_path(repo_root, args.db_path)
    if db_path is not None:
        os.environ["NF_ORCH_DB_PATH"] = str(db_path)
    if args.api_token.strip():
        os.environ["NF_ORCHESTRATOR_TOKEN"] = args.api_token.strip()
    else:
        os.environ.pop("NF_ORCHESTRATOR_TOKEN", None)
    os.environ["NF_MAX_HEAVY_JOBS"] = str(max(1, int(args.max_heavy_jobs)))

    worker_procs: list[subprocess.Popen[bytes]] = []
    worker_count = 0 if args.no_worker else max(0, args.worker_procs)
    for _ in range(worker_count):
        worker_procs.append(
            _spawn_worker(repo_root, poll_interval=args.poll_interval, lease_seconds=args.lease_seconds)
        )

    try:
        print("nf local stack")
        print(f"- Orchestrator: http://{args.host}:{args.port}")
        if db_path is not None:
            print(f"- DB: {db_path}")
        if worker_procs:
            print(f"- Worker Procs: {len(worker_procs)}")
            for idx, worker_proc in enumerate(worker_procs, start=1):
                print(f"  - Worker {idx} PID: {worker_proc.pid}")
        else:
            print("- Worker Procs: 0")
        print(f"- Max Heavy Jobs: {os.environ.get('NF_MAX_HEAVY_JOBS')}")
        print("- Stop: Ctrl+C")
        print("")

        from modules.nf_orchestrator import run_orchestrator

        run_orchestrator(args.host, args.port, start_worker=False)
        return 0
    except KeyboardInterrupt:
        return 130
    finally:
        for worker_proc in worker_procs:
            worker_proc.terminate()
            try:
                worker_proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                worker_proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
