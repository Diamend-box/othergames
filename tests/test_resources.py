import pytest

from satplanner.analysis import resources
from satplanner.analysis.resources import MINER_RATES, ResourceNode, recommend_nodes, sourcing_report
from satplanner.savegame.model import FactoryState, Machine, Miner, Placement


@pytest.fixture
def fake_nodes(monkeypatch):
    nodes = (
        ResourceNode("node_close_impure", "Desc_OreIron_C", "IMPURE", 1000.0, 0.0, 0.0),
        ResourceNode("node_close_pure", "Desc_OreIron_C", "PURE", 2000.0, 0.0, 0.0),
        ResourceNode("node_far_pure", "Desc_OreIron_C", "PURE", 900000.0, 0.0, 0.0),
        ResourceNode("node_taken", "Desc_OreIron_C", "PURE", 500.0, 0.0, 0.0),
        ResourceNode("node_copper", "Desc_OreCopper_C", "NORMAL", 1000.0, 0.0, 0.0),
    )
    monkeypatch.setattr(resources, "load_node_database", lambda: nodes)
    return nodes


@pytest.fixture
def base_state():
    return FactoryState(
        machines=[Machine("m", "Build_SmelterMk1_C", Placement(0.0, 0.0, 0.0), "Recipe_IngotIron_C")],
        miners=[Miner("miner", "Build_MinerMk2_C", Placement(500.0, 0.0, 0.0), node_instance="node_taken")],
    )


def test_miner_rates_match_the_game():
    assert MINER_RATES["Build_MinerMk1_C"]["NORMAL"] == 60.0
    assert MINER_RATES["Build_MinerMk3_C"]["PURE"] == 480.0


def test_a_node_already_being_mined_is_never_recommended(fake_nodes, base_state):
    picks = recommend_nodes("Desc_OreIron_C", 100.0, base_state)
    assert "node_taken" not in [p.node.instance_name for p in picks]


def test_enough_nodes_are_picked_to_cover_the_target(fake_nodes, base_state):
    picks = recommend_nodes("Desc_OreIron_C", 300.0, base_state)
    assert sum(p.rate_per_minute for p in picks) >= 300.0


def test_close_and_rich_nodes_come_first(fake_nodes, base_state):
    picks = recommend_nodes("Desc_OreIron_C", 60.0, base_state)
    assert picks[0].node.instance_name == "node_close_pure"


def test_distance_is_reported_in_metres(fake_nodes, base_state):
    """World units are centimetres; the report must not say 2000 m."""
    picks = recommend_nodes("Desc_OreIron_C", 60.0, base_state)
    assert picks[0].distance_m == pytest.approx(20.0)


def test_water_extractors_ignore_purity(fake_nodes):
    node = ResourceNode("w", "Desc_Water_C", "IMPURE", 0.0, 0.0, 0.0)
    assert node.rate("Build_WaterPump_C") == 120.0


def test_sourcing_report_covers_each_raw_input(fake_nodes, base_state, docs):
    report = sourcing_report({"Desc_OreIron_C": 200.0}, base_state, docs)
    assert report[0]["resource_class"] == "Desc_OreIron_C"
    assert report[0]["needed_per_minute"] == 200.0
    assert report[0]["covered_per_minute"] >= 200.0


def test_a_missing_node_database_is_reported_not_hidden(monkeypatch, base_state, docs):
    monkeypatch.setattr(resources, "load_node_database", lambda: ())
    report = sourcing_report({"Desc_OreIron_C": 60.0}, base_state, docs)
    assert report[0]["nodes"] == []
    assert "fetch_parser" in report[0]["note"]
