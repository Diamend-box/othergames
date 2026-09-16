"""Throughput, power and material maths for a plan.

All rates are per minute, matching the units the game itself shows.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..gamedata import GameData
from ..plan.model import Plan, PlanMachine

# Power scales with clock speed raised to this exponent - it is log2(2.5), the
# constant the game uses, so a machine at 250% draws 2.5x its rated power's
# worth of exponent rather than 2.5x the power itself.
POWER_CLOCK_EXPONENT = 1.321928


def machine_rate(recipe, item: str, clock: float = 1.0, sloops: int = 0) -> float:
    """Units per minute of `item` from one machine at the given settings."""
    base = recipe.rate_per_minute(item)
    return base * clock * (1 + sloops)


def machine_input_rate(recipe, item: str, clock: float = 1.0) -> float:
    """Units per minute of `item` consumed by one machine.

    Somersloops amplify output without changing input, so they do not appear
    here.
    """
    return recipe.input_rate_per_minute(item) * clock


def machine_power(building, clock: float = 1.0, sloops: int = 0) -> float:
    """Power draw in MW for one machine at the given settings."""
    base = getattr(building, "power_mw", 0.0)
    power = base * (clock**POWER_CLOCK_EXPONENT)
    if sloops:
        # Amplification costs power quadratically in the boost multiplier.
        power *= (1 + sloops) ** 2
    return power


@dataclass
class Throughput:
    """Net item flow for a plan, in units per minute."""

    produced: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    consumed: dict[str, float] = field(default_factory=lambda: defaultdict(float))

    def net(self) -> dict[str, float]:
        items = set(self.produced) | set(self.consumed)
        return {item: self.produced.get(item, 0.0) - self.consumed.get(item, 0.0) for item in items}

    def surplus(self) -> dict[str, float]:
        return {item: rate for item, rate in self.net().items() if rate > 1e-6}

    def deficit(self) -> dict[str, float]:
        """Items the plan consumes more of than it makes - the raw inputs."""
        return {item: -rate for item, rate in self.net().items() if rate < -1e-6}


def machine_throughput(machine: PlanMachine, docs: GameData, into: Throughput) -> None:
    recipe = docs.recipes.get(machine.recipe_class)
    if recipe is None:
        return
    for product in recipe.products:
        into.produced[product.item] += machine.count * machine_rate(
            recipe, product.item, machine.clock
        )
    for ingredient in recipe.ingredients:
        into.consumed[ingredient.item] += machine.count * machine_input_rate(
            recipe, ingredient.item, machine.clock
        )


def plan_throughput(plan: Plan, docs: GameData) -> Throughput:
    """Everything the finished plan would produce and consume, per minute."""
    totals = Throughput()
    for block in plan.blocks:
        for machine in block.machines:
            machine_throughput(machine, docs, totals)
    return totals


def plan_power_mw(plan: Plan, docs: GameData) -> float:
    total = 0.0
    for block in plan.blocks:
        for machine in block.machines:
            building = docs.buildables.get(machine.building_class)
            if building is not None:
                total += machine.count * machine_power(building, machine.clock)
    return total


def machines_needed(recipe, item: str, target_per_minute: float, clock: float = 1.0) -> float:
    """Fractional machine count to hit a target rate - round up to build it."""
    per_machine = machine_rate(recipe, item, clock)
    if per_machine <= 0:
        return 0.0
    return target_per_minute / per_machine
