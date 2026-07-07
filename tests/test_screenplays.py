"""Screenplays feature: discovery, media-index parsing, record-macro generation,
settings round-trips, and cache persistence (the Screenplays tab's backend)."""
import json
import pytest
import tempfile
from pathlib import Path

from starpost.core.macro_generator import record_screenplays_macro, render_macro
from starpost.core.result_parser import parse_media_index, parse_sim_output
from starpost.core.settings import MediaConfig, Settings
from starpost.data.models import Displayer, MediaArtifact, Screenplay, SimResult
from starpost.data.store import ResultStore

CLASSIFICATION = {"residual_keywords": ["residual"], "force_keywords": ["force"]}


def test_store_round_trips_screenplays_and_movie_poster(tmp_path):
    res = SimResult(sim_path="/c/a.sim")
    res.screenplays = [
        Screenplay(
            name="Flyby",
            scene="Results",
            displayers=[Displayer(name="Scalar velocity", kind="scalar")],
        ),
    ]
    res.media = [
        MediaArtifact(
            name="Flyby-Front", path="/out/a-Flyby-Front.mp4", source="Flyby",
            kind="movie", view="Front", poster="/out/a-Flyby-Front_poster.png",
        ),
    ]
    store = ResultStore()
    store.put(res)
    path = tmp_path / "cache.json"
    store.save_cache(path)

    loaded = ResultStore()
    loaded.load_cache(path)
    got = loaded.get("/c/a.sim")
    assert [sp.name for sp in got.screenplays] == ["Flyby"]
    assert got.screenplays[0].scene == "Results"
    assert [(d.name, d.kind) for d in got.screenplays[0].displayers] == [
        ("Scalar velocity", "scalar")
    ]
    assert got.media[0].kind == "movie"
    assert got.media[0].poster == "/out/a-Flyby-Front_poster.png"
    assert got.screenplay_names() == {"Flyby"}


def test_old_cache_without_screenplays_loads_empty(tmp_path):
    # Caches written before this feature have no "screenplays" key and no
    # "poster" field on media entries; they must still load.
    store = ResultStore()
    res = SimResult(sim_path="/c/a.sim")
    res.media = [MediaArtifact(name="s", path="/out/s.png", source="S")]
    store.put(res)
    path = tmp_path / "cache.json"
    store.save_cache(path)
    payload = json.loads(path.read_text())
    for d in payload.values():
        d.pop("screenplays", None)
        for m in d.get("media", []):
            m.pop("poster", None)
    path.write_text(json.dumps(payload))

    loaded = ResultStore()
    loaded.load_cache(path)
    got = loaded.get("/c/a.sim")
    assert got.screenplays == []
    assert got.media[0].poster == ""


def test_parse_sim_output_reads_screenplays(tmp_path):
    sim = tmp_path / "caseA.sim"
    (tmp_path / "caseA__screenplays_index.csv").write_text(
        "screenplay,scene,displayer,kind\n"
        "Flyby,Results,Scalar velocity,scalar\n"
        "Flyby,Results,Vector 1,vector\n"
        "Intro,,,\n"  # a screenplay whose scene couldn't be resolved
    )
    res = parse_sim_output(str(sim), tmp_path, CLASSIFICATION)
    assert [s.name for s in res.screenplays] == ["Flyby", "Intro"]
    flyby = res.screenplays[0]
    assert flyby.scene == "Results"
    assert [(d.name, d.kind) for d in flyby.displayers] == [
        ("Scalar velocity", "scalar"),
        ("Vector 1", "vector"),
    ]
    intro = res.screenplays[1]
    assert intro.scene == "" and intro.displayers == []


def test_parse_sim_output_no_screenplays_index_is_empty(tmp_path):
    res = parse_sim_output(str(tmp_path / "caseA.sim"), tmp_path, CLASSIFICATION)
    assert res.screenplays == []


def test_parse_media_index_reads_movie_and_poster(tmp_path):
    (tmp_path / "caseA__media_index.csv").write_text(
        "kind,source,name,file,error,displayers,view,poster\n"
        "movie,Flyby,Flyby-Front,caseA-Flyby-Front.mp4,,"
        "Scalar velocity,Front,caseA-Flyby-Front_poster.png\n"
        "movie,Intro,Intro,,ERROR,,,\n"
    )
    media = parse_media_index("caseA", tmp_path)
    ok = media[0]
    assert ok.kind == "movie"
    assert ok.path == str((tmp_path / "caseA-Flyby-Front.mp4").resolve())
    assert ok.poster == str(
        (tmp_path / "caseA-Flyby-Front_poster.png").resolve()
    )
    bad = media[1]
    assert bad.error == "ERROR" and bad.path == "" and bad.poster == ""


def test_parse_media_index_without_poster_column(tmp_path):
    # A scenes render pass writes no poster column; artifacts default to "".
    (tmp_path / "caseA__media_index.csv").write_text(
        "kind,source,name,file,error,displayers,view\n"
        "still,Results,Results,caseA-Results.png,,,\n"
    )
    media = parse_media_index("caseA", tmp_path)
    assert media[0].poster == ""


def test_extract_macro_lists_screenplays(tmp_path):
    path = render_macro(Path("/out"), tmp_path)
    text = path.read_text()
    assert "exportScreenplays" in text
    assert "__screenplays_index.csv" in text
    # No compile-time dependency on the screenplay API.
    assert "import star.screenplay" not in text
    assert 'Class.forName("star.screenplay.ScreenplayManager")' in text


def test_media_config_movie_defaults():
    m = MediaConfig()
    assert m.movie_format == "mp4"
    assert m.movie_fps == 30
    assert m.movie_resolution == "1080p"
    assert m.movie_quality == "high"
    assert m.screenplays_per_checkout == 1
    assert m.movie_dimensions() == (1920, 1080)
    assert MediaConfig(movie_resolution="2160p").movie_dimensions() == (3840, 2160)


def test_media_config_movie_round_trip():
    s = Settings.from_dict({"media": {
        "movie_format": "AVI",
        "movie_fps": 24,
        "movie_resolution": "2160p",
        "movie_quality": "Medium",
        "screenplays_per_checkout": 3,
    }})
    assert s.media.movie_format == "avi"          # normalized to lowercase
    assert s.media.movie_fps == 24
    assert s.media.movie_resolution == "2160p"
    assert s.media.movie_quality == "medium"
    assert s.media.screenplays_per_checkout == 3
    out = s.to_dict()["media"]
    assert out["movie_format"] == "avi"
    assert out["movie_fps"] == 24
    assert out["movie_resolution"] == "2160p"
    assert out["movie_quality"] == "medium"
    assert out["screenplays_per_checkout"] == 3


def test_media_config_movie_values_clamped():
    # Unknown values fall back to defaults; counts are coerced to >= 1.
    s = Settings.from_dict({"media": {
        "movie_format": "webm",
        "movie_resolution": "4320p",
        "movie_quality": "ultra",
        "movie_fps": 0,
        "screenplays_per_checkout": 0,
    }})
    assert s.media.movie_format == "mp4"
    assert s.media.movie_resolution == "1080p"
    assert s.media.movie_quality == "high"
    assert s.media.movie_fps == 1
    assert s.media.screenplays_per_checkout == 1


def test_record_screenplays_macro_embeds_selection_and_movie_settings():
    with tempfile.TemporaryDirectory() as d:
        path = record_screenplays_macro(
            Path("/out"),
            Path(d),
            {"Flyby": ["Scalar velocity"], "Intro": []},
            ["Front"],
            1920,
            1080,
            24,
            "avi",
            "medium",
        )
        text = path.read_text()
        assert path.name == "record_screenplays.java"
        assert "public class record_screenplays" in text
        assert 'MOV_EXT = "avi"' in text
        assert "FPS = 24" in text
        assert "MOV_WIDTH = 1920" in text and "MOV_HEIGHT = 1080" in text
        assert "QUALITY = 0.75" in text
        assert 'VIEW_NAMES = { "Front" }' in text
        assert (
            'm.put("Flyby", new LinkedHashSet<>(Arrays.asList('
            '"Scalar velocity")));'
        ) in text
        assert 'm.put("Intro", new LinkedHashSet<>(Arrays.asList()));' in text
        # No compile-time dependency on the screenplay API; graceful lookup.
        assert "import star.screenplay" not in text
        assert "Class.forName" in text
        # Each screenplay's scene is closed to free graphics memory.
        assert "scene.close()" in text
        # The reflective recorder scans director sub-objects and write* methods,
        # and its failure path dumps unfillable candidates / the full API.
        assert '"getScreenplayDirector"' in text
        assert 'n.startsWith("write")' in text
        assert "[unfillable]" in text
        assert "-- public methods of " in text
        # A candidate that returns without producing the movie is rejected.
        assert "[no output file]" in text
        assert 'n.contains("movie")' in text
        # Single-frame exports are excluded; the target file is pre-created so
        # STAR's writability probe passes, and empty stubs are cleaned up.
        assert 'n.contains("frame")' in text
        assert "createNewFile" in text
        assert "deleteIfEmpty" in text


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _StubRunner:
    """Duck-typed runner for worker tests: records calls, returns canned
    artifacts or raises."""

    def __init__(self, artifacts=None, error=None):
        self.calls = []
        self._artifacts = artifacts or []
        self._error = error

    def record_screenplays(self, sim_file, output_dir, show, views,
                           log_sink=None):
        self.calls.append((sim_file, dict(show), list(views)))
        if self._error:
            raise self._error
        return list(self._artifacts)


def test_screenplay_record_worker_emits_artifacts(app, tmp_path):
    from starpost.batch.queue import ScreenplayRecordWorker

    art = MediaArtifact(name="Flyby", path="/out/a.mp4", source="Flyby",
                        kind="movie")
    runner = _StubRunner(artifacts=[art])
    jobs = [(tmp_path / "a.sim", {"Flyby": ["Scalar velocity"]})]
    worker = ScreenplayRecordWorker(jobs, runner, tmp_path, views=["Front"])
    recorded, progress, finished = [], [], []
    worker.recorded.connect(lambda sp, arts: recorded.append((sp, arts)))
    worker.progress.connect(lambda done, total: progress.append((done, total)))
    worker.finished.connect(lambda: finished.append(1))
    worker.run()
    assert recorded == [(str(tmp_path / "a.sim"), [art])]
    assert progress == [(1, 1)] and finished == [1]
    assert runner.calls == [
        (tmp_path / "a.sim", {"Flyby": ["Scalar velocity"]}, ["Front"])
    ]


def test_screenplay_record_worker_continues_after_failure(app, tmp_path):
    from starpost.batch.queue import ScreenplayRecordWorker

    runner = _StubRunner(error=RuntimeError("boom"))
    jobs = [
        (tmp_path / "a.sim", {"Flyby": []}),
        (tmp_path / "b.sim", {"Intro": []}),
    ]
    worker = ScreenplayRecordWorker(jobs, runner, tmp_path)
    logs, finished = [], []
    worker.log.connect(logs.append)
    worker.finished.connect(lambda: finished.append(1))
    worker.run()
    assert finished == [1]
    assert len(runner.calls) == 2  # the second job still ran
    assert any("Recording failed" in line for line in logs)
