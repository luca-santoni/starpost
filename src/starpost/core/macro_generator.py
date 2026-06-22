"""Render the Java extraction macro from its Jinja2 template.

The STAR-CCM+ batch runner requires the public class name to match the .java
filename, so we always render to `extract_all.java` (class `extract_all`).
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_MACRO_DIR = Path(__file__).resolve().parent.parent / "macros"
_TEMPLATE = "extract_all.java.j2"
_CLASS_NAME = "extract_all"
_RENDER_TEMPLATE = "render_scenes.java.j2"
_RENDER_CLASS_NAME = "render_scenes"

_env = Environment(
    loader=FileSystemLoader(str(_MACRO_DIR)),
    autoescape=select_autoescape(enabled_extensions=()),  # plain Java, no escaping
    keep_trailing_newline=True,
)


def render_macro(output_dir: Path, dest_dir: Path) -> Path:
    """Render the macro that exports to `output_dir`. Returns the .java path.

    `dest_dir` is where the .java file is written (a temp dir per run).
    """
    # Java string literal: forward slashes are safe on Linux and tolerated by
    # the STAR-CCM+ JVM on Windows, avoiding backslash-escaping headaches.
    out = str(output_dir).replace("\\", "/")
    text = _env.get_template(_TEMPLATE).render(output_dir=out)

    java_path = dest_dir / f"{_CLASS_NAME}.java"
    java_path.write_text(text, encoding="utf-8")
    return java_path


def _java_string_array(names: list[str]) -> str:
    """Render ``names`` as the body of a Java String[] initializer, i.e. a comma-
    separated list of quoted, escaped literals (empty string for an empty list)."""
    parts = []
    for n in names:
        escaped = n.replace("\\", "\\\\").replace('"', '\\"')
        parts.append(f'"{escaped}"')
    return ", ".join(parts)


def render_scenes_macro(
    output_dir: Path,
    dest_dir: Path,
    scene_names: list[str],
    width: int,
    height: int,
    magnification: int,
) -> Path:
    """Render the scene-still macro that exports to ``output_dir``. Returns the
    .java path. ``scene_names`` empty means render every scene in the .sim.

    ``dest_dir`` is where the .java file is written (a temp dir per run).
    """
    out = str(output_dir).replace("\\", "/")
    text = _env.get_template(_RENDER_TEMPLATE).render(
        output_dir=out,
        scene_names_java=_java_string_array(scene_names),
        width=int(width),
        height=int(height),
        magnification=int(magnification),
    )
    java_path = dest_dir / f"{_RENDER_CLASS_NAME}.java"
    java_path.write_text(text, encoding="utf-8")
    return java_path
