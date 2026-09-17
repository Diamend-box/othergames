"""The planner's application layer.

Everything the UI can ask for lives here as plain Python returning plain
dictionaries, so the HTTP layer stays a thin shell and the interesting
behaviour can be tested without starting a server.
"""

from __future__ import annotations

import time
from pathlib import Path

from . import config
from .analysis import buildorder, diff as diff_mod, placement, production, resources
from .gamedata import GameData, load_docs
from .plan.model import Plan, PlanBlock, PlanMachine
from .plan import modeler
from .savegame import discovery
from .savegame.adapter import ParserUnavailable, load_state
from .savegame.model import FactoryState

PLAN_FILENAME = "plan.json"


class PlannerService:
    def __init__(self, settings: config.Settings | None = None):
        self.settings = settings or config.Settings()
        self.docs: GameData = GameData()
        self.state: FactoryState | None = None
        self.selected_save: Path | None = None
        self.plan: Plan = Plan()
        self.last_error: str | None = None
        self._load_docs()
        self._load_plan()

    # -- setup -------------------------------------------------------------

    def _load_docs(self) -> None:
        try:
            self.docs = load_docs(self.settings.docs_json)
        except (OSError, ValueError) as exc:
            self.docs = GameData()
            self.last_error = f"Could not read the game's docs file: {exc}"

    @property
    def plan_path(self) -> Path:
        return config.state_dir() / PLAN_FILENAME

    def _load_plan(self) -> None:
        if self.plan_path.is_file():
            try:
                self.plan = Plan.load(self.plan_path)
            except (OSError, ValueError, KeyError) as exc:
                self.last_error = f"Could not read the saved plan: {exc}"

    def save_plan(self) -> None:
        self.plan.save(self.plan_path)

    # -- saves -------------------------------------------------------------

    def saves(self) -> list[dict[str, object]]:
        found = discovery.list_saves(self.settings.save_dir)
        return [save.describe() for save in discovery.newest_session(found)]

    def current_save_path(self) -> Path | None:
        if self.selected_save is not None:
            return self.selected_save
        latest = discovery.latest_save(self.settings.save_dir)
        return latest.path if latest else None

    def select_save(self, path: str) -> dict[str, object]:
        candidate = Path(path)
        if not candidate.is_file():
            return {"ok": False, "error": f"No such save file: {path}"}
        self.selected_save = candidate
        return self.refresh(force=True)

    def refresh(self, force: bool = False) -> dict[str, object]:
        """Re-read the save file and rebuild the current factory state."""
        path = self.current_save_path()
        if path is None:
            return {
                "ok": False,
                "error": "No save file found. Set the save folder, or pass "
                "SATPLANNER_SAVE_DIR, and try again.",
            }
        if not force and self.state is not None and self.state.source_path == str(path):
            try:
                if path.stat().st_mtime <= self.state.parsed_at:
                    return {"ok": True, "cached": True, "state": self.state.summary()}
            except OSError:
                pass
        started = time.time()
        try:
            self.state = load_state(path, docs=self.docs)
        except ParserUnavailable as exc:
            self.last_error = str(exc)
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # a corrupt or unsupported save
            self.last_error = f"Could not read {path.name}: {exc}"
            return {"ok": False, "error": self.last_error}
        self.last_error = None
        return {
            "ok": True,
            "cached": False,
            "parse_seconds": round(time.time() - started, 1),
            "state": self.state.summary(),
        }

    # -- plan --------------------------------------------------------------

    def set_plan(self, payload: dict) -> dict[str, object]:
        try:
            self.plan = Plan.from_dict(payload)
        except (KeyError, TypeError, ValueError) as exc:
            return {"ok": False, "error": f"That plan did not make sense: {exc}"}
        self.save_plan()
        return {"ok": True, "plan": self.plan.to_dict()}

    def scan_modeler(self, directory: str | None = None) -> dict[str, object]:
        """Report what Satisfactory Modeler has on disk.

        Until its project format is known this is the useful thing the app can
        do: say precisely what the files are.
        """
        target = Path(directory) if directory else self.settings.modeler_dir
        if target is None:
            return {
                "ok": False,
                "error": "Satisfactory Modeler was not found. Pass its folder, "
                "or set SATPLANNER_MODELER_DIR.",
            }
        reports = modeler.sniff_directory(target)
        return {
            "ok": True,
            "directory": str(target),
            "files": [report.describe() for report in reports],
            "importable": [r.describe() for r in reports if r.kind in {"json", "sqlite"}],
        }

    def import_modeler(self, path: str) -> dict[str, object]:
        try:
            plan = modeler.import_plan(Path(path), docs=self.docs)
        except modeler.UnknownModelerFormat as exc:
            return {
                "ok": False,
                "error": str(exc),
                "report": exc.report.describe() if exc.report else None,
            }
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        self.plan = plan
        self.save_plan()
        return {"ok": True, "plan": self.plan.to_dict(), "warnings": plan.warnings}

    # -- the report --------------------------------------------------------

    def report(self) -> dict[str, object]:
        """Everything the main screen shows, in one payload."""
        if self.state is None:
            refreshed = self.refresh()
            if not refreshed.get("ok"):
                return {"ok": False, "error": refreshed.get("error")}
        state = self.state
        assert state is not None

        if not self.docs.is_loaded:
            return {
                "ok": False,
                "error": "The game's item and recipe data has not been loaded, so "
                "rates and costs cannot be worked out. Point the app at your "
                "Satisfactory install (CommunityResources/Docs) and refresh.",
                "state": state.summary(),
            }

        report = diff_mod.diff_plan(state, self.plan)
        throughput = production.plan_throughput(self.plan, self.docs)
        suggestions = placement.suggest_placements(state, self.plan, report)
        stages = buildorder.build_order(self.plan, self.docs)
        block_names = {block.id: block.name for block in self.plan.blocks}

        return {
            "ok": True,
            "state": state.summary(),
            "plan": {
                "name": self.plan.name,
                "source": self.plan.source,
                "blocks": len(self.plan.blocks),
                "machines": self.plan.total_machines,
            },
            "progress": {
                "machines_built": sum(row.have for row in report.rows),
                "machines_planned": sum(row.want for row in report.rows),
                "machines_missing": report.machines_missing,
                "complete": report.complete,
            },
            "rows": [row.describe(self.docs) for row in report.rows],
            "unplanned": [
                {
                    "building": self.docs.building_name(building),
                    "recipe": self.docs.recipes[recipe].display_name
                    if recipe in self.docs.recipes
                    else (recipe or "no recipe set"),
                    "count": count,
                }
                for (building, recipe), count in sorted(report.unplanned.items(), key=lambda kv: -kv[1])
            ],
            "shopping_list": diff_mod.construction_shopping_list(report, self.docs, state),
            "power_mw": round(production.plan_power_mw(self.plan, self.docs), 1),
            "outputs": [
                {"item": self.docs.item_name(item), "per_minute": round(rate, 1)}
                for item, rate in sorted(throughput.surplus().items(), key=lambda kv: -kv[1])
            ],
            "sourcing": resources.sourcing_report(throughput.deficit(), state, self.docs),
            "build_order": [
                {
                    "stage": stage.index + 1,
                    "blocks": [block_names.get(bid, bid) for bid in stage.blocks],
                    "reason": stage.reason,
                }
                for stage in stages
            ],
            "placements": [s.describe(self.docs) for s in suggestions],
        }

    def grid(self) -> dict[str, object]:
        """Everything the grid view draws, in world coordinates."""
        if self.state is None:
            return {"ok": False, "error": "No save loaded yet."}
        state = self.state
        anchor = state.anchor
        report = diff_mod.diff_plan(state, self.plan)
        suggestions = placement.suggest_placements(state, self.plan, report)
        return {
            "ok": True,
            "anchor": {
                "origin_x": anchor.origin_x,
                "origin_y": anchor.origin_y,
                "cell_uu": anchor.cell_uu,
                "source": anchor.source,
            },
            "built": [
                {
                    "x": machine.placement.x,
                    "y": machine.placement.y,
                    "cell": list(anchor.world_to_cell(machine.placement.x, machine.placement.y)),
                    "building": self.docs.building_name(machine.building_class),
                    "recipe": self.docs.recipes[machine.recipe_class].display_name
                    if machine.recipe_class in self.docs.recipes
                    else (machine.recipe_class or "no recipe"),
                    "clock": machine.clock,
                }
                for machine in state.machines
            ],
            "foundations": [
                {"x": f.placement.x, "y": f.placement.y} for f in state.foundations[:4000]
            ],
            "suggested": [s.describe(self.docs) for s in suggestions],
        }

    def status(self) -> dict[str, object]:
        return {
            "ok": True,
            "settings": self.settings.describe(),
            "docs_loaded": self.docs.is_loaded,
            "recipes": len(self.docs.recipes),
            "node_data": len(resources.load_node_database()),
            "selected_save": str(self.current_save_path()) if self.current_save_path() else None,
            "state": self.state.summary() if self.state else None,
            "plan": {"name": self.plan.name, "machines": self.plan.total_machines},
            "last_error": self.last_error,
        }


def demo_plan() -> Plan:
    """A small starter plan, used when the app has nothing else to show."""
    return Plan(
        name="Starter iron line",
        source="demo",
        blocks=[
            PlanBlock(
                id="ingots",
                name="Iron smelting",
                anchor_cell=(0, 0),
                machines=[PlanMachine("Build_SmelterMk1_C", "Recipe_IngotIron_C", 6)],
            ),
            PlanBlock(
                id="plates",
                name="Iron plates",
                anchor_cell=(6, 0),
                machines=[PlanMachine("Build_ConstructorMk1_C", "Recipe_IronPlate_C", 4)],
            ),
        ],
    )
