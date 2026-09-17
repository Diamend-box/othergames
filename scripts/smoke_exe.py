#!/usr/bin/env python3
"""Start the packaged executable and check it can actually serve a save.

PyInstaller reports success as soon as it has written an exe, so a build can be
green and still crash on launch. This runs dist/SatisfactoryPlanner against the
fixture save and the fixture recipe data, then asks the API for a report.

    python scripts/build_exe.py
    python scripts/smoke_exe.py
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
EXE = ROOT / "dist" / ("SatisfactoryPlanner.exe" if sys.platform == "win32" else "SatisfactoryPlanner")
STARTUP_SECONDS = 120  # the first parse of the save happens before the port opens


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read())


def wait_for(url: str, proc: subprocess.Popen, deadline: float) -> dict:
    while time.time() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"The executable exited early with code {proc.returncode}")
        try:
            return get(url)
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(0.5)
    raise SystemExit(f"No answer from {url} after {STARTUP_SECONDS}s")


def main() -> int:
    if not EXE.is_file():
        print(f"Missing {EXE} - run scripts/build_exe.py first", file=sys.stderr)
        return 1

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory() as state_home:
        # Keep the app's own files (the saved plan) out of the real profile.
        env = dict(os.environ, APPDATA=state_home, XDG_DATA_HOME=state_home)
        cmd = [
            str(EXE),
            "--no-browser",
            "--port", str(port),
            "--save-dir", str(FIXTURES),
            "--docs", str(FIXTURES / "en-US.json"),
        ]
        print(" ".join(cmd))
        proc = subprocess.Popen(cmd, env=env, cwd=state_home)
        try:
            status = wait_for(f"{base}/api/status", proc, time.time() + STARTUP_SECONDS)
            print("status:", json.dumps(status, indent=2, default=str))
            state = status.get("state") or {}
            problems = []
            if not status.get("docs_loaded"):
                problems.append("the game docs did not load")
            if status.get("last_error"):
                problems.append(f"last_error: {status['last_error']}")
            if not state.get("machines"):
                problems.append("no machines were read from the fixture save")

            report = get(f"{base}/api/report")
            if not report.get("ok"):
                problems.append(f"report failed: {report.get('error')}")
            else:
                print(f"report: {len(report['rows'])} plan rows, {len(report['unplanned'])} unplanned kinds")

            with urllib.request.urlopen(f"{base}/static/app.js", timeout=10) as response:
                if "javascript" not in response.headers["Content-Type"]:
                    problems.append(f"app.js served as {response.headers['Content-Type']}")

            if problems:
                for problem in problems:
                    print("FAIL:", problem, file=sys.stderr)
                return 1
            print("OK: the executable starts, reads the save and serves a report")
            return 0
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
