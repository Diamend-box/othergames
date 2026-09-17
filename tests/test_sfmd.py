"""Satisfactory Modeler `.sfmd` import: the graph read is settled, the solver's
semantics are provisional (see `sfmd.solve`) and tested for internal
consistency only."""

import json
from pathlib import Path

import pytest

from satplanner.plan.modeler import import_plan
from satplanner.plan.sfmd import import_sfmd, parse_sfmd, solve

FIXTURE = Path(__file__).parent / "fixtures" / "test.sfmd"


def chain(ore_max=90.0):
    return {
        "Version": "1.0", "Solver": "Full",
        "Data": [
            {"Name": "Iron Ore", "X": 0, "Y": 0, "Max": str(ore_max)},
            {"Name": "Iron Ingot", "X": 1, "Y": 0, "Inputs": {"Iron Ore": [0]}},
            {"Name": "Iron Plate", "X": 2, "Y": 0, "Inputs": {"Iron Ingot": [[1, [[5, 5]]]]}},
        ],
    }


def test_the_real_export_parses_completely():
    graph = parse_sfmd(json.loads(FIXTURE.read_text()))
    assert len(graph.nodes) == 21
    assert {(n.name, n.max_rate) for n in graph.raws} == {("Iron Ore", 780.0), ("Copper Ore", 60.0), ("Coal", 270.0)}
    assert [n.name for n in graph.sinks] == ["Space Elevator Phase 2"]


def test_edges_are_read_in_both_plain_and_routed_forms():
    graph = parse_sfmd(chain())
    assert graph.nodes[1].inputs == {"Iron Ore": 0}
    assert graph.nodes[2].inputs == {"Iron Ingot": 1}  # routed edge with path points


def test_rates_scale_to_the_tightest_raw_cap(docs):
    """90 ore/min feeds 90 ingots, which make 60 plates: 3 smelters, 3 constructors."""
    solved, warnings = solve(parse_sfmd(chain(90.0)), docs)
    by_name = {s.node.name: s for s in solved}
    assert by_name["Iron Plate"].rate_per_minute == pytest.approx(60.0)
    assert by_name["Iron Ingot"].rate_per_minute == pytest.approx(90.0)
    assert by_name["Iron Ingot"].machines == pytest.approx(3.0)
    assert by_name["Iron Plate"].machines == pytest.approx(3.0)
    assert warnings == []


def test_a_cap_on_an_intermediate_node_limits_the_whole_graph(docs):
    payload = chain(9999.0)
    payload["Data"][2]["Max"] = "20"
    solved, _ = solve(parse_sfmd(payload), docs)
    assert {s.node.name: round(s.rate_per_minute, 3) for s in solved}["Iron Ingot"] == 30.0


def test_unknown_nodes_are_reported_rather_than_invented(docs):
    payload = chain()
    payload["Data"].append({"Name": "Space Elevator Phase 2", "X": 3, "Y": 0, "Max": "1", "Inputs": {"Iron Plate": [2]}})
    _, warnings = solve(parse_sfmd(payload), docs)
    assert any("Space Elevator Phase 2" in w for w in warnings)


def test_import_rounds_machines_up_to_whole_buildings(docs):
    plan, _ = import_sfmd(chain(100.0), name="t", source="test", docs=docs)
    counts = plan.machine_counts()
    # 100 ore -> 100 ingots (3.33 smelters -> 4), 66.7 plates (3.33 constructors -> 4)
    assert counts[("Build_SmelterMk1_C", "Recipe_IngotIron_C")] == 4
    assert counts[("Build_ConstructorMk1_C", "Recipe_IronPlate_C")] == 4


def test_import_without_game_data_keeps_the_shape_and_warns():
    plan, warnings = import_sfmd(chain(), name="t", source="test", docs=None)
    assert [b.name for b in plan.blocks] == ["Iron Ingot", "Iron Plate"]
    assert any("recipe data" in w for w in warnings)


def test_import_plan_routes_sfmd_files_to_the_graph_importer(docs, tmp_path):
    path = tmp_path / "line.sfmd"
    path.write_text(json.dumps(chain(90.0)))
    plan = import_plan(path, docs=docs)
    assert plan.source == "modeler:line.sfmd"
    assert plan.total_machines == 6
