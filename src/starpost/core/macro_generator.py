"""Render the Java extraction macro from its Jinja2 template.

The STAR-CCM+ batch runner requires the public class name to match the .java
filename, so we always render to `extract_all.java` (class `extract_all`).
"""
from __future__ import annotations

from pathlib import Path

_MACRO_DIR = Path(__file__).resolve().parent.parent / "macros"
_TEMPLATE = "extract_all.java.j2"
_CLASS_NAME = "extract_all"
_RENDER_TEMPLATE = "render_scenes.java.j2"
_RENDER_CLASS_NAME = "render_scenes"
_RECORD_TEMPLATE = "record_screenplays.java.j2"
_RECORD_CLASS_NAME = "record_screenplays"

# Encoder quality factor per MOVIE_QUALITIES level, embedded in the record
# macro (passed to float/double recorder parameters).
_QUALITY_FACTORS = {"low": 0.5, "medium": 0.75, "high": 1.0}

_env = None


def _get_env():
    """The Jinja2 environment, created on first use. jinja2 is a ~40 ms import
    that this module would otherwise put on the startup path (the main window
    imports the batch worker, which imports the runner, which imports this), yet
    it's only needed once a run actually starts."""
    global _env
    if _env is None:
        from jinja2 import Environment, FileSystemLoader, select_autoescape

        _env = Environment(
            loader=FileSystemLoader(str(_MACRO_DIR)),
            autoescape=select_autoescape(enabled_extensions=()),  # plain Java
            keep_trailing_newline=True,
        )
    return _env


def render_macro(output_dir: Path, dest_dir: Path) -> Path:
    """Render the macro that exports to `output_dir`. Returns the .java path.

    `dest_dir` is where the .java file is written (a temp dir per run).
    """
    # Java string literal: forward slashes are safe on Linux and tolerated by
    # the STAR-CCM+ JVM on Windows, avoiding backslash-escaping headaches.
    out = str(output_dir).replace("\\", "/")
    text = _get_env().get_template(_TEMPLATE).render(output_dir=out)

    java_path = dest_dir / f"{_CLASS_NAME}.java"
    java_path.write_text(text, encoding="utf-8")
    return java_path


def _java_literal(s: str) -> str:
    """A quoted, escaped Java string literal for ``s``."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _java_string_array(names: list[str]) -> str:
    """Render ``names`` as the body of a Java String[] initializer, i.e. a comma-
    separated list of quoted, escaped literals (empty string for an empty list)."""
    return ", ".join(_java_literal(n) for n in names)


def _java_show_map_puts(scene_show: dict[str, list[str]]) -> str:
    """Render the ``m.put(...)`` statements that populate the scene -> visible
    displayers map in the render macro (one per scene, newline-separated)."""
    lines = []
    for scene, displayers in scene_show.items():
        members = ", ".join(_java_literal(d) for d in displayers)
        # LinkedHashSet preserves selection order so the displayer-name component
        # of the output file/label is deterministic.
        lines.append(
            f"m.put({_java_literal(scene)}, "
            f"new LinkedHashSet<>(Arrays.asList({members})));"
        )
    return "\n        ".join(lines)


def render_scenes_macro(
    output_dir: Path,
    dest_dir: Path,
    scene_show: dict[str, list[str]],
    view_names: list[str],
    width: int,
    height: int,
    magnification: int,
    image_format: str = "png",
) -> Path:
    """Render the scene-still macro that exports to ``output_dir``. Returns the
    .java path. ``scene_show`` maps each scene to render to the scalar/vector
    displayers to keep visible (its other field displayers are hidden).
    ``view_names`` are the saved camera views to render each scene from; empty
    renders from each scene's current view. ``image_format`` is the output file
    extension (png/jpg/tiff), which STAR-CCM+ uses to pick the image format.

    ``dest_dir`` is where the .java file is written (a temp dir per run).
    """
    out = str(output_dir).replace("\\", "/")
    text = _get_env().get_template(_RENDER_TEMPLATE).render(
        output_dir=out,
        show_map_puts=_java_show_map_puts(scene_show),
        view_names_java=_java_string_array(view_names),
        width=int(width),
        height=int(height),
        magnification=int(magnification),
        image_ext=str(image_format),
    )
    java_path = dest_dir / f"{_RENDER_CLASS_NAME}.java"
    java_path.write_text(text, encoding="utf-8")
    return java_path


def record_screenplays_macro(
    output_dir: Path,
    dest_dir: Path,
    screenplay_show: dict[str, list[str]],
    view_names: list[str],
    width: int,
    height: int,
    fps: int,
    movie_format: str = "mp4",
    quality: str = "high",
    anim_length: float = 0.0,
    start_time: float = 0.0,
) -> Path:
    """Render the screenplay-record macro that exports to ``output_dir``.
    Returns the .java path. ``screenplay_show`` maps each screenplay to record
    to the scalar/vector displayers of its scene to keep visible.
    ``view_names`` are the saved camera views to record each screenplay from;
    empty records from each screenplay's own camera. ``movie_format`` is the
    output file extension (mp4/avi/mov), which STAR-CCM+ uses to pick the
    encoder; ``quality`` is a MOVIE_QUALITIES level mapped to a 0..1 factor.
    ``anim_length`` is the recording length in seconds (0 ==
    record each screenplay at its own preferred length); ``start_time`` is
    the offset in seconds the recording starts from.

    ``dest_dir`` is where the .java file is written (a temp dir per run).
    """
    out = str(output_dir).replace("\\", "/")
    text = _get_env().get_template(_RECORD_TEMPLATE).render(
        output_dir=out,
        show_map_puts=_java_show_map_puts(screenplay_show),
        view_names_java=_java_string_array(view_names),
        width=int(width),
        height=int(height),
        fps=int(fps),
        movie_ext=str(movie_format),
        quality_factor=_QUALITY_FACTORS.get(str(quality), 1.0),
        anim_length=float(anim_length),
        start_time=float(start_time),
    )
    java_path = dest_dir / f"{_RECORD_CLASS_NAME}.java"
    java_path.write_text(text, encoding="utf-8")
    return java_path
