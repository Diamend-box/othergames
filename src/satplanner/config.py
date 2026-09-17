"""Where things live on disk, and how the app finds them.

Everything here is overridable by environment variable so the app can be
developed and tested away from a Windows machine with the game installed.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

ENV_SAVE_DIR = "SATPLANNER_SAVE_DIR"
ENV_DOCS = "SATPLANNER_DOCS"
ENV_GAME_DIR = "SATPLANNER_GAME_DIR"
ENV_MODELER_DIR = "SATPLANNER_MODELER_DIR"
ENV_VENDOR = "SATPLANNER_VENDOR"

# Steam library roots worth checking before parsing libraryfolders.vdf.
_COMMON_STEAM_ROOTS = [
    Path("C:/Program Files (x86)/Steam"),
    Path("C:/Steam"),
    Path.home() / ".steam/steam",
    Path.home() / ".local/share/Steam",
]


def default_save_dir() -> Path | None:
    """The folder Satisfactory writes saves into.

    On Windows this is %LOCALAPPDATA%\\FactoryGame\\Saved\\SaveGames, which
    holds one subfolder per account plus a `common` folder.
    """
    override = os.environ.get(ENV_SAVE_DIR)
    if override:
        return Path(override)

    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidate = Path(local) / "FactoryGame" / "Saved" / "SaveGames"
        if candidate.is_dir():
            return candidate
    return None


def steam_library_roots() -> list[Path]:
    """Every Steam library folder we can find, deduplicated."""
    roots: list[Path] = []
    for root in _COMMON_STEAM_ROOTS:
        if not root.is_dir():
            continue
        roots.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if not vdf.is_file():
            continue
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # libraryfolders.vdf is Valve's key-value format; the only thing we
        # want out of it is the "path" values, so a scan beats a real parser.
        for line in text.splitlines():
            parts = [p for p in line.split('"') if p.strip()]
            if len(parts) >= 2 and parts[0].strip() == "path":
                roots.append(Path(parts[1]))
    seen: set[str] = set()
    unique: list[Path] = []
    for root in roots:
        key = str(root).lower()
        if key not in seen and root.is_dir():
            seen.add(key)
            unique.append(root)
    return unique


def find_game_dir() -> Path | None:
    """The Satisfactory install folder."""
    override = os.environ.get(ENV_GAME_DIR)
    if override:
        path = Path(override)
        return path if path.is_dir() else None
    for root in steam_library_roots():
        candidate = root / "steamapps" / "common" / "Satisfactory"
        if candidate.is_dir():
            return candidate
    return None


def find_modeler_dir() -> Path | None:
    """The Satisfactory Modeler install folder.

    Modeler is a separate Steam app. Its project files have been reported to
    live inside its install directory; `plan.modeler` sniffs whatever is
    actually there rather than assuming a format.
    """
    override = os.environ.get(ENV_MODELER_DIR)
    if override:
        path = Path(override)
        return path if path.is_dir() else None
    for root in steam_library_roots():
        candidate = root / "steamapps" / "common" / "Satisfactory Modeler"
        if candidate.is_dir():
            return candidate
    return None


def find_docs_json() -> Path | None:
    """The game's own item/recipe dump, shipped under CommunityResources/Docs.

    Reading this from the player's install means the planner's numbers always
    match the patch they are running instead of drifting from a hardcoded table.
    """
    override = os.environ.get(ENV_DOCS)
    if override:
        path = Path(override)
        return path if path.is_file() else None

    game_dir = find_game_dir()
    if game_dir is None:
        return None
    docs_dir = game_dir / "CommunityResources" / "Docs"
    if not docs_dir.is_dir():
        return None
    for name in ("en-US.json", "Docs.json"):
        candidate = docs_dir / name
        if candidate.is_file():
            return candidate
    for candidate in sorted(docs_dir.glob("*.json")):
        return candidate
    return None


def vendor_dir() -> Path:
    """Where `scripts/fetch_parser.py` puts the upstream save parser.

    In a PyInstaller build the parser is bundled alongside the app rather than
    sitting in a vendor folder, so the unpack directory is used instead.
    """
    override = os.environ.get(ENV_VENDOR)
    if override:
        return Path(override)
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled)
    return Path(__file__).resolve().parents[2] / "vendor"


def state_dir() -> Path:
    """Where the app keeps its own files (the active plan, settings)."""
    base = os.environ.get("APPDATA") or os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    path = root / "satplanner"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Settings:
    save_dir: Path | None = field(default_factory=default_save_dir)
    docs_json: Path | None = field(default_factory=find_docs_json)
    modeler_dir: Path | None = field(default_factory=find_modeler_dir)
    poll_seconds: int = 60
    host: str = "127.0.0.1"
    port: int = 8711

    def describe(self) -> dict[str, object]:
        return {
            "save_dir": str(self.save_dir) if self.save_dir else None,
            "docs_json": str(self.docs_json) if self.docs_json else None,
            "modeler_dir": str(self.modeler_dir) if self.modeler_dir else None,
            "poll_seconds": self.poll_seconds,
        }
