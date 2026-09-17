#!/usr/bin/env python3
"""Fetch the Satisfactory save parser this app reads save files with.

GreyHak's `sat_sav_parse` is the parser that tracks the 1.2 save format most
closely (it names v1.2.0.0 through v1.2.2.1 explicitly). It is GPL-3 licensed
and publishes no package on PyPI, so it is downloaded into `vendor/` at setup
time rather than committed into this repository - that keeps this project's
own licensing separate from it, and makes updating to a new game patch a
matter of re-running this script.

    python scripts/fetch_parser.py [--ref <branch-or-tag>]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_URL = "https://github.com/GreyHak/sat_sav_parse.git"
TARGET = Path(__file__).resolve().parents[1] / "vendor" / "sat_sav_parse"


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default=None, help="Branch, tag or commit to check out")
    parser.add_argument("--force", action="store_true", help="Delete and re-clone")
    args = parser.parse_args()

    if TARGET.exists() and args.force:
        shutil.rmtree(TARGET)

    if TARGET.exists():
        print(f"Updating {TARGET}")
        run("git", "fetch", "--depth", "1", "origin", args.ref or "HEAD", cwd=TARGET)
        run("git", "checkout", "FETCH_HEAD", cwd=TARGET)
    else:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        print(f"Cloning {REPO_URL} into {TARGET}")
        cmd = ["git", "clone", "--depth", "1"]
        if args.ref:
            cmd += ["--branch", args.ref]
        run(*cmd, REPO_URL, str(TARGET))

    if not (TARGET / "sav_parse.py").is_file():
        print("ERROR: sav_parse.py missing after fetch", file=sys.stderr)
        return 1

    print("Done. The parser is GPL-3; see vendor/sat_sav_parse/LICENSE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
