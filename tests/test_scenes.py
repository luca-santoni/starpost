"""Scene-still feature: scene discovery, media-index parsing, and render-macro
generation (the Scenes tab's backend)."""
import tempfile
from pathlib import Path

from starpost.core.macro_generator import _java_string_array, render_scenes_macro
from starpost.core.result_parser import parse_media_index, parse_sim_output

CLASSIFICATION = {"residual_keywords": ["residual"], "force_keywords": ["force"]}


def test_parse_sim_output_reads_scene_names(tmp_path):
    sim = tmp_path / "caseA.sim"
    (tmp_path / "caseA__scenes_index.csv").write_text(
        "scene\nScalar Scene 1\nVelocity\n"
    )
    res = parse_sim_output(str(sim), tmp_path, CLASSIFICATION)
    assert res.scenes == ["Scalar Scene 1", "Velocity"]


def test_parse_sim_output_no_scenes_index_is_empty(tmp_path):
    # Older extractions (pre-scenes) simply have no scene list.
    sim = tmp_path / "caseA.sim"
    res = parse_sim_output(str(sim), tmp_path, CLASSIFICATION)
    assert res.scenes == []


def test_parse_media_index_resolves_paths_and_errors(tmp_path):
    (tmp_path / "caseA__media_index.csv").write_text(
        "kind,source,name,file,error\n"
        "still,Scalar Scene 1,Scalar Scene 1,caseA__scene__Scalar_Scene_1.png,\n"
        "still,Velocity,Velocity,,ERROR\n"
    )
    media = parse_media_index("caseA", tmp_path)
    assert len(media) == 2
    ok = media[0]
    assert ok.kind == "still" and ok.source == "Scalar Scene 1" and ok.error is None
    assert ok.path == str((tmp_path / "caseA__scene__Scalar_Scene_1.png").resolve())
    bad = media[1]
    assert bad.error == "ERROR" and bad.path == ""


def test_parse_media_index_missing_is_empty(tmp_path):
    assert parse_media_index("caseA", tmp_path) == []


def test_java_string_array_quotes_and_escapes():
    assert _java_string_array([]) == ""
    assert _java_string_array(["A", "B"]) == '"A", "B"'
    # Embedded quotes and backslashes are escaped for a Java string literal.
    assert _java_string_array(['Quote"Name']) == '"Quote\\"Name"'


def test_render_scenes_macro_embeds_selection_and_resolution():
    with tempfile.TemporaryDirectory() as d:
        path = render_scenes_macro(
            Path("/out"), Path(d), ["Scalar Scene 1"], 1280, 720, 2
        )
        text = path.read_text()
        assert path.name == "render_scenes.java"
        assert "public class render_scenes" in text
        assert '"Scalar Scene 1"' in text
        assert "IMG_WIDTH = 1280" in text
        assert "IMG_HEIGHT = 720" in text
        assert "MAGNIFICATION = 2" in text
