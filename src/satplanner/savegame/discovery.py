"""Finding save files and noticing when the game writes a new one."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


@dataclass(frozen=True)
class SaveFile:
    path: Path
    name: str
    modified: float
    size_bytes: int

    def describe(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "name": self.name,
            "modified": self.modified,
            "modified_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.modified)),
            "size_mb": round(self.size_bytes / (1024 * 1024), 1),
        }


def list_saves(save_dir: Path | None) -> list[SaveFile]:
    """Every `.sav` under the save folder, newest first.

    Satisfactory keeps one subfolder per account plus `common`, so the search
    is recursive. Autosaves are included - they are usually the freshest view
    of the factory.
    """
    if save_dir is None or not Path(save_dir).is_dir():
        return []
    saves: list[SaveFile] = []
    for path in Path(save_dir).rglob("*.sav"):
        try:
            stat = path.stat()
        except OSError:
            continue
        saves.append(
            SaveFile(path=path, name=path.stem, modified=stat.st_mtime, size_bytes=stat.st_size)
        )
    return sorted(saves, key=lambda s: s.modified, reverse=True)


def latest_save(save_dir: Path | None) -> SaveFile | None:
    saves = list_saves(save_dir)
    return saves[0] if saves else None


def newest_session(saves: Iterable[SaveFile]) -> list[SaveFile]:
    """Group saves by session name, keeping the newest of each.

    Save folders accumulate dozens of autosaves; this is what the save picker
    in the UI lists so the player sees their worlds, not their backups.
    """
    best: dict[str, SaveFile] = {}
    for save in saves:
        stem = save.name.split("_autosave_")[0]
        current = best.get(stem)
        if current is None or save.modified > current.modified:
            best[stem] = save
    return sorted(best.values(), key=lambda s: s.modified, reverse=True)


class SaveWatcher:
    """Polls a save file's timestamp and fires a callback when it changes.

    Saves only land on disk at an autosave or a manual save, so polling every
    minute is as live as this data ever gets - there is nothing to be gained
    from a filesystem watcher here, and polling survives the atomic replace
    the game does when it writes.
    """

    def __init__(self, get_path: Callable[[], Path | None], on_change: Callable[[Path], None], interval: float = 60.0):
        self._get_path = get_path
        self._on_change = on_change
        self._interval = interval
        self._seen: tuple[str, float] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="save-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def check_once(self) -> bool:
        """Returns True if the save changed since the last check."""
        path = self._get_path()
        if path is None:
            return False
        try:
            modified = Path(path).stat().st_mtime
        except OSError:
            return False
        fingerprint = (str(path), modified)
        if fingerprint == self._seen:
            return False
        self._seen = fingerprint
        self._on_change(Path(path))
        return True

    def _run(self) -> None:  # pragma: no cover - timing loop
        while not self._stop.wait(self._interval):
            try:
                self.check_once()
            except Exception:
                # A transient read failure while the game rewrites the file is
                # normal; the next poll picks it up.
                continue
