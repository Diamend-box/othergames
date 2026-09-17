"""Entry point: `python -m satplanner`, or the packaged executable."""

from __future__ import annotations

import argparse
from pathlib import Path

# Absolute imports on purpose: PyInstaller runs this file as a top-level
# script, where relative imports have no parent package to resolve against.
from satplanner.config import Settings
from satplanner.web.server import serve


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="satplanner",
        description="Compare your Satisfactory save against a factory plan.",
    )
    parser.add_argument("--save-dir", type=Path, default=None, help="Folder holding your .sav files")
    parser.add_argument("--docs", type=Path, default=None, help="Path to the game's Docs JSON")
    parser.add_argument("--modeler-dir", type=Path, default=None, help="Satisfactory Modeler install folder")
    parser.add_argument("--port", type=int, default=8711)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--poll", type=int, default=60, help="Seconds between save-file checks")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser window")
    args = parser.parse_args()

    settings = Settings()
    if args.save_dir:
        settings.save_dir = args.save_dir
    if args.docs:
        settings.docs_json = args.docs
    if args.modeler_dir:
        settings.modeler_dir = args.modeler_dir
    settings.port = args.port
    settings.host = args.host
    settings.poll_seconds = args.poll

    serve(settings, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
