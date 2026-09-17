"""Shared fixtures: a miniature but realistic game dataset and factory."""

from __future__ import annotations

import pytest

from satplanner.gamedata import Buildable, GameData, Ingredient, Item, Recipe
from satplanner.plan.model import Plan, PlanBlock, PlanMachine
from satplanner.savegame.model import FactoryState, Machine, Placement, Storage
from satplanner.worldgrid import GridAnchor


@pytest.fixture
def docs() -> GameData:
    data = GameData(source="test")
    for class_name, display, form in [
        ("Desc_OreIron_C", "Iron Ore", "RF_SOLID"),
        ("Desc_IronIngot_C", "Iron Ingot", "RF_SOLID"),
        ("Desc_IronPlate_C", "Iron Plate", "RF_SOLID"),
        ("Desc_IronRod_C", "Iron Rod", "RF_SOLID"),
        ("Desc_Water_C", "Water", "RF_LIQUID"),
    ]:
        data.items[class_name] = Item(class_name, display, form)

    data.buildables["Build_SmelterMk1_C"] = Buildable("Build_SmelterMk1_C", "Smelter", 4.0, True)
    data.buildables["Build_ConstructorMk1_C"] = Buildable(
        "Build_ConstructorMk1_C", "Constructor", 4.0, True
    )

    data.recipes["Recipe_IngotIron_C"] = Recipe(
        "Recipe_IngotIron_C", "Iron Ingot", 2.0,
        (Ingredient("Desc_OreIron_C", 1.0),),
        (Ingredient("Desc_IronIngot_C", 1.0),),
        ("Build_SmelterMk1_C",),
    )
    data.recipes["Recipe_IronPlate_C"] = Recipe(
        "Recipe_IronPlate_C", "Iron Plate", 6.0,
        (Ingredient("Desc_IronIngot_C", 3.0),),
        (Ingredient("Desc_IronPlate_C", 2.0),),
        ("Build_ConstructorMk1_C",),
    )
    data.recipes["Recipe_IronRod_C"] = Recipe(
        "Recipe_IronRod_C", "Iron Rod", 4.0,
        (Ingredient("Desc_IronIngot_C", 1.0),),
        (Ingredient("Desc_IronRod_C", 1.0),),
        ("Build_ConstructorMk1_C",),
    )
    # Construction costs are expressed as recipes producing the descriptor.
    data.recipes["Recipe_Build_SmelterMk1_C"] = Recipe(
        "Recipe_Build_SmelterMk1_C", "Smelter", 1.0,
        (Ingredient("Desc_IronRod_C", 5.0),),
        (Ingredient("Desc_SmelterMk1_C", 1.0),),
        (),
    )
    return data


@pytest.fixture
def plan() -> Plan:
    return Plan(
        name="Iron line",
        blocks=[
            PlanBlock(
                id="ingots", name="Iron smelting", anchor_cell=(0, 0),
                machines=[PlanMachine("Build_SmelterMk1_C", "Recipe_IngotIron_C", 6)],
            ),
            PlanBlock(
                id="plates", name="Iron plates", anchor_cell=(10, 0),
                machines=[PlanMachine("Build_ConstructorMk1_C", "Recipe_IronPlate_C", 4)],
            ),
        ],
    )


@pytest.fixture
def state() -> FactoryState:
    """Four smelters and one constructor standing, on an 800 uu grid."""
    anchor = GridAnchor(origin_x=0.0, origin_y=0.0, cell_uu=800.0, source="test")
    machines = [
        Machine(f"smelter{i}", "Build_SmelterMk1_C", Placement(i * 800.0, 0.0, 0.0), "Recipe_IngotIron_C")
        for i in range(4)
    ]
    machines.append(
        Machine("constructor0", "Build_ConstructorMk1_C", Placement(8000.0, 0.0, 0.0), "Recipe_IronPlate_C")
    )
    return FactoryState(
        save_name="TestSave",
        save_version=60,
        machines=machines,
        storages=[Storage("box0", "Build_StorageContainerMk1_C", Placement(0.0, 800.0, 0.0), {"Desc_IronRod_C": 12})],
        anchor=anchor,
    )
