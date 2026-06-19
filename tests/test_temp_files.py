import pytest

from starpost.utils import paths


@pytest.fixture
def cache(monkeypatch, tmp_path):
    """Redirect the cache dir and system temp dir to throwaway locations, seeded
    with representative temp files (so tests never touch the real ones)."""
    c = tmp_path / "cache"
    c.mkdir()
    monkeypatch.setattr(paths, "cache_dir", lambda: c)

    # Isolate the system temp dir scanned for leftover macro working folders.
    sys_temp = tmp_path / "systmp"
    sys_temp.mkdir()
    monkeypatch.setattr(paths.tempfile, "gettempdir", lambda: str(sys_temp))

    (c / "starpost.log").write_text("log")
    (c / "starpost.log.1").write_text("rotated")
    (c / "results_cache.json").write_text("{}")
    (c / "file_list.json").write_text("[]")
    (c / "checkmark_ffc829.png").write_bytes(b"x")
    updates = c / "updates"
    updates.mkdir()
    (updates / "Setup.exe").write_bytes(b"y")
    (sys_temp / "starpost_macro_abc123").mkdir()
    return c


def test_temp_paths_lists_cache_and_macro_leftovers(cache):
    names = {p.name for p in paths.temp_paths()}
    assert names == {
        "starpost.log",
        "starpost.log.1",
        "results_cache.json",
        "file_list.json",
        "checkmark_ffc829.png",
        "updates",
        "starpost_macro_abc123",
    }


def test_describe_dedupes_and_labels(cache):
    labels = paths.describe_temp_paths(paths.temp_paths())
    # The two log files collapse into a single "Application logs" entry.
    assert labels.count("Application logs") == 1
    assert "Cached extraction results (crash recovery)" in labels
    assert "Saved Files-tab list" in labels
    assert "Generated theme icons" in labels
    assert "Downloaded update installers" in labels
    assert "Leftover macro working folders" in labels


def test_clear_removes_everything_but_keeps_cache_dir(cache):
    removed, failed = paths.clear_temp_files()
    assert failed == []
    # 5 cache files + the updates/ dir + the macro leftover dir.
    assert removed == 7
    assert list(cache.iterdir()) == []
    assert cache.exists()  # the dir itself is kept, only its contents go


def test_clear_is_safe_when_empty(monkeypatch, tmp_path):
    empty = tmp_path / "cache"
    empty.mkdir()
    sys_temp = tmp_path / "systmp"
    sys_temp.mkdir()
    monkeypatch.setattr(paths, "cache_dir", lambda: empty)
    monkeypatch.setattr(paths.tempfile, "gettempdir", lambda: str(sys_temp))
    removed, failed = paths.clear_temp_files()
    assert failed == []
    assert removed == 0
