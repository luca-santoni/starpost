"""Tests for the result store's crash-recovery cache persistence."""
import json
from dataclasses import asdict

from starpost.data.models import (
    Displayer,
    MediaArtifact,
    MonitorPlot,
    PlotKind,
    PlotSeries,
    Report,
    Scene,
    SimResult,
)
from starpost.data.store import ResultStore, _result_to_dict


def _full_result() -> SimResult:
    """A SimResult exercising every field the cache persists."""
    return SimResult(
        sim_path="/cases/caseA.sim",
        reports=[Report("Drag", 1.5, units="N"), Report("Lift", None, error="bad")],
        plots=[
            MonitorPlot(
                "Residuals",
                [PlotSeries("Continuity", [1, 2, 3], [1e-1, 1e-2, 1e-3])],
                kind=PlotKind.RESIDUAL, y_log=True,
            ),
            MonitorPlot(
                "Forces",
                [PlotSeries("Drag", [1, 2], [10.0, 9.5])],
                kind=PlotKind.FORCE, x_label="Time", error="partial",
            ),
        ],
        scenes=[Scene("Pressure", [Displayer("Static Pressure", "scalar")])],
        views=["Front", "Top"],
        media=[MediaArtifact("Pressure", "/out/p.png", source="Pressure",
                             width=1920, height=1080, view="Front")],
        extracted_at="2026-07-02T10:00:00",
    )


def test_result_to_dict_matches_asdict():
    """The hand-built cache snapshot must stay byte-identical to asdict's
    output (it exists only because asdict deep-copies every plot point)."""
    r = _full_result()
    assert json.dumps(_result_to_dict(r), sort_keys=True) == json.dumps(
        asdict(r), sort_keys=True
    )


def test_save_and_load_cache_round_trip(tmp_path):
    store = ResultStore()
    store.put(_full_result())
    path = tmp_path / "cache.json"
    store.save_cache(path)

    loaded = ResultStore()
    loaded.load_cache(path)
    (r,) = loaded.all()
    assert r.sim_path == "/cases/caseA.sim"
    assert [p.kind for p in r.plots] == [PlotKind.RESIDUAL, PlotKind.FORCE]
    assert r.plots[0].series[0].y == [1e-1, 1e-2, 1e-3]
    assert r.scenes[0].displayers[0].name == "Static Pressure"
    assert r.media[0].width == 1920 and r.views == ["Front", "Top"]


def test_save_cache_async_writes_the_same_file(tmp_path):
    """The async save must produce exactly what the synchronous one does."""
    store = ResultStore()
    store.put(_full_result())
    sync_path = tmp_path / "sync.json"
    async_path = tmp_path / "async.json"
    store.save_cache(sync_path)
    store.save_cache_async(async_path).join()
    assert async_path.read_text() == sync_path.read_text()


def test_save_cache_is_atomic_no_temp_leftovers(tmp_path):
    """The cache is written via a temp file + atomic replace: the target is
    always complete/valid JSON and no stray temp files are left behind."""
    store = ResultStore()
    store.put(_full_result())
    path = tmp_path / "cache.json"
    store.save_cache(path)
    # Target exists and is complete, parseable JSON (never torn).
    assert "/cases/caseA.sim" in json.loads(path.read_text())
    # Only the cache file remains — the temp file was replaced, not left over.
    assert [p.name for p in tmp_path.iterdir()] == ["cache.json"]


def test_save_cache_overwrites_existing_atomically(tmp_path):
    """A second save replaces the first cleanly, leaving one valid file."""
    store = ResultStore()
    store.put(_full_result())
    path = tmp_path / "cache.json"
    store.save_cache(path)
    store.remove("/cases/caseA.sim")
    store.save_cache(path)
    assert json.loads(path.read_text()) == {}
    assert [p.name for p in tmp_path.iterdir()] == ["cache.json"]


def test_stale_async_write_is_skipped(tmp_path):
    """A save that was snapshotted before a newer one must never overwrite the
    newer one's file (the generation check in _write_cache)."""
    store = ResultStore()
    store.put(_full_result())
    path = tmp_path / "cache.json"

    old_payload, old_gen = store._snapshot()  # snapshotted first…
    store.remove("/cases/caseA.sim")
    store.save_cache(path)                    # …but a newer save runs first
    newer = path.read_text()

    store._write_cache(old_payload, path, old_gen)  # the stale write arrives late
    assert path.read_text() == newer  # skipped: the newer state was kept
