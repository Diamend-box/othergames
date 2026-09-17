# Satisfactory Build Planner

Reads your Satisfactory save file, compares the factory you have actually built
against a plan, and tells you what is still missing, where to put it, and where
to get the raw materials.

Runs as a single Windows `.exe`. Double-click it and the interface opens in your
browser; it re-reads your save every minute, or on demand.

> **Status: save reading verified against a real 1.2.4.0 save.** Machines,
> recipes, overclocks, extractors and their nodes, container and player
> inventories all read correctly. The Modeler importer reads the `.sfmd`
> graph but its rate solver is provisional - see [What still needs
> checking](#what-still-needs-checking). The project currently lives inside
> the `ghost-sim` repository and is meant to move to its own repo; nothing in
> it depends on where it sits.

---

## What it does

- **Reads your save** - every machine you have placed, the recipe it is set to,
  its overclock, what is in your containers, which resource nodes already have
  a miner on them, and every foundation.
- **Syncs its grid to the world grid.** Satisfactory measures the world in
  centimetres and snaps buildings to an 8 m foundation lattice. The app recovers
  that lattice's exact phase by taking a vote across all your placed
  foundations, so a cell in the app is the same cell in the game and every
  coordinate it suggests is one you can fly to.
- **Diffs against your plan** - per block, per building, per recipe: how many
  stand, how many were wanted, how many are missing.
- **Tells you what to build next** - the plan's blocks sorted into stages, so
  feeders get built before the things they feed.
- **Costs the remaining work** - construction materials for everything missing,
  netted off what is already in your containers.
- **Sources the raw materials** - for every ore, oil or water the plan consumes
  but does not make, the nearest free nodes with their purity, the extractor to
  put on them, and the yield you will get.

## Running it

**From the executable:** download `SatisfactoryPlanner.exe` from the GitHub
Actions build artifact, run it, and the UI opens at
`http://127.0.0.1:8711/`. Close the console window to stop it.

**From source:**

```bash
python scripts/fetch_parser.py     # downloads the save parser (see Licensing)
python -m pip install -e .
python -m satplanner
```

Useful flags: `--save-dir`, `--docs`, `--modeler-dir`, `--port`, `--poll`,
`--no-browser`. Every path can also be set by environment variable
(`SATPLANNER_SAVE_DIR`, `SATPLANNER_DOCS`, `SATPLANNER_MODELER_DIR`), which is
how the app is developed on a machine with no game installed.

## What it finds by itself

| Thing | Where it looks |
| --- | --- |
| Save files | `%LOCALAPPDATA%\FactoryGame\Saved\SaveGames\**\*.sav` |
| Recipes, items, power draws | `<Satisfactory>\CommunityResources\Docs\en-US.json` |
| Satisfactory install | Steam's `libraryfolders.vdf`, then `steamapps\common\Satisfactory` |
| Satisfactory Modeler | `steamapps\common\Satisfactory Modeler` |
| Resource node positions | ships with the save parser (see below) |

Recipe data is read from *your* install rather than hardcoded, so the numbers
follow whatever patch you are on instead of drifting from it.

## Plans

A plan is a list of blocks; each block is a list of "N of this building running
this recipe", optionally pinned to a grid cell:

```json
{
  "name": "Iron line",
  "blocks": [
    {
      "id": "ingots",
      "name": "Iron smelting",
      "anchor_cell": [0, 0],
      "machines": [
        {"building_class": "Build_SmelterMk1_C", "recipe_class": "Recipe_IngotIron_C", "count": 6}
      ]
    }
  ]
}
```

`anchor_cell` is what makes the per-block comparison work: existing machines are
assigned to the nearest anchored block, which is what you mean by "that block
over there". Without anchors the app falls back to comparing totals across the
whole factory, and each machine is still only counted once.

Plans are saved to `%APPDATA%\satplanner\plan.json`.

### Importing from Satisfactory Modeler

Modeler's Export writes an `.sfmd` file: JSON describing a **graph**. Each node
is an item ("Iron Plate", "Rotor") whose `Inputs` point at the nodes feeding
it; raw resources carry a per-minute `Max` cap; and `"Solver": "Full"` means
Modeler works out every rate and machine count itself and stores none of them.
Importing therefore re-solves the graph using the game's recipe data.

The graph read is settled (`plan/sfmd.py`). The solver's semantics are
inferred - demand-driven rates, scaled up until the tightest raw cap is met,
node `Max` values as caps - and are flagged provisional until checked against
what Modeler displays for a known plan. Nodes with no matching recipe (Modeler
pseudo-nodes such as "Space Elevator Phase 2") are reported, not guessed.

Setup tab → point it at the Modeler folder or an exported file → **Scan** →
**Import**. Without the game's recipe file the shape imports with one machine
per step and a warning.

## What still needs checking

These are the things that could not be verified without a Windows machine, the
game, and a real save:

1. ~~The save adapter against a real 1.2 save.~~ **Done.** Verified against a
   1.2.4.0 save (save format 60, build 502094): 109 machines with recipes and
   clocks, 48 extractors with node links, 58 containers, player inventory and
   play time all correct. Unknown save versions still raise a warning in the UI
   rather than failing.
2. **The Modeler solver.** The `.sfmd` graph reads correctly (the real export
   is a test fixture). Whether the solved rates match Modeler's own numbers
   needs a side-by-side with a plan open in Modeler - in particular what
   `Max: 1` on a space-elevator node means.
3. **The Windows build.** The PyInstaller packaging and the CI workflow have
   never been run - the development container is Linux and PyInstaller does not
   cross-compile. Expect to iterate on the first build.
4. **The somersloop model.** Overclocking is exact (output scales linearly,
   power by the game's `clock^1.321928`). Somersloop amplification is modelled
   as linear output and quadratic power, which matches the common understanding
   but has not been checked against 1.2 in game.

## Known limitations

- **No terrain.** The save says where buildings are, not what the ground looks
  like. Placement suggestions avoid cells that are already occupied and cluster
  near their block, but the app will happily suggest a cell in a lake. Near an
  existing base they are sound; far from one, check before building.
- **The grid needs foundations.** A base built freehand on terrain has no
  lattice to recover; the app says so and falls back to the world origin. Lay
  foundations anywhere and refresh.
- **Axis-aligned grids only.** A foundation field built at an angle will not
  line up; the vote across foundations picks the dominant offset and treats the
  rest as outliers.
- **Read-only.** It never writes to your save. Deliberately.
- **Autosave cadence.** Saves only hit disk when the game writes them, so the
  view is at best as fresh as your last autosave - a minute-long poll loses
  nothing.
- **Belt and pipe routing is not modelled.** The app knows what is built and
  where, not whether it is correctly fed.

## Layout

```
src/satplanner/
  worldgrid.py        grid maths - recovering the in-game lattice, snapping, free cells
  gamedata.py         parses the game's own Docs JSON into items, recipes, buildings
  config.py           finding saves, the game, Modeler; all overridable by env var
  service.py          application layer - everything the UI can ask for
  savegame/
    model.py          the domain model: machines, miners, storages, foundations
    adapter.py        the only file that knows about the upstream save parser
    classnames.py     class paths -> what kind of building this is
    discovery.py      finding save files, watching for new ones
  plan/
    model.py          plans, blocks, machines; JSON round-trip
    modeler.py        format sniffing and import dispatch for Satisfactory Modeler
    sfmd.py           the .sfmd graph reader and (provisional) rate solver
  analysis/
    production.py     rates, power, throughput
    diff.py           built vs planned, and the construction shopping list
    buildorder.py     dependency-sorted build stages
    resources.py      node selection and extraction rates
    placement.py      where the missing machines should go
  web/                the local server and the browser UI
scripts/
  fetch_parser.py     downloads the save parser into vendor/
  build_exe.py        packages the Windows executable
tests/                90 tests, no game or save file required
```

Run the tests with `python -m pytest`.

## Licensing

Save parsing and the resource-node database come from
[GreyHak/sat_sav_parse](https://github.com/GreyHak/sat_sav_parse), which is
**GPL-3**. It publishes no PyPI package, so `scripts/fetch_parser.py` downloads
it into `vendor/` (git-ignored) rather than committing it here - that keeps this
project's own licensing separate. Note that a built `.exe` bundles it, so
distributing that executable publicly would carry GPL obligations. For personal
use this does not matter.

Satisfactory is made by Coffee Stain Studios. This is an unofficial tool and is
not affiliated with them.
