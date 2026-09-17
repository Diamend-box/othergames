"""Item, recipe and building data read from the game's own documentation dump.

Satisfactory ships a JSON dump of every item, recipe and buildable under
`CommunityResources/Docs`. Reading it from the player's install keeps the
planner's numbers tied to the patch they are actually running, which matters
because recipe durations and power draws move between updates.

The dump stores structured fields as Unreal's own text encoding, e.g.

    ((ItemClass="...Desc_OreIron.Desc_OreIron_C",Amount=1))

so the small amount of regex here is unavoidable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# Fluids and gases are stored multiplied by 1000 in the docs (litres rather
# than the cubic metres the game's UI shows), so they are scaled on the way in.
FLUID_FORMS = {"RF_LIQUID", "RF_GAS"}
FLUID_SCALE = 1000.0

_ITEM_AMOUNT_RE = re.compile(
    r"ItemClass\s*=\s*[^,]*?([A-Za-z0-9_]+)\.\1_C[^,]*,\s*Amount\s*=\s*(-?\d+)"
)
_CLASS_REF_RE = re.compile(r"([A-Za-z0-9_]+)\.\1_C")
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class Item:
    class_name: str
    display_name: str
    form: str = "RF_SOLID"

    @property
    def is_fluid(self) -> bool:
        return self.form in FLUID_FORMS


@dataclass(frozen=True)
class Ingredient:
    item: str
    amount: float


@dataclass(frozen=True)
class Recipe:
    class_name: str
    display_name: str
    duration_s: float
    ingredients: tuple[Ingredient, ...]
    products: tuple[Ingredient, ...]
    produced_in: tuple[str, ...]

    @property
    def is_alternate(self) -> bool:
        return self.class_name.startswith("Recipe_Alternate")

    def rate_per_minute(self, item: str) -> float:
        """Units of `item` produced per minute by one machine at 100%."""
        if self.duration_s <= 0:
            return 0.0
        for product in self.products:
            if product.item == item:
                return product.amount * 60.0 / self.duration_s
        return 0.0

    def input_rate_per_minute(self, item: str) -> float:
        if self.duration_s <= 0:
            return 0.0
        for ingredient in self.ingredients:
            if ingredient.item == item:
                return ingredient.amount * 60.0 / self.duration_s
        return 0.0

    @property
    def primary_product(self) -> str | None:
        return self.products[0].item if self.products else None


@dataclass(frozen=True)
class Buildable:
    class_name: str
    display_name: str
    power_mw: float = 0.0
    is_manufacturer: bool = False
    build_cost: tuple[Ingredient, ...] = ()


@dataclass
class GameData:
    items: dict[str, Item] = field(default_factory=dict)
    recipes: dict[str, Recipe] = field(default_factory=dict)
    buildables: dict[str, Buildable] = field(default_factory=dict)
    source: str | None = None

    # -- lookups -----------------------------------------------------------

    def item_name(self, class_name: str) -> str:
        item = self.items.get(class_name)
        return item.display_name if item else _readable(class_name)

    def building_name(self, class_name: str) -> str:
        building = self.buildables.get(class_name)
        return building.display_name if building else _readable(class_name)

    def recipes_producing(self, item: str) -> list[Recipe]:
        return [r for r in self.recipes.values() if any(p.item == item for p in r.products)]

    def recipes_for_building(self, building: str) -> list[Recipe]:
        return [r for r in self.recipes.values() if building in r.produced_in]

    def build_cost_of(self, building: str) -> tuple[Ingredient, ...]:
        """What it costs to place one of these, from its build recipe.

        The docs express construction costs as recipes whose product is the
        building's descriptor, so the cost is looked up rather than stored.
        """
        buildable = self.buildables.get(building)
        if buildable and buildable.build_cost:
            return buildable.build_cost
        descriptor = building.replace("Build_", "Desc_", 1)
        for recipe in self.recipes.values():
            if any(p.item in (descriptor, building) for p in recipe.products):
                return recipe.ingredients
        return ()

    @property
    def is_loaded(self) -> bool:
        return bool(self.recipes)


def _readable(class_name: str) -> str:
    """Fallback display name for a class we have no docs entry for."""
    name = class_name
    for prefix in ("Build_", "Desc_", "Recipe_", "BP_"):
        if name.startswith(prefix):
            name = name[len(prefix) :]
    if name.endswith("_C"):
        name = name[:-2]
    return re.sub(r"(?<!^)(?=[A-Z])", " ", name).replace("_", " ").strip()


def _parse_amounts(raw: str | None, items: dict[str, Item]) -> tuple[Ingredient, ...]:
    if not raw:
        return ()
    out: list[Ingredient] = []
    for match in _ITEM_AMOUNT_RE.finditer(raw):
        class_name = f"{match.group(1)}_C"
        amount = float(match.group(2))
        item = items.get(class_name)
        if item and item.is_fluid:
            amount /= FLUID_SCALE
        out.append(Ingredient(item=class_name, amount=amount))
    return tuple(out)


def _parse_class_refs(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(f"{m.group(1)}_C" for m in _CLASS_REF_RE.finditer(raw))


def _parse_float(raw: object, default: float = 0.0) -> float:
    if raw is None:
        return default
    if isinstance(raw, (int, float)):
        return float(raw)
    match = _NUM_RE.search(str(raw))
    return float(match.group(0)) if match else default


def read_docs_text(path: Path) -> str:
    """Read the docs dump, which has shipped in several encodings over time."""
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-8"):
        try:
            text = raw.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
        if text.lstrip().startswith(("[", "{")):
            return text
    raise ValueError(f"Could not decode {path} as JSON in any known encoding")


def parse_docs(payload: list[dict], source: str | None = None) -> GameData:
    """Turn the raw docs structure into the planner's data model."""
    data = GameData(source=source)

    # Items first: recipe amounts need each item's form to scale fluids.
    for group in payload:
        native = str(group.get("NativeClass", ""))
        if "Descriptor" not in native and "FGItem" not in native:
            continue
        for entry in group.get("Classes", []):
            class_name = entry.get("ClassName")
            if not class_name:
                continue
            data.items[class_name] = Item(
                class_name=class_name,
                display_name=entry.get("mDisplayName") or _readable(class_name),
                form=entry.get("mForm") or "RF_SOLID",
            )

    for group in payload:
        native = str(group.get("NativeClass", ""))
        if "FGBuildable" not in native:
            continue
        is_manufacturer = "Manufacturer" in native
        for entry in group.get("Classes", []):
            class_name = entry.get("ClassName")
            if not class_name:
                continue
            data.buildables[class_name] = Buildable(
                class_name=class_name,
                display_name=entry.get("mDisplayName") or _readable(class_name),
                power_mw=_parse_float(entry.get("mPowerConsumption")),
                is_manufacturer=is_manufacturer,
            )

    for group in payload:
        if "FGRecipe" not in str(group.get("NativeClass", "")):
            continue
        for entry in group.get("Classes", []):
            class_name = entry.get("ClassName")
            if not class_name:
                continue
            data.recipes[class_name] = Recipe(
                class_name=class_name,
                display_name=entry.get("mDisplayName") or _readable(class_name),
                # The game spells this "mManufactoringDuration"; both are accepted
                # in case the typo is ever fixed upstream.
                duration_s=_parse_float(
                    entry.get("mManufactoringDuration", entry.get("mManufactureDuration"))
                ),
                ingredients=_parse_amounts(entry.get("mIngredients"), data.items),
                products=_parse_amounts(entry.get("mProduct"), data.items),
                produced_in=_parse_class_refs(entry.get("mProducedIn")),
            )

    return data


def load_docs(path: Path | None) -> GameData:
    """Load game data, or return an empty set if the docs cannot be found."""
    if path is None:
        return GameData()
    payload = json.loads(read_docs_text(Path(path)))
    return parse_docs(payload, source=str(path))
