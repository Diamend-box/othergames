"""What to build first.

A plan is a dependency graph: a block that consumes iron plates wants the
block making iron plates standing first. Sorting that graph into stages turns
a wall of machines into an order of work, and anything left in a cycle (or fed
only by raw ore) is flagged rather than hidden.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..gamedata import GameData
from ..plan.model import Plan, PlanBlock


@dataclass
class BuildStage:
    index: int
    blocks: list[str] = field(default_factory=list)
    reason: str = ""


def _block_items(block: PlanBlock, docs: GameData) -> tuple[set[str], set[str]]:
    """(what this block makes, what it needs)."""
    produces: set[str] = set()
    consumes: set[str] = set()
    for machine in block.machines:
        recipe = docs.recipes.get(machine.recipe_class)
        if recipe is None:
            continue
        produces.update(p.item for p in recipe.products)
        consumes.update(i.item for i in recipe.ingredients)
    return produces, consumes


def build_order(plan: Plan, docs: GameData) -> list[BuildStage]:
    """Group the plan's blocks into stages that can be built in parallel.

    Stage 0 is everything that depends on nothing else in the plan - normally
    the smelting that sits on raw ore. Each later stage becomes buildable once
    the stages before it exist.
    """
    produces: dict[str, set[str]] = {}
    consumes: dict[str, set[str]] = {}
    for block in plan.blocks:
        made, needed = _block_items(block, docs)
        produces[block.id] = made
        consumes[block.id] = needed

    # A block depends on another if that other block makes something it eats.
    depends_on: dict[str, set[str]] = {}
    for block in plan.blocks:
        deps = set()
        for other in plan.blocks:
            if other.id == block.id:
                continue
            if consumes[block.id] & produces[other.id]:
                deps.add(other.id)
        depends_on[block.id] = deps

    stages: list[BuildStage] = []
    placed: set[str] = set()
    remaining = {block.id for block in plan.blocks}

    while remaining:
        ready = sorted(bid for bid in remaining if depends_on[bid] <= placed)
        if not ready:
            # Mutually dependent blocks - common and legitimate in Satisfactory
            # (think refinery loops), so they are reported, not dropped.
            stages.append(
                BuildStage(
                    index=len(stages),
                    blocks=sorted(remaining),
                    reason="Circular dependency - these feed each other and need building together",
                )
            )
            break
        stages.append(
            BuildStage(
                index=len(stages),
                blocks=ready,
                reason="Inputs come from raw resources" if not stages else "Inputs come from earlier stages",
            )
        )
        placed.update(ready)
        remaining -= set(ready)

    return stages
