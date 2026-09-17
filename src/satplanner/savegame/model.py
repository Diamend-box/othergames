"""What the planner knows about the factory as it stands right now.

Deliberately a much smaller model than the save file itself: everything here
exists because some part of the planner needs it, and nothing is carried over
just because the parser exposed it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..worldgrid import GridAnchor


@dataclass(frozen=True)
class Placement:
    """Where something sits in the world, in Unreal units."""

    x: float
    y: float
    z: float
    yaw_deg: float = 0.0

    @property
    def xy(self) -> tuple[float, float]:
        return (self.x, self.y)


@dataclass
class Machine:
    """A production building: constructor, smelter, refinery and friends."""

    instance_name: str
    building_class: str
    placement: Placement
    recipe_class: str | None = None
    clock: float = 1.0
    sloops: int = 0

    @property
    def key(self) -> tuple[str, str | None]:
        """What makes two machines interchangeable for planning purposes."""
        return (self.building_class, self.recipe_class)


@dataclass
class Miner:
    instance_name: str
    building_class: str
    placement: Placement
    node_instance: str | None = None
    clock: float = 1.0


@dataclass
class Storage:
    instance_name: str
    building_class: str
    placement: Placement
    stacks: dict[str, int] = field(default_factory=dict)


@dataclass
class Structure:
    """Anything placed that is not a machine - foundations, belts, walls.

    Foundations are the interesting ones: they are what the world grid is
    recovered from.
    """

    instance_name: str
    building_class: str
    placement: Placement


@dataclass
class FactoryState:
    save_name: str = ""
    save_version: int = 0
    build_version: int = 0
    play_time_seconds: float = 0.0
    machines: list[Machine] = field(default_factory=list)
    miners: list[Miner] = field(default_factory=list)
    storages: list[Storage] = field(default_factory=list)
    foundations: list[Structure] = field(default_factory=list)
    player_inventory: dict[str, int] = field(default_factory=dict)
    anchor: GridAnchor = field(default_factory=GridAnchor)
    warnings: list[str] = field(default_factory=list)
    source_path: str | None = None
    parsed_at: float = 0.0

    def machine_counts(self) -> dict[tuple[str, str | None], int]:
        """How many machines are running each (building, recipe) pairing."""
        counts: dict[tuple[str, str | None], int] = defaultdict(int)
        for machine in self.machines:
            counts[machine.key] += 1
        return dict(counts)

    def total_items(self) -> dict[str, int]:
        """Everything sitting in containers plus the player's own pockets."""
        totals: dict[str, int] = defaultdict(int)
        for storage in self.storages:
            for item, count in storage.stacks.items():
                totals[item] += count
        for item, count in self.player_inventory.items():
            totals[item] += count
        return dict(totals)

    def occupied_nodes(self) -> set[str]:
        return {m.node_instance for m in self.miners if m.node_instance}

    def summary(self) -> dict[str, object]:
        return {
            "save_name": self.save_name,
            "save_version": self.save_version,
            "build_version": self.build_version,
            "play_time_hours": round(self.play_time_seconds / 3600.0, 1),
            "machines": len(self.machines),
            "miners": len(self.miners),
            "storages": len(self.storages),
            "foundations": len(self.foundations),
            "distinct_items_stored": len(self.total_items()),
            "warnings": self.warnings,
            "source_path": self.source_path,
        }
