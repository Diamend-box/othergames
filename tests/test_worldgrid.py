from satplanner.worldgrid import (
    DEFAULT_CELL_UU,
    GridAnchor,
    cells_covering,
    free_cells_near,
    infer_anchor,
)


def test_cell_round_trip_is_exact():
    anchor = GridAnchor(origin_x=450.0, origin_y=50.0)
    for point in [(450.0, 50.0), (1250.0, 850.0), (-1150.0, -750.0)]:
        assert anchor.cell_to_world(*anchor.world_to_cell(*point)) == point


def test_positions_snap_to_the_nearest_cell():
    anchor = GridAnchor()
    # 399 uu is just inside the first cell; 401 tips over into the next one.
    assert anchor.world_to_cell(399.0, 0.0)[0] == 0
    assert anchor.world_to_cell(401.0, 0.0)[0] == 1


def test_anchor_is_recovered_from_a_foundation_field():
    """A regular field of foundations should reveal the grid's phase."""
    positions = [(450.0 + 800 * i, 50.0 + 800 * j) for i in range(5) for j in range(5)]
    anchor = infer_anchor(positions)
    assert anchor.origin_x == 450.0
    assert anchor.origin_y == 50.0
    assert anchor.cell_uu == DEFAULT_CELL_UU


def test_freehand_placements_do_not_move_the_grid():
    """A few odd buildings must not outvote the foundations around them."""
    positions = [(450.0 + 800 * i, 50.0) for i in range(12)]
    positions += [(123.0, 456.0), (789.0, 12.0)]
    anchor = infer_anchor(positions)
    assert anchor.origin_x == 450.0


def test_offset_reveals_a_building_placed_off_grid():
    anchor = GridAnchor(origin_x=0.0, origin_y=0.0)
    dx, dy = anchor.offset_from_lattice(830.0, 0.0)
    assert round(dx) == 30
    assert dy == 0


def test_no_foundations_falls_back_to_the_origin():
    anchor = infer_anchor([])
    assert (anchor.origin_x, anchor.origin_y) == (0.0, 0.0)
    assert anchor.source == "default"


def test_free_cells_skip_occupied_ones_and_stay_close():
    occupied = {(0, 0), (1, 0), (0, 1)}
    cells = free_cells_near(occupied, (0, 0), 3)
    assert len(cells) == 3
    assert not set(cells) & occupied
    assert all(max(abs(cx), abs(cy)) <= 2 for cx, cy in cells)


def test_cells_covering_deduplicates_within_a_cell():
    anchor = GridAnchor()
    cells = cells_covering([(0.0, 0.0), (100.0, 100.0), (900.0, 0.0)], anchor)
    assert cells == {(0, 0), (1, 0)}
