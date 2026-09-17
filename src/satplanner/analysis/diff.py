"""Comparing the factory that exists against the factory that was planned."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..gamedata import GameData
from ..plan.model import Plan
from ..savegame.model import FactoryState, Machine


@dataclass
class DiffRow:
    building_class: str
    recipe_class: str
    block_id: str
    have: int
    want: int

    @property
    def missing(self) -> int:
        return max(0, self.want - self.have)

    @property
    def surplus(self) -> int:
        return max(0, self.have - self.want)

    def describe(self, docs: GameData) -> dict[str, object]:
        return {
            "block_id": self.block_id,
            "building": docs.building_name(self.building_class),
            "building_class": self.building_class,
            "recipe": docs.recipes[self.recipe_class].display_name
            if self.recipe_class in docs.recipes
            else self.recipe_class,
            "recipe_class": self.recipe_class,
            "have": self.have,
            "want": self.want,
            "missing": self.missing,
            "surplus": self.surplus,
        }


@dataclass
class DiffReport:
    rows: list[DiffRow] = field(default_factory=list)
    unplanned: dict[tuple[str, str | None], int] = field(default_factory=dict)
    unassigned_recipes: list[str] = field(default_factory=list)

    @property
    def machines_missing(self) -> int:
        return sum(row.missing for row in self.rows)

    @property
    def complete(self) -> bool:
        return self.machines_missing == 0


def _assign_to_blocks(state: FactoryState, plan: Plan) -> dict[str, list[Machine]]:
    """Decide which existing machine counts towards which planned block.

    When blocks carry a grid anchor, machines go to the nearest one - which is
    what a player means by "that block over there". Without anchors there is
    nothing to cluster on, so every machine lands in a shared pool and the
    comparison is done on totals instead.
    """
    anchored = [block for block in plan.blocks if block.anchor_cell is not None]
    assignment: dict[str, list[Machine]] = {block.id: [] for block in plan.blocks}

    if not anchored:
        assignment.setdefault("", [])
        assignment[""] = list(state.machines)
        return assignment

    anchor = state.anchor
    centres = {
        block.id: anchor.cell_to_world(*block.anchor_cell)
        for block in anchored
        if block.anchor_cell is not None
    }
    for machine in state.machines:
        best_id = min(
            centres,
            key=lambda bid: (machine.placement.x - centres[bid][0]) ** 2
            + (machine.placement.y - centres[bid][1]) ** 2,
        )
        assignment[best_id].append(machine)
    return assignment


def diff_plan(state: FactoryState, plan: Plan) -> DiffReport:
    """Row per (block, building, recipe): how many stand, how many were wanted."""
    report = DiffReport()
    assignment = _assign_to_blocks(state, plan)
    pooled = "" in assignment

    claimed: set[str] = set()
    for block in plan.blocks:
        available = assignment.get("" if pooled else block.id, [])
        have_counts: dict[tuple[str, str | None], int] = defaultdict(int)
        for machine in available:
            if machine.instance_name in claimed:
                continue
            have_counts[machine.key] += 1

        for (building_class, recipe_class), want in block.machine_counts().items():
            have = have_counts.get((building_class, recipe_class), 0)
            used = min(have, want)
            # Claim the machines this block is counting so a second block with
            # the same recipe cannot count them a second time.
            taken = 0
            for machine in available:
                if taken >= used:
                    break
                if machine.instance_name in claimed:
                    continue
                if machine.key == (building_class, recipe_class):
                    claimed.add(machine.instance_name)
                    taken += 1
            report.rows.append(
                DiffRow(
                    building_class=building_class,
                    recipe_class=recipe_class,
                    block_id=block.id,
                    have=used,
                    want=want,
                )
            )

    leftover: dict[tuple[str, str | None], int] = defaultdict(int)
    for machine in state.machines:
        if machine.instance_name not in claimed:
            leftover[machine.key] += 1
    report.unplanned = dict(leftover)
    report.unassigned_recipes = sorted(
        {m.building_class for m in state.machines if m.recipe_class is None}
    )
    return report


def construction_shopping_list(
    report: DiffReport, docs: GameData, state: FactoryState | None = None
) -> list[dict[str, object]]:
    """Parts needed to build everything that is missing, netted off stock."""
    needed: dict[str, float] = defaultdict(float)
    for row in report.rows:
        if row.missing <= 0:
            continue
        for ingredient in docs.build_cost_of(row.building_class):
            needed[ingredient.item] += ingredient.amount * row.missing

    stock = state.total_items() if state is not None else {}
    out: list[dict[str, object]] = []
    for item, amount in sorted(needed.items(), key=lambda kv: -kv[1]):
        have = stock.get(item, 0)
        out.append(
            {
                "item": docs.item_name(item),
                "item_class": item,
                "needed": round(amount, 2),
                "in_storage": have,
                "short_by": round(max(0.0, amount - have), 2),
            }
        )
    return out
