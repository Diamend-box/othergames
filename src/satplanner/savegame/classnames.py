"""Turning save-file class paths into something the planner can reason about.

Actors in the save carry a full type path such as

    /Game/FactoryGame/Buildable/Factory/SmelterMk1/Build_SmelterMk1.Build_SmelterMk1_C

and only the tail of that is useful. Classification prefers the game's own
docs when they are loaded, and falls back to name patterns when they are not,
so the app still does something sensible before the player has pointed it at
their install.
"""

from __future__ import annotations

# Machines that take a recipe and turn inputs into outputs. Used only as a
# fallback when the docs dump is unavailable.
_MANUFACTURER_HINTS = (
    "Smelter",
    "Foundry",
    "Constructor",
    "Assembler",
    "Manufacturer",
    "Refinery",
    "Packager",
    "Blender",
    "HadronCollider",
    "QuantumEncoder",
    "Converter",
)

_MINER_HINTS = ("MinerMk", "WaterPump", "OilPump", "FrackingExtractor")
_STORAGE_HINTS = ("StorageContainer", "StorageIntegrated", "FluidTank", "IndustrialTank")
_FOUNDATION_HINTS = ("Foundation", "Ramp", "Walkway_", "Platform")


def class_name_from_path(type_path: str) -> str:
    """`/Game/.../Build_SmelterMk1.Build_SmelterMk1_C` -> `Build_SmelterMk1_C`."""
    if not type_path:
        return ""
    tail = type_path.rsplit(".", 1)[-1]
    return tail.strip("'\" ")


def _matches(class_name: str, hints: tuple[str, ...]) -> bool:
    return any(hint in class_name for hint in hints)


def is_manufacturer(class_name: str, docs=None) -> bool:
    if docs is not None and docs.is_loaded:
        buildable = docs.buildables.get(class_name)
        if buildable is not None:
            return buildable.is_manufacturer
    return class_name.startswith("Build_") and _matches(class_name, _MANUFACTURER_HINTS)


def is_miner(class_name: str) -> bool:
    return class_name.startswith("Build_") and _matches(class_name, _MINER_HINTS)


def is_storage(class_name: str) -> bool:
    return class_name.startswith("Build_") and _matches(class_name, _STORAGE_HINTS)


def is_foundation(class_name: str) -> bool:
    return class_name.startswith("Build_") and _matches(class_name, _FOUNDATION_HINTS)
