from satplanner.analysis.diff import construction_shopping_list, diff_plan
from satplanner.plan.model import Plan, PlanBlock, PlanMachine
from satplanner.savegame.model import FactoryState, Machine, Placement


def rows_by_block(report):
    return {(row.block_id, row.building_class): row for row in report.rows}


def test_counts_what_is_built_against_what_was_planned(state, plan):
    report = diff_plan(state, plan)
    rows = rows_by_block(report)
    assert rows[("ingots", "Build_SmelterMk1_C")].have == 4
    assert rows[("ingots", "Build_SmelterMk1_C")].missing == 2
    assert rows[("plates", "Build_ConstructorMk1_C")].have == 1
    assert rows[("plates", "Build_ConstructorMk1_C")].missing == 3
    assert report.machines_missing == 5
    assert not report.complete


def test_machines_are_assigned_to_the_block_they_stand_in(docs):
    """Two blocks running the same recipe must not share the same machines."""
    plan = Plan(
        blocks=[
            PlanBlock(id="north", name="North", anchor_cell=(0, 0),
                      machines=[PlanMachine("Build_SmelterMk1_C", "Recipe_IngotIron_C", 2)]),
            PlanBlock(id="south", name="South", anchor_cell=(0, 50),
                      machines=[PlanMachine("Build_SmelterMk1_C", "Recipe_IngotIron_C", 2)]),
        ]
    )
    state = FactoryState(
        machines=[
            Machine("n1", "Build_SmelterMk1_C", Placement(0.0, 0.0, 0.0), "Recipe_IngotIron_C"),
            Machine("n2", "Build_SmelterMk1_C", Placement(800.0, 0.0, 0.0), "Recipe_IngotIron_C"),
            Machine("s1", "Build_SmelterMk1_C", Placement(0.0, 40000.0, 0.0), "Recipe_IngotIron_C"),
        ]
    )
    rows = rows_by_block(diff_plan(state, plan))
    assert rows[("north", "Build_SmelterMk1_C")].have == 2
    assert rows[("south", "Build_SmelterMk1_C")].have == 1


def test_machines_are_never_counted_twice(docs):
    """Without anchors the pool is shared, but each machine is claimed once."""
    plan = Plan(
        blocks=[
            PlanBlock(id="a", name="A", machines=[PlanMachine("Build_SmelterMk1_C", "Recipe_IngotIron_C", 2)]),
            PlanBlock(id="b", name="B", machines=[PlanMachine("Build_SmelterMk1_C", "Recipe_IngotIron_C", 2)]),
        ]
    )
    state = FactoryState(
        machines=[
            Machine(f"s{i}", "Build_SmelterMk1_C", Placement(i * 800.0, 0.0, 0.0), "Recipe_IngotIron_C")
            for i in range(3)
        ]
    )
    report = diff_plan(state, plan)
    assert sum(row.have for row in report.rows) == 3
    assert report.machines_missing == 1


def test_machines_outside_the_plan_are_reported_not_hidden(state, plan):
    extra = Machine("rods", "Build_ConstructorMk1_C", Placement(9000.0, 0.0, 0.0), "Recipe_IronRod_C")
    state.machines.append(extra)
    report = diff_plan(state, plan)
    assert report.unplanned[("Build_ConstructorMk1_C", "Recipe_IronRod_C")] == 1


def test_machines_with_no_recipe_set_are_flagged(state, plan):
    state.machines.append(Machine("idle", "Build_ConstructorMk1_C", Placement(0.0, 5000.0, 0.0), None))
    report = diff_plan(state, plan)
    assert "Build_ConstructorMk1_C" in report.unassigned_recipes


def test_shopping_list_nets_off_what_is_already_in_storage(state, plan, docs):
    """Two smelters cost 10 rods; there are 12 in a container, so nothing is short."""
    report = diff_plan(state, plan)
    items = {row["item_class"]: row for row in construction_shopping_list(report, docs, state)}
    assert items["Desc_IronRod_C"]["needed"] == 10.0
    assert items["Desc_IronRod_C"]["in_storage"] == 12
    assert items["Desc_IronRod_C"]["short_by"] == 0.0


def test_shopping_list_reports_a_genuine_shortfall(state, plan, docs):
    state.storages[0].stacks["Desc_IronRod_C"] = 3
    report = diff_plan(state, plan)
    items = {row["item_class"]: row for row in construction_shopping_list(report, docs, state)}
    assert items["Desc_IronRod_C"]["short_by"] == 7.0


def test_a_finished_plan_reports_complete(plan, docs):
    machines = [
        Machine(f"s{i}", "Build_SmelterMk1_C", Placement(i * 800.0, 0.0, 0.0), "Recipe_IngotIron_C")
        for i in range(6)
    ] + [
        Machine(f"c{i}", "Build_ConstructorMk1_C", Placement(8000.0 + i * 800.0, 0.0, 0.0), "Recipe_IronPlate_C")
        for i in range(4)
    ]
    report = diff_plan(FactoryState(machines=machines), plan)
    assert report.complete
    assert report.machines_missing == 0
