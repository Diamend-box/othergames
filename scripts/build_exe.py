#!/usr/bin/env python3
"""Package the planner as a single Windows executable.

Run on Windows (PyInstaller does not cross-compile). CI does this on a
windows-latest runner; see .github/workflows/windows-build.yml.

    python scripts/fetch_parser.py
    python scripts/build_exe.py

The result is dist/SatisfactoryPlanner.exe - double-click it and the UI opens
in the default browser.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEPARATOR = ";" if sys.platform == "win32" else ":"


def main() -> int:
    static = ROOT / "src" / "satplanner" / "web" / "static"
    parser = ROOT / "vendor" / "sat_sav_parse"

    if not parser.is_file() and not (parser / "sav_parse.py").is_file():
        print("Save parser missing - run scripts/fetch_parser.py first", file=sys.stderr)
        return 1

    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--name", "SatisfactoryPlanner",
        "--paths", str(ROOT / "src"),
        # The UI files and the save parser both have to travel with the exe.
        "--add-data", f"{static}{SEPARATOR}satplanner/web/static",
        "--add-data", f"{parser}{SEPARATOR}sat_sav_parse",
        # The parser is imported dynamically once a save is opened.
        "--hidden-import", "sav_parse",
        "--collect-submodules", "sav_data",
        str(ROOT / "src" / "satplanner" / "__main__.py"),
    ]
    print(" ".join(args))
    return subprocess.run(args, cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
