"""Importing Satisfactory Modeler project files (`.sfmd`).

An `.sfmd` is JSON describing a *graph*, not a machine list. Each entry in
`Data` is an item node - "Iron Plate", "Rotor" - whose `Inputs` name the nodes
feeding it. Raw resources have no inputs and carry a per-minute `Max`. Modeler
solves the whole thing itself (`"Solver": "Full"`) and stores none of the
resulting rates or machine counts, so importing means re-solving.

Two halves live here:

* `parse_sfmd` reads the graph. This is settled - it is a plain read of the
  file format as observed.
* `solve` turns the graph into rates and machine counts. Its semantics are
  INFERRED and flagged as such until confirmed against what Modeler displays
  for a known plan. Assumptions are listed on the function.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..gamedata import GameData, Ingredient, Recipe
from .model import Plan, PlanBlock, PlanMachine

# Modeler nodes that are not game recipes. The game's docs do not list the
# Project Assembly phases, so Modeler carries its own table and so must we.
# Each is modelled as Modeler does: the full delivery as one craft taking a
# minute, so the node's "machine count" is phases per minute.
#
# Phase 2 is confirmed against Modeler's own display (10:10:1 at 0.01
# machines). The others are the game's published requirements and have not
# been checked against Modeler.
PSEUDO_RECIPES: dict[str, dict[str, float]] = {
    "Space Elevator Phase 1": {"Smart Plating": 50},
    "Space Elevator Phase 2": {"Smart Plating": 1000, "Versatile Framework": 1000, "Automated Wiring": 100},
    "Space Elevator Phase 3": {"Versatile Framework": 2500, "Modular Engine": 500, "Adaptive Control Unit": 100},
    "Space Elevator Phase 4": {
        "Assembly Director System": 4000, "Magnetic Field Generator": 4000,
        "Nuclear Pasta": 1000, "Thermal Propulsion Rocket": 1000,
    },
    "Space Elevator Phase 5": {"Biochemical Sculptor": 1000, "Ballistic Warp Drive": 1000, "AI Expansion Server": 40},
}


@dataclass
class SfmdNode:
    index: int
    name: str
    x: float
    y: float
    inputs: dict[str, int] = field(default_factory=dict)  # ingredient name -> source node index
    max_rate: float | None = None
    auto_round: bool = False

    @property
    def is_raw(self) -> bool:
        return not self.inputs


@dataclass
class SfmdGraph:
    nodes: list[SfmdNode]
    solver: str = "Full"
    version: str = ""

    def consumers_of(self, index: int) -> list[SfmdNode]:
        return [n for n in self.nodes if index in n.inputs.values()]

    @property
    def sinks(self) -> list[SfmdNode]:
        return [n for n in self.nodes if not self.consumers_of(n.index) and not n.is_raw]

    @property
    def raws(self) -> list[SfmdNode]:
        return [n for n in self.nodes if n.is_raw]


def _source_index(value: Any) -> int | None:
    """`[1]` or `[[2, [[x, y], ...]]]` - the source index is the first scalar."""
    while isinstance(value, list) and value:
        value = value[0]
    return int(value) if isinstance(value, (int, float)) else None


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def looks_like_sfmd(payload: Any) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get("Data"), list) and "Solver" in payload


def parse_sfmd(payload: dict) -> SfmdGraph:
    nodes: list[SfmdNode] = []
    for index, raw in enumerate(payload.get("Data", [])):
        inputs: dict[str, int] = {}
        for ingredient, value in (raw.get("Inputs") or {}).items():
            source = _source_index(value)
            if source is not None:
                inputs[str(ingredient)] = source
        nodes.append(
            SfmdNode(
                index=index,
                name=str(raw.get("Name", f"node{index}")),
                x=_float(raw.get("X")) or 0.0,
                y=_float(raw.get("Y")) or 0.0,
                inputs=inputs,
                max_rate=_float(raw.get("Max")),
                auto_round=bool(raw.get("AutoRound", False)),
            )
        )
    return SfmdGraph(nodes=nodes, solver=str(payload.get("Solver", "Full")), version=str(payload.get("Version", "")))


# -- solving ---------------------------------------------------------------


def _norm(name: str) -> str:
    """Modeler and the game disagree on plurals ("Screw" vs "Screws")."""
    key = name.strip().lower()
    return key[:-1] if key.endswith("s") and len(key) > 3 else key


def _item_by_name(name: str, docs: GameData) -> str | None:
    wanted = _norm(name)
    for item in docs.items.values():
        if _norm(item.display_name) == wanted:
            return item.class_name
    return None


def _pseudo_recipe(name: str, docs: GameData) -> Recipe | None:
    table = PSEUDO_RECIPES.get(name)
    if table is None:
        return None
    ingredients = []
    for item_name, amount in table.items():
        item_class = _item_by_name(item_name, docs)
        if item_class is None:
            return None
        ingredients.append(Ingredient(item_class, float(amount)))
    product = f"Pseudo_{name.replace(' ', '')}_C"
    return Recipe(
        class_name=product, display_name=name, duration_s=60.0,
        ingredients=tuple(ingredients), products=(Ingredient(product, 1.0),), produced_in=(),
    )


def _recipe_for(name: str, docs: GameData) -> Recipe | None:
    """The default recipe for an item, matched by display name.

    Modeler labels nodes with item names, and an alternate recipe would need
    to be spelled out in the node name; a plain name means the standard one.
    Some nodes are Modeler's own (see PSEUDO_RECIPES).
    """
    pseudo = _pseudo_recipe(name, docs)
    if pseudo is not None:
        return pseudo
    wanted = _norm(name)
    exact = [r for r in docs.recipes.values() if _norm(r.display_name) == wanted and not r.is_alternate]
    if exact:
        return exact[0]
    by_product = [
        r for r in docs.recipes.values()
        if not r.is_alternate and r.primary_product and _norm(docs.item_name(r.primary_product)) == wanted
    ]
    return by_product[0] if by_product else None


@dataclass
class SolvedNode:
    node: SfmdNode
    recipe: Recipe | None
    rate_per_minute: float = 0.0
    machines: float = 0.0


def solve(graph: SfmdGraph, docs: GameData) -> tuple[list[SolvedNode], list[str]]:
    """Rates and machine counts for every node.

    ASSUMED semantics, pending confirmation against Modeler's own display:

    1. A node's rate is demand-driven: what its consumers pull, per minute.
    2. The whole graph scales with one factor, chosen as large as the raw
       resource caps allow ("Full" solver = maximise output).
    3. A `Max` on a non-raw node caps that node's rate.
    4. Nodes with no recipe in the docs (Modeler pseudo-nodes such as space
       elevator phases) cannot contribute demand, and are reported.
    """
    warnings: list[str] = []
    solved = {n.index: SolvedNode(node=n, recipe=None if n.is_raw else _recipe_for(n.name, docs)) for n in graph.nodes}

    for entry in solved.values():
        if not entry.node.is_raw and entry.recipe is None:
            warnings.append(f"No recipe found for '{entry.node.name}' - its inputs will not be counted.")

    # Demand per unit of "one of everything the sinks make", walked from the
    # sinks back to the raws. Sinks without a recipe get no unit demand.
    unit_demand: dict[int, float] = {n.index: 0.0 for n in graph.nodes}
    for sink in graph.sinks:
        unit_demand[sink.index] = 1.0

    order = _topological_from_sinks(graph)
    for index in order:
        entry = solved[index]
        recipe = entry.recipe
        if recipe is None or unit_demand[index] <= 0:
            continue
        product_per_craft = next((p.amount for p in recipe.products if p.item == recipe.primary_product), 0.0)
        if product_per_craft <= 0:
            continue
        inputs_by_key = {_norm(k): v for k, v in entry.node.inputs.items()}
        for ingredient in recipe.ingredients:
            source = inputs_by_key.get(_norm(docs.item_name(ingredient.item)))
            if source is None:
                continue
            unit_demand[source] += unit_demand[index] * ingredient.amount / product_per_craft

    # Scale so the tightest raw cap is just met, then honour any node caps.
    scale = math.inf
    for raw in graph.raws:
        if raw.max_rate and unit_demand[raw.index] > 0:
            scale = min(scale, raw.max_rate / unit_demand[raw.index])
    for node in graph.nodes:
        if not node.is_raw and node.max_rate and unit_demand[node.index] > 0:
            scale = min(scale, node.max_rate / unit_demand[node.index])
    if scale is math.inf:
        scale = 1.0
        warnings.append("No raw resource caps in the plan; rates are per unit of output.")

    for index, entry in solved.items():
        entry.rate_per_minute = unit_demand[index] * scale
        if entry.recipe is not None:
            per_machine = entry.recipe.rate_per_minute(entry.recipe.primary_product or "")
            entry.machines = entry.rate_per_minute / per_machine if per_machine > 0 else 0.0

    return [solved[n.index] for n in graph.nodes], warnings


def _topological_from_sinks(graph: SfmdGraph) -> list[int]:
    """Node indices ordered so every consumer precedes what feeds it."""
    consumers: dict[int, set[int]] = {n.index: set() for n in graph.nodes}
    for node in graph.nodes:
        for source in node.inputs.values():
            if source in consumers:
                consumers[source].add(node.index)
    remaining = dict(consumers)
    order: list[int] = []
    while remaining:
        ready = sorted(i for i, cs in remaining.items() if not (cs & remaining.keys()))
        if not ready:  # a loop; emit the rest in index order rather than hang
            order.extend(sorted(remaining))
            break
        order.extend(ready)
        for i in ready:
            del remaining[i]
    return order


def import_sfmd(payload: dict, name: str, source: str, docs: GameData | None = None) -> tuple[Plan, list[str]]:
    """An `.sfmd` graph as a plan: one block per solved node.

    Without game data the topology still imports, with one machine per node
    and a warning - enough to see the shape, not enough to build from.
    """
    graph = parse_sfmd(payload)
    blocks: list[PlanBlock] = []
    warnings: list[str] = []

    if docs is None or not docs.is_loaded:
        warnings.append("Game recipe data not loaded - imported the plan's shape with 1 machine per step.")
        for node in graph.nodes:
            if node.is_raw:
                continue
            blocks.append(PlanBlock(id=f"n{node.index}", name=node.name,
                                    machines=[PlanMachine("Build_Unknown_C", node.name, 1)],
                                    notes="rate not solved"))
        return Plan(name=name, blocks=blocks, source=source), warnings

    solved, solve_warnings = solve(graph, docs)
    warnings.extend(solve_warnings)
    for entry in solved:
        if entry.node.is_raw or entry.recipe is None or not entry.recipe.produced_in:
            continue  # raws, unknowns and Modeler-only nodes are not buildings
        count = max(1, math.ceil(entry.machines - 1e-9)) if entry.machines > 0 else 0
        if count == 0:
            continue
        building = entry.recipe.produced_in[0] if entry.recipe.produced_in else "Build_Unknown_C"
        blocks.append(
            PlanBlock(
                id=f"n{entry.node.index}",
                name=entry.node.name,
                machines=[PlanMachine(building, entry.recipe.class_name, count)],
                notes=f"{entry.rate_per_minute:.1f}/min ({entry.machines:.2f} machines)",
            )
        )
    return Plan(name=name, blocks=blocks, source=source), warnings
