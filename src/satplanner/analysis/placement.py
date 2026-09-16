"""Suggesting where new machines go, in real in-game coordinates.

Every suggestion is a cell on the world grid recovered from the player's own
foundations, so a coordinate printed here is a coordinate they can fly to.
What this does not know is terrain: it will happily suggest a cell over a
cliff or a lake. Suggestions near an existing build are therefore sound, and
suggestions far from one want checking before pouring concrete.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..gamedata import GameData
from ..plan.model import Plan
from ..savegame.model import FactoryState
from ..worldgrid import cells_covering, free_cells_near
from .diff import DiffReport


@dataclass
class Suggestion:
    block_id: str
    building_class: str
    recipe_class: str
    cell: tuple[int, int]
    world_x: float
    world_y: float

    def describe(self, docs: GameData) -> dict[str, object]:
        return {
            "block_id": self.block_id,
            "building": docs.building_name(self.building_class),
            "recipe": docs.recipes[self.recipe_class].display_name
            if self.recipe_class in docs.recipes
            else self.recipe_class,
            "cell": list(self.cell),
            "world_x": round(self.world_x, 1),
            "world_y": round(self.world_y, 1),
        }


def suggest_placements(
    state: FactoryState, plan: Plan, report: DiffReport, max_per_block: int = 60
) -> list[Suggestion]:
    """A grid cell for each machine the plan is still missing."""
    anchor = state.anchor
    occupied = cells_covering(
        [m.placement.xy for m in state.machines]
        + [s.placement.xy for s in state.storages]
        + [m.placement.xy for m in state.miners],
        anchor,
    )

    blocks_by_id = {block.id: block for block in plan.blocks}
    suggestions: list[Suggestion] = []

    for block_id in dict.fromkeys(row.block_id for row in report.rows):
        block = blocks_by_id.get(block_id)
        rows = [r for r in report.rows if r.block_id == block_id and r.missing > 0]
        if not rows:
            continue

        if block is not None and block.anchor_cell is not None:
            centre = block.anchor_cell
        else:
            # No anchor set: start beside whatever of this block already exists,
            # falling back to the middle of the built area.
            centre = _fallback_centre(state, anchor)

        wanted = min(max_per_block, sum(row.missing for row in rows))
        cells = free_cells_near(occupied, centre, wanted)
        cursor = 0
        for row in rows:
            for _ in range(row.missing):
                if cursor >= len(cells):
                    break
                cell = cells[cursor]
                cursor += 1
                occupied.add(cell)
                world_x, world_y = anchor.cell_to_world(*cell)
                suggestions.append(
                    Suggestion(
                        block_id=block_id,
                        building_class=row.building_class,
                        recipe_class=row.recipe_class,
                        cell=cell,
                        world_x=world_x,
                        world_y=world_y,
                    )
                )
    return suggestions


def _fallback_centre(state: FactoryState, anchor) -> tuple[int, int]:
    """The middle of everything built so far, in cells."""
    points = [m.placement.xy for m in state.machines] or [
        f.placement.xy for f in state.foundations
    ]
    if not points:
        return (0, 0)
    mean_x = sum(p[0] for p in points) / len(points)
    mean_y = sum(p[1] for p in points) / len(points)
    return anchor.world_to_cell(mean_x, mean_y)
