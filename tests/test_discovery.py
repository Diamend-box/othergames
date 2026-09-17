import time

from satplanner.savegame.discovery import SaveWatcher, latest_save, list_saves, newest_session


def make_save(directory, name, age_seconds=0):
    path = directory / name
    path.write_bytes(b"not really a save")
    stamp = time.time() - age_seconds
    import os

    os.utime(path, (stamp, stamp))
    return path


def test_saves_are_found_recursively_and_sorted_newest_first(tmp_path):
    (tmp_path / "76561198000000000").mkdir()
    make_save(tmp_path / "76561198000000000", "Old.sav", age_seconds=600)
    make_save(tmp_path / "76561198000000000", "New.sav", age_seconds=0)
    saves = list_saves(tmp_path)
    assert [s.name for s in saves] == ["New", "Old"]
    assert latest_save(tmp_path).name == "New"


def test_a_missing_folder_is_not_an_error(tmp_path):
    assert list_saves(tmp_path / "nope") == []
    assert latest_save(None) is None


def test_autosaves_collapse_into_their_session(tmp_path):
    """A save folder is mostly autosaves; the picker should show worlds."""
    make_save(tmp_path, "Ficsit_autosave_0.sav", age_seconds=300)
    make_save(tmp_path, "Ficsit_autosave_1.sav", age_seconds=60)
    make_save(tmp_path, "Other.sav", age_seconds=10)
    sessions = newest_session(list_saves(tmp_path))
    assert sorted(s.name for s in sessions) == ["Ficsit_autosave_1", "Other"]


def test_the_watcher_fires_once_per_change(tmp_path):
    path = make_save(tmp_path, "Ficsit.sav")
    seen = []
    watcher = SaveWatcher(get_path=lambda: path, on_change=seen.append, interval=0.01)

    assert watcher.check_once() is True
    assert watcher.check_once() is False

    import os

    later = time.time() + 10
    os.utime(path, (later, later))
    assert watcher.check_once() is True
    assert len(seen) == 2


def test_the_watcher_shrugs_off_a_missing_file(tmp_path):
    watcher = SaveWatcher(get_path=lambda: tmp_path / "gone.sav", on_change=lambda p: None)
    assert watcher.check_once() is False
