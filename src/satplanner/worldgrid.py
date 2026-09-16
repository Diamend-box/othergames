"""Mapping between Satisfactory world coordinates and a foundation grid.

Satisfactory measures the world in Unreal units, where 1 uu == 1 cm, so an 8 m
foundation is 800 uu on a side. Buildings placed on foundations snap to that
foundation lattice, which means every factory in a save shares a global grid
whose *phase* was fixed by wherever the very first foundation happened to land.

This module recovers that phase from the save (see `infer_anchor`) so the
planner's grid lines up with the one in the running game: a cell in the app is
the same cell on the player's screen, and any position the planner suggests can
be read straight off as in-game coordinates.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

# Unreal units per metre. Satisfactory works in centimetres.
UU_PER_METRE = 100.0

# Foundation footprints available in game, in Unreal units.
FOUNDATION_SIZES_UU = {
    "1m": 100.0,
    "2m": 200.0,
    "4m": 400.0,
    "8m": 800.0,
}

DEFAULT_CELL_UU = FOUNDATION_SIZES_UU["8m"]


@dataclass(frozen=True)
class GridAnchor:
    """The origin and pitch of the in-game foundation lattice.

    `origin_x`/`origin_y` are the world coordinates of the centre of cell
    (0, 0). `cell_uu` is the lattice pitch. Only axis-aligned grids are
    supported; rotated foundation fields are noted as a limitation in the
    README rather than silently mis-snapped.
    """

    origin_x: float = 0.0
    origin_y: float = 0.0
    cell_uu: float = DEFAULT_CELL_UU
    source: str = "default"

    def world_to_cell(self, x: float, y: float) -> tuple[int, int]:
        """World coordinates -> the cell containing them."""
        return (
            math.floor((x - self.origin_x) / self.cell_uu + 0.5),
            math.floor((y - self.origin_y) / self.cell_uu + 0.5),
        )

    def cell_to_world(self, cx: int, cy: int) -> tuple[float, float]:
        """Cell indices -> the world coordinates of that cell's centre."""
        return (
            self.origin_x + cx * self.cell_uu,
            self.origin_y + cy * self.cell_uu,
        )

    def snap(self, x: float, y: float) -> tuple[float, float]:
        """Nudge a world position onto the nearest lattice point."""
        return self.cell_to_world(*self.world_to_cell(x, y))

    def offset_from_lattice(self, x: float, y: float) -> tuple[float, float]:
        """How far a position sits from its lattice point, in uu.

        Useful for spotting buildings that were placed freehand rather than on
        foundations - those will not line up with anything the planner draws.
        """
        sx, sy = self.snap(x, y)
        return (x - sx, y - sy)


def _phase(value: float, cell: float) -> float:
    """Where `value` falls within a lattice period, in [0, cell)."""
    return value - math.floor(value / cell) * cell


def infer_anchor(
    positions: Sequence[tuple[float, float]],
    cell_uu: float = DEFAULT_CELL_UU,
    bucket_uu: float = 10.0,
    source: str = "inferred",
) -> GridAnchor:
    """Recover the world grid's phase from placed foundations.

    Each foundation's position is reduced to its offset within one lattice
    period, then the most common offset wins. Freehand or rotated builds show
    up as scattered phases and are outvoted by the regular field around them,
    so a handful of odd placements will not drag the grid off true.

    `bucket_uu` sets how coarsely phases are grouped before voting; 10 uu
    (10 cm) tolerates float drift in the save without merging genuinely
    distinct offsets.
    """
    if not positions:
        return GridAnchor(cell_uu=cell_uu, source="default")

    votes: Counter[tuple[int, int]] = Counter()
    for x, y in positions:
        bx = int(_phase(x, cell_uu) // bucket_uu)
        by = int(_phase(y, cell_uu) // bucket_uu)
        votes[(bx, by)] += 1

    (bx, by), _ = votes.most_common(1)[0]

    # Average the true phases inside the winning bucket rather than using the
    # bucket's own edge, so the anchor keeps sub-bucket precision.
    xs, ys = [], []
    for x, y in positions:
        px, py = _phase(x, cell_uu), _phase(y, cell_uu)
        if int(px // bucket_uu) == bx and int(py // bucket_uu) == by:
            xs.append(px)
            ys.append(py)

    return GridAnchor(
        origin_x=sum(xs) / len(xs),
        origin_y=sum(ys) / len(ys),
        cell_uu=cell_uu,
        source=source,
    )


def cells_covering(
    positions: Iterable[tuple[float, float]], anchor: GridAnchor
) -> set[tuple[int, int]]:
    """The set of grid cells occupied by the given world positions."""
    return {anchor.world_to_cell(x, y) for x, y in positions}


def free_cells_near(
    occupied: set[tuple[int, int]],
    centre: tuple[int, int],
    count: int,
    max_radius: int = 40,
) -> list[tuple[int, int]]:
    """Pick `count` unoccupied cells, spiralling out from `centre`.

    This is how the planner proposes somewhere to put new machines: it keeps
    them close to the block they belong to and never suggests a cell that
    already has something in it. It knows nothing about terrain - see the
    README's limitations section.
    """
    found: list[tuple[int, int]] = []
    cx, cy = centre
    for radius in range(max_radius + 1):
        ring: list[tuple[int, int]] = []
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if max(abs(dx), abs(dy)) != radius:
                    continue
                ring.append((cx + dx, cy + dy))
        ring.sort(key=lambda c: ((c[0] - cx) ** 2 + (c[1] - cy) ** 2, c))
        for cell in ring:
            if cell not in occupied and cell not in found:
                found.append(cell)
                if len(found) == count:
                    return found
    return found
