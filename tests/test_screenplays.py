"""Screenplays feature: discovery, media-index parsing, record-macro generation,
settings round-trips, and cache persistence (the Screenplays tab's backend)."""
import json
from pathlib import Path

from starpost.core.macro_generator import render_macro
from starpost.core.result_parser import parse_media_index, parse_sim_output
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
