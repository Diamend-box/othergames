"""Working out where the raw materials for a plan come from.

The node database ships with the upstream save parser (`sav_data.resourcePurity`,
extracted for v1.2.0.0): every ore node, oil well and water source in the world
with its type, purity and coordinates. The save then says which of those
already have a miner on them, so a recommendation only ever points at nodes
that are genuinely free.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from functools import lru_cache

from .. import config
from ..gamedata import GameData
from ..savegame.model import FactoryState

# Extraction rates per minute at 100% clock, by purity.
# Fluid extractors are rated in cubic metres per minute.
MINER_RATES = {
    "Build_MinerMk1_C": {"IMPURE": 30.0, "NORMAL": 60.0, "PURE": 120.0},
    "Build_MinerMk2_C": {"IMPURE": 60.0, "NORMAL": 120.0, "PURE": 240.0},
    "Build_MinerMk3_C": {"IMPURE": 120.0, "NORMAL": 240.0, "PURE": 480.0},
    "Build_OilPump_C": {"IMPURE": 60.0, "NORMAL": 120.0, "PURE": 240.0},
    # The water extractor ignores purity - every water source is the same.
    "Build_WaterPump_C": {"IMPURE": 120.0, "NORMAL": 120.0, "PURE": 120.0},
    # Resource wells vary with the number of satellites on the pressuriser, so
    # this is the per-satellite rate rather than a whole-well figure.
    "Build_FrackingExtractor_C": {"IMPURE": 30.0, "NORMAL": 60.0, "PURE": 120.0},
}

# Which extractor to assume for a given resource when the caller has no view.
DEFAULT_EXTRACTOR = {
    "Desc_Water_C": "Build_WaterPump_C",
    "Desc_LiquidOil_C": "Build_OilPump_C",
    "Desc_NitrogenGas_C": "Build_FrackingExtractor_C",
}
DEFAULT_ORE_EXTRACTOR = "Build_MinerMk2_C"


@dataclass(frozen=True)
class ResourceNode:
    instance_name: str
    resource_class: str
    purity: str
    x: float
    y: float
    z: float

    def rate(self, miner_class: str, clock: float = 1.0) -> float:
        table = MINER_RATES.get(miner_class)
        if table is None:
            return 0.0
        return table.get(self.purity.upper(), 0.0) * clock


@lru_cache(maxsize=1)
def load_node_database() -> tuple[ResourceNode, ...]:
    """Every node in the world, or an empty tuple if the parser is missing."""
    vendor = config.vendor_dir()
    for candidate in (vendor / "sat_sav_parse", vendor):
        if (candidate / "sav_data").is_dir():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            break
    try:
        from sav_data.resourcePurity import RESOURCE_PURITY  # type: ignore
    except ImportError:
        return ()

    nodes: list[ResourceNode] = []
    for instance_name, entry in RESOURCE_PURITY.items():
        try:
            resource_class, purity, position, _core = entry
            purity_name = getattr(purity, "name", str(purity))
            nodes.append(
                ResourceNode(
                    instance_name=instance_name,
                    resource_class=str(resource_class),
                    purity=str(purity_name),
                    x=float(position[0]),
                    y=float(position[1]),
                    z=float(position[2]),
                )
            )
        except (TypeError, ValueError, IndexError):
            continue
    return tuple(nodes)


def nodes_for_resource(resource_class: str) -> list[ResourceNode]:
    return [n for n in load_node_database() if n.resource_class == resource_class]


@dataclass
class NodeRecommendation:
    node: ResourceNode
    miner_class: str
    rate_per_minute: float
    distance_m: float
    already_mined: bool

    def describe(self, docs: GameData) -> dict[str, object]:
        return {
            "node": self.node.instance_name.rsplit(".", 1)[-1],
            "resource": docs.item_name(self.node.resource_class),
            "resource_class": self.node.resource_class,
            "purity": self.node.purity.capitalize(),
            "world_x": round(self.node.x, 1),
            "world_y": round(self.node.y, 1),
            "distance_m": round(self.distance_m),
            "extractor": docs.building_name(self.miner_class),
            "rate_per_minute": round(self.rate_per_minute, 1),
            "already_mined": self.already_mined,
        }


def recommend_nodes(
    resource_class: str,
    target_per_minute: float,
    state: FactoryState,
    reference: tuple[float, float] | None = None,
    miner_class: str | None = None,
    clock: float = 1.0,
) -> list[NodeRecommendation]:
    """Nearest free nodes that together cover the target rate.

    Nodes already carrying a miner are skipped rather than double-counted -
    the plan needs new extraction, not a second miner on the same patch.
    """
    miner = miner_class or DEFAULT_EXTRACTOR.get(resource_class, DEFAULT_ORE_EXTRACTOR)
    occupied = state.occupied_nodes()
    origin = reference or _centre_of_base(state)

    candidates = []
    for node in nodes_for_resource(resource_class):
        rate = node.rate(miner, clock)
        if rate <= 0:
            continue
        distance = math.dist((node.x, node.y), origin) / 100.0  # uu -> metres
        candidates.append((distance, node, rate))

    # Prefer close nodes, and among similar distances the richer ones.
    candidates.sort(key=lambda c: (c[0] / max(c[2], 1.0), c[0]))

    picked: list[NodeRecommendation] = []
    covered = 0.0
    for distance, node, rate in candidates:
        if node.instance_name in occupied:
            continue
        picked.append(
            NodeRecommendation(
                node=node,
                miner_class=miner,
                rate_per_minute=rate,
                distance_m=distance,
                already_mined=False,
            )
        )
        covered += rate
        if covered >= target_per_minute:
            break
    return picked


def _centre_of_base(state: FactoryState) -> tuple[float, float]:
    points = [m.placement.xy for m in state.machines] or [
        f.placement.xy for f in state.foundations
    ]
    if not points:
        return (0.0, 0.0)
    return (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
    )


def sourcing_report(
    deficits: dict[str, float], state: FactoryState, docs: GameData
) -> list[dict[str, object]]:
    """For every raw input the plan needs, where to get it."""
    out: list[dict[str, object]] = []
    for resource_class, rate in sorted(deficits.items(), key=lambda kv: -kv[1]):
        recommendations = recommend_nodes(resource_class, rate, state)
        out.append(
            {
                "resource": docs.item_name(resource_class),
                "resource_class": resource_class,
                "needed_per_minute": round(rate, 1),
                "covered_per_minute": round(sum(r.rate_per_minute for r in recommendations), 1),
                "nodes": [r.describe(docs) for r in recommendations],
                "note": "No node data - run scripts/fetch_parser.py"
                if not load_node_database()
                else "",
            }
        )
    return out
