"""Tests for the save-file adapter, driven by stand-in parser objects.

The real parser needs a 30 MB save file, so the extraction logic is exercised
against objects shaped the way `sat_sav_parse` produces them. This proves the
walk, the header/object join and the property handling; it cannot prove the
property *names* are right for a given game build - that needs a real save.
"""

from __future__ import annotations

from types import SimpleNamespace

from satplanner.savegame.adapter import build_state


class StubParse:
    """Stands in for the `sav_parse` module."""

    @staticmethod
    def getPropertyValue(properties, name, caseInsensitiveFlag=False):  # noqa: N802
        for key, value in properties:
            if key == name:
                return value
        return None


def header(type_path, instance_name, position=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0, 1.0)):
    return SimpleNamespace(
        typePath=type_path, instanceName=instance_name, position=list(position), rotation=list(rotation)
    )


def obj(instance_name, **properties):
    return SimpleNamespace(instanceName=instance_name, properties=list(properties.items()))


def ref(path_name):
    return SimpleNamespace(pathName=path_name)


SMELTER = "/Game/FactoryGame/Buildable/Factory/SmelterMk1/Build_SmelterMk1.Build_SmelterMk1_C"
FOUNDATION = "/Game/FactoryGame/Buildable/Factory/Foundation/Build_Foundation_8x4_01.Build_Foundation_8x4_01_C"
MINER = "/Game/FactoryGame/Buildable/Factory/MinerMK2/Build_MinerMk2.Build_MinerMk2_C"
CONTAINER = "/Game/FactoryGame/Buildable/Factory/StorageContainerMk1/Build_StorageContainerMk1.Build_StorageContainerMk1_C"


def make_save(headers, objects, save_version=60):
    level = SimpleNamespace(actorAndComponentObjectHeaders=headers, objects=objects)
    info = SimpleNamespace(saveName="TestSave", saveVersion=save_version, buildVersion=123456)
    return SimpleNamespace(saveFileInfo=info, levels=[level])


def test_machines_are_read_with_their_recipe_and_clock():
    save = make_save(
        [header(SMELTER, "smelter1", position=(1250.0, 3250.0, 100.0))],
        [obj("smelter1",
             mCurrentRecipe=ref("/Game/FactoryGame/Recipes/Recipe_IngotIron.Recipe_IngotIron_C"),
             mCurrentPotential=2.5)],
    )
    state = build_state(StubParse, save)
    assert len(state.machines) == 1
    machine = state.machines[0]
    assert machine.building_class == "Build_SmelterMk1_C"
    assert machine.recipe_class == "Recipe_IngotIron_C"
    assert machine.clock == 2.5
    assert machine.placement.x == 1250.0


def test_a_machine_with_no_recipe_set_still_appears():
    save = make_save([header(SMELTER, "idle")], [obj("idle")])
    state = build_state(StubParse, save)
    assert state.machines[0].recipe_class is None
    assert state.machines[0].clock == 1.0


def test_the_grid_is_recovered_from_the_foundations_in_the_save():
    headers = [
        header(FOUNDATION, f"f{i}", position=(450.0 + 800 * i, 50.0, 0.0)) for i in range(6)
    ]
    state = build_state(StubParse, make_save(headers, []))
    assert state.anchor.origin_x == 450.0
    assert state.anchor.source == "foundations"
    assert len(state.foundations) == 6


def test_a_save_with_no_foundations_warns_rather_than_guessing():
    state = build_state(StubParse, make_save([header(SMELTER, "s1")], [obj("s1")]))
    assert any("No foundations" in w for w in state.warnings)


def test_miners_record_the_node_they_sit_on():
    save = make_save(
        [header(MINER, "miner1")],
        [obj("miner1", mExtractResourceNode=ref("Persistent_Level:PersistentLevel.BP_ResourceNode42"))],
    )
    state = build_state(StubParse, save)
    assert state.miners[0].node_instance.endswith("BP_ResourceNode42")
    assert state.occupied_nodes() == {"Persistent_Level:PersistentLevel.BP_ResourceNode42"}


def test_storage_contents_are_read_through_the_inventory_component():
    """Containers hold a reference to a component; the stacks live there."""
    stacks = [
        [[("Item", ("/Game/.../Desc_IronPlate.Desc_IronPlate_C", None)), ("NumItems", 87)]],
        [[("Item", ("/Game/.../Desc_IronRod.Desc_IronRod_C", None)), ("NumItems", 13)]],
        [[("Item", ("", None)), ("NumItems", 0)]],
    ]
    save = make_save(
        [header(CONTAINER, "box1")],
        [
            obj("box1", mStorageInventory=ref("box1.inventory")),
            obj("box1.inventory", mInventoryStacks=stacks),
        ],
    )
    state = build_state(StubParse, save)
    assert state.storages[0].stacks == {"Desc_IronPlate_C": 87, "Desc_IronRod_C": 13}
    assert state.total_items()["Desc_IronPlate_C"] == 87


def test_an_unrecognised_save_version_is_flagged():
    save = make_save([], [], save_version=99)
    assert any("99" in w for w in build_state(StubParse, save).warnings)


def test_a_known_1_2_save_version_passes_without_complaint():
    save = make_save([], [], save_version=60)
    assert not any("format version" in w for w in build_state(StubParse, save).warnings)


def test_one_broken_actor_does_not_lose_the_rest_of_the_report():
    class Exploding:
        instanceName = "bad"

        @property
        def properties(self):
            raise RuntimeError("corrupt property block")

    save = make_save(
        [header(SMELTER, "bad"), header(SMELTER, "good")],
        [Exploding(), obj("good", mCurrentRecipe=ref("/x/Recipe_IngotIron.Recipe_IngotIron_C"))],
    )
    state = build_state(StubParse, save)
    assert [m.instance_name for m in state.machines] == ["bad", "good"]
    assert state.machines[1].recipe_class == "Recipe_IngotIron_C"


def test_headers_and_objects_are_joined_by_name_not_by_position():
    """Ordering differences between the two lists must not swap recipes."""
    save = make_save(
        [header(SMELTER, "a"), header(SMELTER, "b")],
        [
            obj("b", mCurrentRecipe=ref("/x/Recipe_IronPlate.Recipe_IronPlate_C")),
            obj("a", mCurrentRecipe=ref("/x/Recipe_IngotIron.Recipe_IngotIron_C")),
        ],
    )
    state = build_state(StubParse, save)
    by_name = {m.instance_name: m.recipe_class for m in state.machines}
    assert by_name == {"a": "Recipe_IngotIron_C", "b": "Recipe_IronPlate_C"}
