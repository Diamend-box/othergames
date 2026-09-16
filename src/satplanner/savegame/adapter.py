"""Bridge from GreyHak's `sat_sav_parse` to the planner's own model.

The upstream parser is GPL-3 and ships no package metadata, so it is fetched
into `vendor/` by `scripts/fetch_parser.py` rather than vendored into this
repository or installed from PyPI. Keeping it behind this one module means the
rest of the app depends on `FactoryState`, not on somebody else's data shapes,
and a future swap to a different parser touches only this file.

Every field read here is read defensively. The save format moves between game
versions and a missing property should cost one machine's recipe, not the whole
report, so failures are collected as warnings instead of raised.
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path
from typing import Any

from .. import config
from ..gamedata import GameData
from ..worldgrid import infer_anchor
from . import classnames as cn
from .model import FactoryState, Machine, Miner, Placement, Storage, Structure

# Save-format versions the upstream parser recognises, mapped to the game
# releases that wrote them. Anything outside this set still gets parsed, but
# the user is warned that the results may be wrong.
SUPPORTED_SAVE_VERSIONS = {
    58: "1.2.0.0 - 1.2.1.0",
    59: "1.2.2.0",
    60: "1.2.2.1",
}

_MAX_WARNINGS = 25


class ParserUnavailable(RuntimeError):
    """The upstream save parser has not been fetched into vendor/."""


def ensure_parser():
    """Import `sav_parse` from vendor/, with a useful error if it is missing."""
    vendor = config.vendor_dir()
    candidates = [vendor / "sat_sav_parse", vendor]
    for candidate in candidates:
        if (candidate / "sav_parse.py").is_file():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            break
    try:
        import sav_parse  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on local setup
        raise ParserUnavailable(
            "The Satisfactory save parser is not installed. Run "
            "`python scripts/fetch_parser.py` to download it into vendor/."
        ) from exc

    # The parser draws progress bars on stdout, which is noise inside a server.
    for flag in ("PROGRESS_BAR_ENABLE_DECOMPRESS", "PROGRESS_BAR_ENABLE_PARSE", "PROGRESS_BAR_ENABLE_DUMP"):
        if hasattr(sav_parse, flag):
            setattr(sav_parse, flag, False)
    return sav_parse


def _prop(sav_parse, obj: Any, *names: str) -> Any:
    """First matching property value, or None.

    Several properties have been renamed across game versions, so callers pass
    every spelling they know about.
    """
    try:
        properties = getattr(obj, "properties", None)
    except Exception:
        # A corrupt property block costs this one field, not the building:
        # its class and position came from the header and are still good.
        return None
    if not properties:
        return None
    for name in names:
        try:
            value = sav_parse.getPropertyValue(properties, name)
        except Exception:
            continue
        if value is not None:
            return value
    return None


def _path_name(value: Any) -> str | None:
    """Pull a path out of an object reference, whatever shape it arrived in."""
    if value is None:
        return None
    path = getattr(value, "pathName", None)
    if isinstance(path, str) and path:
        return path
    if isinstance(value, str) and value:
        return value
    if isinstance(value, (list, tuple)) and value:
        return _path_name(value[-1])
    return None


def _yaw_from_quaternion(rotation: Any) -> float:
    """Yaw in degrees from the actor's [x, y, z, w] quaternion."""
    try:
        x, y, z, w = (float(v) for v in rotation[:4])
    except (TypeError, ValueError, IndexError):
        return 0.0
    return math.degrees(math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z)))


def _placement(header: Any) -> Placement:
    position = getattr(header, "position", None) or (0.0, 0.0, 0.0)
    try:
        x, y, z = (float(v) for v in position[:3])
    except (TypeError, ValueError):
        x = y = z = 0.0
    return Placement(x=x, y=y, z=z, yaw_deg=_yaw_from_quaternion(getattr(header, "rotation", None)))


def _stacks_from_inventory(inventory_stacks: Any) -> dict[str, int]:
    """Flatten `mInventoryStacks` into {item class name: count}.

    The stored shape is deeply nested - each stack is a pair of named
    properties, `Item` (whose value carries the item's path) and `NumItems`.
    """
    totals: dict[str, int] = {}
    if not inventory_stacks:
        return totals
    for stack in inventory_stacks:
        try:
            entry = stack[0]
            fields = {str(field[0]): field[1] for field in entry}
        except (TypeError, IndexError, KeyError):
            continue
        item_field = fields.get("Item")
        count = fields.get("NumItems")
        path = _path_name(item_field[0] if isinstance(item_field, (list, tuple)) else item_field)
        if not path or not isinstance(count, (int, float)) or count <= 0:
            continue
        item_class = cn.class_name_from_path(path)
        if item_class:
            totals[item_class] = totals.get(item_class, 0) + int(count)
    return totals


def build_state(sav_parse, parsed_save: Any, docs: GameData | None = None, source_path: str | None = None) -> FactoryState:
    """Walk a parsed save and pull out everything the planner needs.

    Split out from `load_state` so it can be exercised with stand-in objects
    in the tests without a real 30 MB save on disk.
    """
    state = FactoryState(source_path=source_path, parsed_at=time.time())

    info = getattr(parsed_save, "saveFileInfo", None)
    if info is not None:
        state.save_name = str(getattr(info, "saveName", "") or "")
        state.save_version = int(getattr(info, "saveVersion", 0) or 0)
        state.build_version = int(getattr(info, "buildVersion", 0) or 0)
        play_ticks = getattr(info, "playDurationSeconds", None)
        if isinstance(play_ticks, (int, float)):
            state.play_time_seconds = float(play_ticks)

    if state.save_version and state.save_version not in SUPPORTED_SAVE_VERSIONS:
        state.warnings.append(
            f"Save format version {state.save_version} is not one this build has been "
            f"checked against ({', '.join(str(v) for v in sorted(SUPPORTED_SAVE_VERSIONS))}). "
            "Numbers may be wrong."
        )

    # Objects carry the properties, headers carry the type and the transform.
    # They are matched on instance name rather than list position so a parser
    # change in ordering cannot silently misattribute recipes.
    objects_by_name: dict[str, Any] = {}
    for level in getattr(parsed_save, "levels", []):
        for obj in getattr(level, "objects", []):
            name = getattr(obj, "instanceName", None)
            if name:
                objects_by_name[name] = obj

    foundation_positions: list[tuple[float, float]] = []

    for level in getattr(parsed_save, "levels", []):
        for header in getattr(level, "actorAndComponentObjectHeaders", []):
            type_path = getattr(header, "typePath", None)
            instance_name = getattr(header, "instanceName", None)
            if not type_path or not instance_name:
                continue
            class_name = cn.class_name_from_path(type_path)
            if not class_name.startswith("Build_"):
                continue

            placement = _placement(header)
            obj = objects_by_name.get(instance_name)

            try:
                if cn.is_foundation(class_name):
                    foundation_positions.append(placement.xy)
                    state.foundations.append(
                        Structure(instance_name, class_name, placement)
                    )
                elif cn.is_miner(class_name):
                    node_ref = _prop(sav_parse, obj, "mExtractResourceNode", "mExtractableResource")
                    state.miners.append(
                        Miner(
                            instance_name=instance_name,
                            building_class=class_name,
                            placement=placement,
                            node_instance=_path_name(node_ref),
                            clock=_clock(sav_parse, obj),
                        )
                    )
                elif cn.is_storage(class_name):
                    state.storages.append(
                        Storage(
                            instance_name=instance_name,
                            building_class=class_name,
                            placement=placement,
                            stacks=_inventory_of(sav_parse, obj, objects_by_name),
                        )
                    )
                elif cn.is_manufacturer(class_name, docs):
                    recipe_ref = _path_name(_prop(sav_parse, obj, "mCurrentRecipe"))
                    state.machines.append(
                        Machine(
                            instance_name=instance_name,
                            building_class=class_name,
                            placement=placement,
                            recipe_class=cn.class_name_from_path(recipe_ref) if recipe_ref else None,
                            clock=_clock(sav_parse, obj),
                            sloops=_sloops(sav_parse, obj),
                        )
                    )
            except Exception as exc:  # one bad actor must not lose the report
                if len(state.warnings) < _MAX_WARNINGS:
                    state.warnings.append(f"Skipped {class_name} ({instance_name}): {exc}")

    state.anchor = infer_anchor(foundation_positions, source="foundations")
    if not foundation_positions:
        state.warnings.append(
            "No foundations found, so the grid falls back to the world origin. "
            "Place some foundations and refresh to line the grid up with your base."
        )
    return state


def _clock(sav_parse, obj: Any) -> float:
    value = _prop(sav_parse, obj, "mCurrentPotential", "mPendingPotential")
    return float(value) if isinstance(value, (int, float)) and value > 0 else 1.0


def _sloops(sav_parse, obj: Any) -> int:
    value = _prop(sav_parse, obj, "mProductionBoost", "mCurrentProductionBoost")
    if isinstance(value, (int, float)) and value > 1:
        # Stored as a multiplier rather than a count; one sloop doubles output.
        return int(round(value)) - 1
    return 0


def _inventory_of(sav_parse, obj: Any, objects_by_name: dict[str, Any]) -> dict[str, int]:
    """Follow a building's inventory component and read its stacks."""
    if obj is None:
        return {}
    direct = _prop(sav_parse, obj, "mInventoryStacks")
    if direct:
        return _stacks_from_inventory(direct)
    ref = _path_name(_prop(sav_parse, obj, "mStorageInventory", "mInventory"))
    if not ref:
        return {}
    component = objects_by_name.get(ref)
    if component is None:
        return {}
    return _stacks_from_inventory(_prop(sav_parse, component, "mInventoryStacks"))


def load_state(path: Path, docs: GameData | None = None) -> FactoryState:
    """Parse a `.sav` file into a `FactoryState`."""
    sav_parse = ensure_parser()
    parsed = sav_parse.readFullSaveFile(str(path))
    return build_state(sav_parse, parsed, docs=docs, source_path=str(path))
