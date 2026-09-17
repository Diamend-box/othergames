from satplanner.analysis.production import (
    machine_power,
    machine_rate,
    machines_needed,
    plan_power_mw,
    plan_throughput,
)


def test_throughput_nets_production_against_consumption(plan, docs):
    """6 smelters feed 4 constructors: 180 ingots in, 120 eaten, 60 spare."""
    totals = plan_throughput(plan, docs)
    net = totals.net()
    assert net["Desc_IronIngot_C"] == 60.0
    assert net["Desc_IronPlate_C"] == 80.0
    assert net["Desc_OreIron_C"] == -180.0


def test_deficit_lists_only_the_raw_inputs(plan, docs):
    assert plan_throughput(plan, docs).deficit() == {"Desc_OreIron_C": 180.0}


def test_surplus_lists_only_what_is_left_over(plan, docs):
    surplus = plan_throughput(plan, docs).surplus()
    assert surplus == {"Desc_IronIngot_C": 60.0, "Desc_IronPlate_C": 80.0}


def test_overclocking_scales_output_linearly(docs):
    recipe = docs.recipes["Recipe_IngotIron_C"]
    assert machine_rate(recipe, "Desc_IronIngot_C", clock=2.5) == 75.0


def test_overclocking_scales_power_by_the_game_exponent(docs):
    """A 4 MW smelter at 250% draws about 13.4 MW in game."""
    smelter = docs.buildables["Build_SmelterMk1_C"]
    assert round(machine_power(smelter, clock=2.5), 1) == 13.4
    assert machine_power(smelter, clock=1.0) == 4.0


def test_somersloops_double_output_and_quadruple_power(docs):
    recipe = docs.recipes["Recipe_IngotIron_C"]
    smelter = docs.buildables["Build_SmelterMk1_C"]
    assert machine_rate(recipe, "Desc_IronIngot_C", sloops=1) == 60.0
    assert machine_power(smelter, sloops=1) == 16.0


def test_plan_power_sums_every_machine(plan, docs):
    assert plan_power_mw(plan, docs) == 40.0


def test_machines_needed_reports_fractions(docs):
    """9 machines' worth of demand should not quietly become 9."""
    recipe = docs.recipes["Recipe_IngotIron_C"]
    assert machines_needed(recipe, "Desc_IronIngot_C", 250.0) == 250.0 / 30.0


def test_a_recipe_with_no_duration_produces_nothing(docs):
    from satplanner.gamedata import Ingredient, Recipe

    broken = Recipe("Recipe_Broken_C", "Broken", 0.0, (), (Ingredient("Desc_IronIngot_C", 1.0),), ())
    assert machine_rate(broken, "Desc_IronIngot_C") == 0.0
