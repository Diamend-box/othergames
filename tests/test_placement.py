from satplanner.analysis.diff import diff_plan
from satplanner.analysis.placement import suggest_placements


def test_one_suggestion_per_missing_machine(state, plan):
    report = diff_plan(state, plan)
    suggestions = suggest_placements(state, plan, report)
    assert len(suggestions) == report.machines_missing == 5


def test_suggestions_never_land_on_something_already_built(state, plan):
    report = diff_plan(state, plan)
    occupied = {state.anchor.world_to_cell(*m.placement.xy) for m in state.machines}
    occupied |= {state.anchor.world_to_cell(*s.placement.xy) for s in state.storages}
    cells = [s.cell for s in suggest_placements(state, plan, report)]
    assert not set(cells) & occupied
    assert len(set(cells)) == len(cells)


def test_suggested_coordinates_land_on_the_world_grid(state, plan):
    """The whole point: a suggestion must be a real in-game position."""
    report = diff_plan(state, plan)
    for suggestion in suggest_placements(state, plan, report):
        assert state.anchor.snap(suggestion.world_x, suggestion.world_y) == (
            suggestion.world_x,
            suggestion.world_y,
        )
        assert state.anchor.world_to_cell(suggestion.world_x, suggestion.world_y) == suggestion.cell


def test_suggestions_stay_near_their_block(state, plan):
    report = diff_plan(state, plan)
    by_block = {}
    for suggestion in suggest_placements(state, plan, report):
        by_block.setdefault(suggestion.block_id, []).append(suggestion.cell)
    # The plates block is anchored at cell (10, 0); its suggestions should
    # cluster there rather than beside the smelters at the origin.
    assert all(abs(cx - 10) <= 3 for cx, _ in by_block["plates"])
    assert all(abs(cx) <= 3 for cx, _ in by_block["ingots"])
