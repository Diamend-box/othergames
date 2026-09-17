"""Checks against real game data: a 1.2.4.0 save, the game's own recipe dump,
and a Modeler export whose solved numbers were read off Modeler's screen.

The save test needs the upstream parser in vendor/ (scripts/fetch_parser.py)
and is skipped without it.
"""

import json
from pathlib import Path

import pytest

from satplanner.gamedata import load_docs
from satplanner.plan.sfmd import parse_sfmd, solve
from satplanner.savegame.adapter import ParserUnavailable, load_state

FIXTURES = Path(__file__).parent / "fixtures"
SAVE = FIXTURES / "Shatisfactory_1.2.4.0.sav"
DOCS = FIXTURES / "en-US.json"
SFMD = FIXTURES / "test.sfmd"


@pytest.fixture(scope="module")
def real_docs():
    return load_docs(DOCS)


@pytest.fixture(scope="module")
def real_state(real_docs):
    try:
        return load_state(SAVE, docs=real_docs)
    except ParserUnavailable:
        pytest.skip("save parser not fetched into vendor/")


def test_the_docs_dump_decodes_and_rates_are_right(real_docs):
    assert real_docs.recipes["Recipe_IngotIron_C"].rate_per_minute("Desc_IronIngot_C") == 30.0
    assert real_docs.recipes["Recipe_Screw_C"].rate_per_minute("Desc_IronScrew_C") == 40.0
    assert real_docs.buildables["Build_SmelterMk1_C"].power_mw == 4.0
    cost = {i.item: i.amount for i in real_docs.build_cost_of("Build_SmelterMk1_C")}
    assert cost == {"Desc_IronRod_C": 5.0, "Desc_Wire_C": 8.0}


def test_a_real_1_2_4_0_save_reads_completely(real_state):
    assert real_state.save_version == 60
    assert not any("format version" in w for w in real_state.warnings)
    assert len(real_state.machines) == 109
    assert len(real_state.miners) == 48
    assert len(real_state.storages) == 58
    assert real_state.machine_counts()[("Build_ConstructorMk1_C", "Recipe_IronRod_C")] == 22
    assert real_state.machine_counts()[("Build_SmelterMk1_C", "Recipe_IngotIron_C")] == 20
    assert all(m.node_instance for m in real_state.miners)
    assert round(real_state.play_time_seconds / 3600, 1) == 42.7
    assert real_state.player_inventory["Desc_SteelPlate_C"] == 1379
    assert {1.5, 1.0} <= {round(m.clock, 2) for m in real_state.machines}


# Every node's rate and machine count as Modeler displayed them for test.sfmd.
MODELER_DISPLAY = {
    "Iron Ore": (659.26, None), "Coal": (270.0, None), "Copper Ore": (26.5, None),
    "Iron Ingot": (389.26, 12.98), "Iron Plate": (115.95, 5.8), "Iron Rod": (215.34, 14.36),
    "Screw": (507.97, 12.7), "Reinforced Iron Plate": (19.32, 3.87), "Rotor": (11.04, 2.76),
    "Smart Plating": (11.04, 5.52), "Modular Frame": (5.52, 2.76), "Steel Ingot": (270.0, 6.0),
    "Steel Beam": (66.26, 4.42), "Steel Pipe": (3.31, 0.17), "Versatile Framework": (11.04, 2.21),
    "Copper Ingot": (26.5, 0.88), "Wire": (53.0, 1.77), "Stator": (1.1, 0.22), "Cable": (22.09, 0.74),
    "Automated Wiring": (1.1, 0.44), "Space Elevator Phase 2": (0.011, 0.01),
}


def test_the_solver_reproduces_modelers_own_numbers(real_docs):
    """Coal is the binding cap in this plan; everything else scales from it."""
    solved, warnings = solve(parse_sfmd(json.loads(SFMD.read_text())), real_docs)
    assert warnings == []
    assert len(solved) == len(MODELER_DISPLAY)
    for entry in solved:
        rate, machines = MODELER_DISPLAY[entry.node.name]
        assert entry.rate_per_minute == pytest.approx(rate, abs=0.06), entry.node.name
        if machines is not None:
            assert entry.machines == pytest.approx(machines, abs=0.011), entry.node.name
