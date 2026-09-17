"""Importing a plan out of Satisfactory Modeler.

Modeler is a separate Steam application and its project format is not
documented anywhere I could find, so this module does not pretend to know it.
Instead it *identifies* what is on disk - `sniff_directory` reports the shape
of every candidate file it finds - and imports the formats it can actually
read. Point the app at the Modeler folder and the report says exactly what
we are dealing with; writing the real importer is then a small job.

If the format turns out to be opaque binary, the fallback is the native plan
editor rather than guesswork.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .model import Plan, PlanBlock, PlanMachine
from .sfmd import import_sfmd, looks_like_sfmd

# File extensions that belong to the application rather than the player's work.
_IGNORED_SUFFIXES = {
    ".dll", ".exe", ".pak", ".uasset", ".uexe", ".so", ".dylib", ".pdb",
    ".png", ".jpg", ".jpeg", ".ico", ".ttf", ".otf", ".wav", ".ogg", ".mp3",
    ".log", ".tmp",
}

_MAGIC = [
    (b"SQLite format 3\x00", "sqlite"),
    (b"PK\x03\x04", "zip"),
    (b"\x1f\x8b", "gzip"),
]


class UnknownModelerFormat(RuntimeError):
    """The file was found but its format is not one we can read yet."""

    def __init__(self, message: str, report: "FormatReport | None" = None):
        super().__init__(message)
        self.report = report


@dataclass
class FormatReport:
    path: str
    size_bytes: int
    kind: str
    detail: str = ""
    top_level_keys: list[str] = field(default_factory=list)
    preview: str = ""

    def describe(self) -> dict[str, object]:
        return {
            "path": self.path,
            "size_kb": round(self.size_bytes / 1024, 1),
            "kind": self.kind,
            "detail": self.detail,
            "top_level_keys": self.top_level_keys,
            "preview": self.preview,
            "importable": self.kind in {"json", "sqlite"},
        }


def _printable_preview(raw: bytes, limit: int = 240) -> str:
    """Readable ASCII runs from a binary head - often enough to name a format."""
    out: list[str] = []
    run: list[str] = []
    for byte in raw:
        if 32 <= byte < 127:
            run.append(chr(byte))
        else:
            if len(run) >= 4:
                out.append("".join(run))
            run = []
    if len(run) >= 4:
        out.append("".join(run))
    return " | ".join(out)[:limit]


def sniff_file(path: Path) -> FormatReport:
    """Work out what kind of file this is without assuming anything."""
    path = Path(path)
    try:
        size = path.stat().st_size
        head = path.open("rb").read(8192)
    except OSError as exc:
        return FormatReport(path=str(path), size_bytes=0, kind="unreadable", detail=str(exc))

    report = FormatReport(path=str(path), size_bytes=size, kind="unknown")

    for magic, kind in _MAGIC:
        if head.startswith(magic):
            report.kind = kind
            if kind == "sqlite":
                report.top_level_keys = _sqlite_tables(path)
                report.detail = f"SQLite database with tables: {', '.join(report.top_level_keys) or 'none'}"
            elif kind == "zip":
                report.detail = "Zip container - may hold JSON or XML inside"
            report.preview = _printable_preview(head)
            return report

    for encoding in ("utf-8-sig", "utf-8", "utf-16"):
        try:
            text = head.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
        stripped = text.lstrip()
        if stripped.startswith(("{", "[")):
            report.kind = "json"
            try:
                payload = json.loads(path.read_text(encoding=encoding))
                if isinstance(payload, dict):
                    report.top_level_keys = sorted(payload.keys())[:40]
                    report.detail = f"JSON object with {len(payload)} top-level keys"
                else:
                    report.detail = f"JSON array of {len(payload)} entries"
            except (json.JSONDecodeError, OSError, UnicodeError) as exc:
                report.detail = f"Looks like JSON but did not parse: {exc}"
            report.preview = stripped[:240]
            return report
        if stripped.startswith("<"):
            report.kind = "xml"
            report.preview = stripped[:240]
            return report
        break

    report.kind = "binary"
    report.detail = "Not JSON, XML, SQLite or a zip - needs reverse engineering"
    report.preview = _printable_preview(head)
    return report


def _sqlite_tables(path: Path) -> list[str]:
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        return [row[0] for row in rows]
    except sqlite3.Error:
        return []


def sniff_directory(directory: Path | None, max_files: int = 60) -> list[FormatReport]:
    """Report on every plausible project file in the Modeler folder."""
    if directory is None or not Path(directory).is_dir():
        return []
    reports: list[FormatReport] = []
    for path in sorted(Path(directory).rglob("*")):
        if len(reports) >= max_files:
            break
        if not path.is_file() or path.suffix.lower() in _IGNORED_SUFFIXES:
            continue
        try:
            if path.stat().st_size > 64 * 1024 * 1024:
                continue
        except OSError:
            continue
        reports.append(sniff_file(path))
    # Files we can actually read are the interesting ones, so float them up.
    reports.sort(key=lambda r: (r.kind not in {"json", "sqlite"}, r.path))
    return reports


# -- import --------------------------------------------------------------


_BUILDING_KEYS = ("building_class", "building", "machine", "machineType", "buildingName")
_RECIPE_KEYS = ("recipe_class", "recipe", "recipeName", "recipeId")
_COUNT_KEYS = ("count", "quantity", "amount", "machines", "machineCount", "qty")
_CLOCK_KEYS = ("clock", "clockSpeed", "overclock", "potential")


def _first(entry: dict, keys: Iterable[str]) -> Any:
    for key in keys:
        for candidate in (key, key.lower(), key.upper()):
            if candidate in entry:
                return entry[candidate]
    return None


def _as_machine(entry: Any) -> PlanMachine | None:
    """Best-effort read of one machine line from an unknown JSON shape."""
    if not isinstance(entry, dict):
        return None
    recipe = _first(entry, _RECIPE_KEYS)
    if not isinstance(recipe, str) or not recipe:
        return None
    building = _first(entry, _BUILDING_KEYS)
    count = _first(entry, _COUNT_KEYS)
    clock = _first(entry, _CLOCK_KEYS)
    try:
        count_value = int(float(count)) if count is not None else 1
    except (TypeError, ValueError):
        count_value = 1
    try:
        clock_value = float(clock) if clock is not None else 1.0
    except (TypeError, ValueError):
        clock_value = 1.0
    if clock_value > 10:  # given as a percentage rather than a multiplier
        clock_value /= 100.0
    return PlanMachine(
        building_class=str(building) if isinstance(building, str) and building else "Build_Unknown_C",
        recipe_class=recipe,
        count=max(1, count_value),
        clock=clock_value,
    )


def _walk_for_machines(payload: Any, depth: int = 0) -> list[PlanMachine]:
    """Find machine-shaped records anywhere in a JSON document."""
    if depth > 8:
        return []
    found: list[PlanMachine] = []
    if isinstance(payload, list):
        for entry in payload:
            machine = _as_machine(entry)
            if machine is not None:
                found.append(machine)
            else:
                found.extend(_walk_for_machines(entry, depth + 1))
    elif isinstance(payload, dict):
        for value in payload.values():
            found.extend(_walk_for_machines(value, depth + 1))
    return found


def import_json_plan(payload: Any, name: str, source: str, docs=None) -> Plan:
    """Turn a JSON document into a plan, natively or by inference."""
    if looks_like_sfmd(payload):
        plan, warnings = import_sfmd(payload, name=name, source=source, docs=docs)
        plan.warnings = warnings
        return plan
    if isinstance(payload, dict) and "blocks" in payload:
        plan = Plan.from_dict(payload)
        plan.source = source
        return plan

    machines = _walk_for_machines(payload)
    if not machines:
        raise UnknownModelerFormat(
            "Read the file as JSON but found nothing that looks like a machine "
            "list. Send the file over and the importer can be taught its shape."
        )
    return Plan(
        name=name,
        blocks=[PlanBlock(id="imported", name="Imported from Modeler", machines=machines)],
        source=source,
    )


def import_plan(path: Path, docs=None) -> Plan:
    """Import a Modeler export, or explain precisely why it could not be."""
    path = Path(path)
    report = sniff_file(path)
    if report.kind == "json":
        for encoding in ("utf-8-sig", "utf-8", "utf-16"):
            try:
                payload = json.loads(path.read_text(encoding=encoding))
            except (UnicodeError, json.JSONDecodeError):
                continue
            return import_json_plan(payload, name=path.stem, source=f"modeler:{path.name}", docs=docs)
        raise UnknownModelerFormat("File looked like JSON but could not be decoded.", report)
    raise UnknownModelerFormat(
        f"'{path.name}' is {report.kind}, which the importer cannot read yet. {report.detail}",
        report,
    )
