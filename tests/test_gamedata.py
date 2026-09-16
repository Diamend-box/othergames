import json

import pytest

from satplanner.gamedata import parse_docs, read_docs_text

IRON_INGREDIENTS = (
    '((ItemClass="/Script/Engine.BlueprintGeneratedClass\'/Game/FactoryGame/Resource/'
    'RawResources/OreIron/Desc_OreIron.Desc_OreIron_C\'",Amount=1))'
)
IRON_PRODUCT = (
    '((ItemClass="/Script/Engine.BlueprintGeneratedClass\'/Game/FactoryGame/Resource/'
    'Parts/IronIngot/Desc_IronIngot.Desc_IronIngot_C\'",Amount=1))'
)
PLATE_INGREDIENTS = (
    '((ItemClass="/Game/FactoryGame/Resource/Parts/IronIngot/Desc_IronIngot.Desc_IronIngot_C",Amount=3),'
    '(ItemClass="/Game/FactoryGame/Resource/RawResources/Water/Desc_Water.Desc_Water_C",Amount=2000))'
)


@pytest.fixture
def raw_docs():
    return [
        {
            "NativeClass": "/Script/CoreUObject.Class'/Script/FactoryGame.FGResourceDescriptor'",
            "Classes": [
                {"ClassName": "Desc_OreIron_C", "mDisplayName": "Iron Ore", "mForm": "RF_SOLID"},
                {"ClassName": "Desc_Water_C", "mDisplayName": "Water", "mForm": "RF_LIQUID"},
            ],
        },
        {
            "NativeClass": "/Script/CoreUObject.Class'/Script/FactoryGame.FGItemDescriptor'",
            "Classes": [
                {"ClassName": "Desc_IronIngot_C", "mDisplayName": "Iron Ingot", "mForm": "RF_SOLID"},
                {"ClassName": "Desc_IronPlate_C", "mDisplayName": "Iron Plate", "mForm": "RF_SOLID"},
            ],
        },
        {
            "NativeClass": "/Script/CoreUObject.Class'/Script/FactoryGame.FGBuildableManufacturer'",
            "Classes": [
                {
                    "ClassName": "Build_SmelterMk1_C",
                    "mDisplayName": "Smelter",
                    "mPowerConsumption": "4.000000",
                }
            ],
        },
        {
            "NativeClass": "/Script/CoreUObject.Class'/Script/FactoryGame.FGRecipe'",
            "Classes": [
                {
                    "ClassName": "Recipe_IngotIron_C",
                    "mDisplayName": "Iron Ingot",
                    "mManufactureDuration": "2.000000",
                    "mIngredients": IRON_INGREDIENTS,
                    "mProduct": IRON_PRODUCT,
                    "mProducedIn": '("/Game/FactoryGame/Buildable/Factory/SmelterMk1/Build_SmelterMk1.Build_SmelterMk1_C")',
                },
                {
                    "ClassName": "Recipe_Alternate_CoatedPlate_C",
                    "mDisplayName": "Alternate: Coated Iron Plate",
                    "mManufactureDuration": "8.000000",
                    "mIngredients": PLATE_INGREDIENTS,
                    "mProduct": IRON_PRODUCT,
                    "mProducedIn": '("/Game/FactoryGame/Buildable/Factory/AssemblerMk1/Build_AssemblerMk1.Build_AssemblerMk1_C")',
                },
            ],
        },
    ]


def test_recipe_rates_match_the_game(raw_docs):
    """A smelter makes 30 iron ingots a minute; that is the whole test."""
    data = parse_docs(raw_docs)
    recipe = data.recipes["Recipe_IngotIron_C"]
    assert recipe.rate_per_minute("Desc_IronIngot_C") == 30.0
    assert recipe.input_rate_per_minute("Desc_OreIron_C") == 30.0
    assert recipe.produced_in == ("Build_SmelterMk1_C",)


def test_fluid_amounts_are_scaled_to_cubic_metres(raw_docs):
    """Docs store fluids multiplied by 1000; 2000 there means 2 m3 here."""
    data = parse_docs(raw_docs)
    recipe = data.recipes["Recipe_Alternate_CoatedPlate_C"]
    amounts = {i.item: i.amount for i in recipe.ingredients}
    assert amounts["Desc_Water_C"] == 2.0
    assert amounts["Desc_IronIngot_C"] == 3.0


def test_alternate_recipes_are_identified(raw_docs):
    data = parse_docs(raw_docs)
    assert data.recipes["Recipe_Alternate_CoatedPlate_C"].is_alternate
    assert not data.recipes["Recipe_IngotIron_C"].is_alternate


def test_buildings_carry_their_power_draw(raw_docs):
    data = parse_docs(raw_docs)
    smelter = data.buildables["Build_SmelterMk1_C"]
    assert smelter.power_mw == 4.0
    assert smelter.is_manufacturer


def test_unknown_classes_get_a_readable_fallback_name(raw_docs):
    data = parse_docs(raw_docs)
    assert data.item_name("Desc_SomethingNew_C") == "Something New"


def test_utf16_docs_are_decoded(tmp_path, raw_docs):
    """The docs dump has shipped as UTF-16 in the past."""
    path = tmp_path / "Docs.json"
    path.write_bytes(json.dumps(raw_docs).encode("utf-16"))
    assert json.loads(read_docs_text(path))[0]["NativeClass"].endswith("FGResourceDescriptor'")
