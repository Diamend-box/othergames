import json
import sqlite3

import pytest

from satplanner.plan.modeler import (
    UnknownModelerFormat,
    import_plan,
    sniff_directory,
    sniff_file,
)


def test_json_is_recognised_and_summarised(tmp_path):
    path = tmp_path / "project.json"
    path.write_text(json.dumps({"factory": {}, "version": 3}))
    report = sniff_file(path)
    assert report.kind == "json"
    assert report.top_level_keys == ["factory", "version"]


def test_sqlite_is_recognised_and_its_tables_listed(tmp_path):
    path = tmp_path / "project.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE machines (id INTEGER)")
        conn.execute("CREATE TABLE recipes (id INTEGER)")
    report = sniff_file(path)
    assert report.kind == "sqlite"
    assert report.top_level_keys == ["machines", "recipes"]


def test_opaque_binary_is_named_as_such_with_readable_strings(tmp_path):
    """When the format is unknown, the report still has to be useful."""
    path = tmp_path / "project.smp"
    path.write_bytes(b"\x00\x01MODELER_PROJECT\x00\xffFactoryLayout\x00")
    report = sniff_file(path)
    assert report.kind == "binary"
    assert "MODELER_PROJECT" in report.preview
    assert not report.describe()["importable"]


def test_machines_are_found_however_deeply_nested(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(
        json.dumps(
            {"document": {"groups": [{"lines": [
                {"recipe": "Recipe_IngotIron_C", "machine": "Build_SmelterMk1_C", "count": 8},
                {"recipe": "Recipe_IronPlate_C", "machine": "Build_ConstructorMk1_C", "quantity": 4},
            ]}]}}
        )
    )
    plan = import_plan(path)
    counts = plan.machine_counts()
    assert counts[("Build_SmelterMk1_C", "Recipe_IngotIron_C")] == 8
    assert counts[("Build_ConstructorMk1_C", "Recipe_IronPlate_C")] == 4


def test_a_clock_given_as_a_percentage_becomes_a_multiplier(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps([{"recipe": "Recipe_IngotIron_C", "clockSpeed": 250}]))
    assert import_plan(path).blocks[0].machines[0].clock == 2.5


def test_our_own_plan_format_round_trips(tmp_path):
    path = tmp_path / "native.json"
    path.write_text(json.dumps({
        "name": "Mine",
        "blocks": [{"id": "b", "name": "B", "anchor_cell": [2, 3],
                    "machines": [{"building_class": "Build_SmelterMk1_C",
                                  "recipe_class": "Recipe_IngotIron_C", "count": 3}]}],
    }))
    plan = import_plan(path)
    assert plan.name == "Mine"
    assert plan.blocks[0].anchor_cell == (2, 3)


def test_unreadable_formats_explain_themselves(tmp_path):
    path = tmp_path / "project.bin"
    path.write_bytes(b"\x00\x01\x02\x03binaryjunk")
    with pytest.raises(UnknownModelerFormat) as exc:
        import_plan(path)
    assert "binary" in str(exc.value)
    assert exc.value.report is not None


def test_json_without_machines_says_so_rather_than_inventing_a_plan(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"theme": "dark", "lastOpened": "yesterday"}))
    with pytest.raises(UnknownModelerFormat):
        import_plan(path)


def test_scanning_a_folder_floats_readable_files_to_the_top(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"\x00\x01\x02\x03")
    (tmp_path / "b.json").write_text("{}")
    (tmp_path / "image.png").write_bytes(b"\x89PNG")
    reports = sniff_directory(tmp_path)
    assert [r.kind for r in reports][0] == "json"
    assert not any(r.path.endswith(".png") for r in reports)
