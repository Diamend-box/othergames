"""The planner's own representation of a factory plan.

Kept independent of whatever Satisfactory Modeler turns out to write, so an
importer for that format only has to produce one of these.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class PlanMachine:
    """`count` machines of `building_class` all running `recipe_class`."""

    building_class: str
    recipe_class: str
    count: int
    clock: float = 1.0

    @property
    def key(self) -> tuple[str, str]:
        return (self.building_class, self.recipe_class)


@dataclass
class PlanBlock:
    """A named chunk of factory - one build site, one job."""

    id: str
    name: str
    machines: list[PlanMachine] = field(default_factory=list)
    # Where this block lives on the world grid, as cell indices. Optional:
    # without it the planner pools machines globally instead of per site.
    anchor_cell: tuple[int, int] | None = None
    notes: str = ""

    def machine_counts(self) -> dict[tuple[str, str], int]:
        counts: dict[tuple[str, str], int] = defaultdict(int)
        for machine in self.machines:
            counts[machine.key] += machine.count
        return dict(counts)


@dataclass
class Plan:
    name: str = "Untitled plan"
    blocks: list[PlanBlock] = field(default_factory=list)
    source: str = "manual"
    warnings: list[str] = field(default_factory=list)

    def machine_counts(self) -> dict[tuple[str, str], int]:
        counts: dict[tuple[str, str], int] = defaultdict(int)
        for block in self.blocks:
            for key, count in block.machine_counts().items():
                counts[key] += count
        return dict(counts)

    @property
    def total_machines(self) -> int:
        return sum(self.machine_counts().values())

    def to_dict(self) -> dict:
        data = asdict(self)
        for block in data["blocks"]:
            if block["anchor_cell"] is not None:
                block["anchor_cell"] = list(block["anchor_cell"])
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Plan":
        blocks = []
        for raw in data.get("blocks", []):
            anchor = raw.get("anchor_cell")
            blocks.append(
                PlanBlock(
                    id=str(raw.get("id") or raw.get("name") or f"block{len(blocks) + 1}"),
                    name=str(raw.get("name") or raw.get("id") or "Block"),
                    machines=[
                        PlanMachine(
                            building_class=str(m["building_class"]),
                            recipe_class=str(m["recipe_class"]),
                            count=int(m.get("count", 1)),
                            clock=float(m.get("clock", 1.0)),
                        )
                        for m in raw.get("machines", [])
                    ],
                    anchor_cell=(int(anchor[0]), int(anchor[1])) if anchor else None,
                    notes=str(raw.get("notes", "")),
                )
            )
        return cls(
            name=str(data.get("name", "Untitled plan")),
            blocks=blocks,
            source=str(data.get("source", "manual")),
        )

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Plan":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
