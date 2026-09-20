"""The world map payload.

The map draws from one endpoint, so what matters here is that every layer it
needs is present and says the right thing: which nodes are free, which are
already mined, which the current plan would have to tap, and where the
factory actually sits in the world.

Node data is faked rather than taken from the parser's database, so these
tests say the same thing with or without vendor/ fetched.
"""

from __future__ import annotations

import pytest

from satplanner.analysis import resources
from satplanner.analysis.resources import ResourceNode
from satplanner.config import Settings
from satplanner.savegame.model import Miner, Placement
from satplanner.service import PlannerService

IRON_NEAR = ResourceNode("nodes.iron_near", "Desc_OreIron_C", "PURE", 1000.0, 0.0, 0.0)
IRON_FAR = ResourceNode("nodes.iron_far", "Desc_OreIron_C", "IMPURE", 400000.0, 0.0, 0.0)
IRON_TAKEN = ResourceNode("nodes.iron_taken", "Desc_OreIron_C", "NORMAL", 500.0, 200.0, 0.0)
COPPER = ResourceNode("nodes.copper", "Desc_OreCopper_C", "NORMAL", -9000.0, 7000.0, 0.0)
ALL_NODES = (IRON_NEAR, IRON_FAR, IRON_TAKEN, COPPER)


@pytest.fixture
def nodes(monkeypatch):
    monkeypatch.setattr(resources, "load_node_database", lambda: ALL_NODES)
    return ALL_NODES


@pytest.fixture
def service(docs, plan, state, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))  # keep the saved plan out of the real profile
    built = PlannerService(Settings(save_dir=None, docs_json=None, modeler_dir=None))
    built.docs = docs
    built.plan = plan
    built.state = state
    return built


def test_the_map_lists_every_known_node(service, nodes):
    payload = service.grid()
    assert payload["ok"]
    assert len(payload["nodes"]) == len(ALL_NODES)
    assert {n["resource_class"] for n in payload["nodes"]} == {"Desc_OreIron_C", "Desc_OreCopper_C"}
    assert all(n["status"] in {"free", "tapped", "wanted"} for n in payload["nodes"])


def test_a_node_under_one_of_your_miners_reads_as_taken(service, nodes):
    service.state.miners = [
        Miner("miner0", "Build_MinerMk2_C", Placement(600.0, 220.0, 0.0), node_instance=IRON_TAKEN.instance_name)
    ]
    by_id = {n["id"]: n for n in service.grid()["nodes"]}
    assert by_id["iron_taken"]["status"] == "tapped"
    assert by_id["copper"]["status"] != "tapped"


def test_the_map_marks_the_nodes_the_plan_still_needs(service, nodes):
    """The plan smelts iron it does not yet mine, so a free iron node is wanted."""
    statuses = {n["id"]: n["status"] for n in service.grid()["nodes"]}
    assert statuses["iron_near"] == "wanted"
    assert statuses["copper"] == "free", "the plan needs no copper"


def test_an_empty_plan_wants_nothing(service, nodes):
    service.plan.blocks = []
    assert all(n["status"] != "wanted" for n in service.grid()["nodes"])


def test_each_extractor_points_back_at_the_node_it_sits_on(service, nodes):
    service.state.miners = [
        Miner("miner0", "Build_MinerMk2_C", Placement(600.0, 220.0, 0.0), node_instance=IRON_TAKEN.instance_name),
        Miner("pump0", "Build_WaterPump_C", Placement(-2000.0, 0.0, 0.0), node_instance="nodes.not_in_the_database"),
    ]
    miners = service.grid()["miners"]
    assert len(miners) == 2
    on_node, orphan = miners
    assert on_node["node_x"] == IRON_TAKEN.x and on_node["node_y"] == IRON_TAKEN.y
    assert on_node["resource"] == "Iron Ore"
    assert on_node["building_class"] == "Build_MinerMk2_C"
    # A water extractor sits on no node in the database; the map must not guess one.
    assert orphan["node_x"] is None and orphan["node_y"] is None


def test_the_map_says_where_the_factory_sits(service, nodes):
    base = service.grid()["base"]
    assert base["min_x"] == 0.0 and base["max_x"] == 8000.0
    assert base["min_y"] == 0.0 and base["max_y"] == 0.0


def test_the_world_bounds_cover_every_node(service, nodes):
    world = service.grid()["world"]
    assert world["min_x"] <= min(n.x for n in ALL_NODES)
    assert world["max_x"] >= max(n.x for n in ALL_NODES)
    assert world["min_y"] <= min(n.y for n in ALL_NODES)
    assert world["max_y"] >= max(n.y for n in ALL_NODES)


def test_every_machine_carries_the_class_its_icon_is_drawn_from(service, nodes):
    built = service.grid()["built"]
    assert built
    assert all(m["building_class"].startswith("Build_") for m in built)


def test_the_map_still_draws_without_the_node_database(service, monkeypatch):
    """Without vendor/ there are no nodes, and the map must still open."""
    monkeypatch.setattr(resources, "load_node_database", lambda: ())
    payload = service.grid()
    assert payload["ok"]
    assert payload["nodes"] == []
    assert payload["world"]["max_x"] > payload["world"]["min_x"]
    assert payload["built"]
