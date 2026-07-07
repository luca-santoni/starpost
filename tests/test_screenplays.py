"""Screenplays feature: discovery, media-index parsing, record-macro generation,
settings round-trips, and cache persistence (the Screenplays tab's backend)."""
import json

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
