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
    java_path.write_text(text)
    return java_path
