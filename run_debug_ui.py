from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch nf loopback debug web UI.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8080, help="Bind port (default: 8080).")
    parser.add_argument("--debug-token", default="", help="Debug UI token (default: random).")
    parser.add_argument("--api-token", default="", help="Optional NF_ORCHESTRATOR_TOKEN for API calls.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser automatically.")
    parser.add_argument("--no-worker", action="store_true", help="Do not start a worker process.")
    parser.add_argument("--poll-interval", type=float, default=1.0, help="Worker poll interval seconds.")
    parser.add_argument("--lease-seconds", type=int, default=30, help="Worker lease seconds.")
    return parser.parse_args()


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

    debug_token = args.debug_token.strip() or uuid.uuid4().hex
    os.environ["NF_ENABLE_DEBUG_WEB_UI"] = "1"
    os.environ["NF_DEBUG_WEB_UI_TOKEN"] = debug_token
    if args.api_token.strip():
        os.environ["NF_ORCHESTRATOR_TOKEN"] = args.api_token.strip()
    else:
        os.environ.pop("NF_ORCHESTRATOR_TOKEN", None)

    url = f"http://{args.host}:{args.port}/_debug?debug_token={debug_token}"
    print("nf debug web UI")
    print(f"- URL: {url}")
    if args.api_token.strip():
        print(f"- API token: {args.api_token.strip()} (paste into the UI's 'API 토큰' field)")
    print("- Stop: Ctrl+C")
    print("")

    if not args.no_browser:
        threading.Thread(target=lambda: (time.sleep(0.8), webbrowser.open(url)), daemon=True).start()

    from modules.nf_orchestrator import run_orchestrator

    worker_proc: subprocess.Popen[bytes] | None = None
    if not args.no_worker:
        worker_proc = _spawn_worker(
            repo_root,
            poll_interval=args.poll_interval,
            lease_seconds=args.lease_seconds,
        )
        print(f"- Worker PID: {worker_proc.pid}")

    try:
        run_orchestrator(args.host, args.port, start_worker=False)
        return 0
    except KeyboardInterrupt:
        return 130
    finally:
        if worker_proc is not None:
            worker_proc.terminate()
            try:
                worker_proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                worker_proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())

