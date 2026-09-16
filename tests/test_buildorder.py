from satplanner.analysis.buildorder import build_order
from satplanner.gamedata import Ingredient, Recipe
from satplanner.plan.model import Plan, PlanBlock, PlanMachine


def test_feeders_are_scheduled_before_the_blocks_they_feed(plan, docs):
    stages = build_order(plan, docs)
    assert stages[0].blocks == ["ingots"]
    assert stages[1].blocks == ["plates"]


def test_independent_blocks_share_a_stage(docs):
    plan = Plan(
        blocks=[
            PlanBlock(id="ingots", name="Ingots", machines=[PlanMachine("Build_SmelterMk1_C", "Recipe_IngotIron_C", 2)]),
            PlanBlock(id="rods", name="Rods", machines=[PlanMachine("Build_ConstructorMk1_C", "Recipe_IronRod_C", 2)]),
            PlanBlock(id="plates", name="Plates", machines=[PlanMachine("Build_ConstructorMk1_C", "Recipe_IronPlate_C", 2)]),
        ]
    )
    stages = build_order(plan, docs)
    assert stages[0].blocks == ["ingots"]
    assert stages[1].blocks == ["plates", "rods"]


def test_circular_dependencies_are_reported_rather_than_dropped(docs):
    """Refinery loops are legitimate; the planner must not silently lose them."""
    docs.recipes["Recipe_AtoB_C"] = Recipe(
        "Recipe_AtoB_C", "A to B", 1.0,
        (Ingredient("Desc_IronPlate_C", 1.0),), (Ingredient("Desc_IronRod_C", 1.0),), (),
    )
    docs.recipes["Recipe_BtoA_C"] = Recipe(
        "Recipe_BtoA_C", "B to A", 1.0,
        (Ingredient("Desc_IronRod_C", 1.0),), (Ingredient("Desc_IronPlate_C", 1.0),), (),
    )
    plan = Plan(
        blocks=[
            PlanBlock(id="a", name="A", machines=[PlanMachine("Build_ConstructorMk1_C", "Recipe_AtoB_C", 1)]),
            PlanBlock(id="b", name="B", machines=[PlanMachine("Build_ConstructorMk1_C", "Recipe_BtoA_C", 1)]),
        ]
    )
    stages = build_order(plan, docs)
    assert sorted(stages[-1].blocks) == ["a", "b"]
    assert "Circular" in stages[-1].reason


def test_an_empty_plan_produces_no_stages(docs):
    assert build_order(Plan(), docs) == []
