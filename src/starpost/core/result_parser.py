"""Parse the CSVs the Java macro exports back into the data model.

Also classifies each monitor plot (residual -> log Y, force -> linear Y) using
keyword heuristics from settings; the result is overridable per-plot.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from starpost.data.models import (
    MediaArtifact,
    MonitorPlot,
    PlotKind,
    PlotSeries,
    Report,
    SimResult,
)
from starpost.utils.logging import get_logger

log = get_logger("parser")


def classify_plot(name: str, classification: dict) -> tuple[PlotKind, bool]:
    """Return (kind, y_log) for a plot name. Residual -> log Y; force -> linear."""
    low = name.lower()
    for kw in classification.get("residual_keywords", []):
        if kw in low:
            return PlotKind.RESIDUAL, True
    for kw in classification.get("force_keywords", []):
        if kw in low:
            return PlotKind.FORCE, False
    return PlotKind.OTHER, False


def parse_sim_output(
    sim_path: str, output_dir: Path, classification: dict
) -> SimResult:
    """Build a SimResult from the per-sim CSVs in `output_dir`."""
    sim_name = Path(sim_path).stem
    result = SimResult(
        sim_path=sim_path,
        extracted_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    result.reports = _parse_reports(output_dir / f"{sim_name}_reports.csv")
    result.plots = _parse_plots(sim_name, output_dir, classification)
    result.scenes = _parse_scenes(output_dir / f"{sim_name}__scenes_index.csv")
    return result


def _parse_scenes(path: Path) -> list[str]:
    """Read the scene-name list the extraction macro wrote (one name per row)."""
    if not path.exists():
        # Older extractions (pre-scenes) simply have no scene list.
        return []
    scenes: list[str] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = (row.get("scene") or "").strip()
            if name:
                scenes.append(name)
    return scenes


def parse_media_index(sim_name: str, output_dir: Path) -> list[MediaArtifact]:
    """Read the media index a render pass wrote into ``output_dir`` and resolve
    each entry's file to an absolute path. Missing index -> empty list."""
    path = output_dir / f"{sim_name}__media_index.csv"
    if not path.exists():
        log.warning("media index missing: %s", path)
        return []
    media: list[MediaArtifact] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            file_cell = (row.get("file") or "").strip()
            err = (row.get("error") or "").strip()
            full = str((output_dir / file_cell).resolve()) if file_cell else ""
            media.append(
                MediaArtifact(
                    name=row.get("name", ""),
                    path=full,
                    source=row.get("source", ""),
                    kind=row.get("kind", "still") or "still",
                    error=err or None,
                )
            )
    return media


def _parse_reports(path: Path) -> list[Report]:
    if not path.exists():
        log.warning("reports CSV missing: %s", path)
        return []
    reports: list[Report] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw = (row.get("value") or "").strip()
            if raw == "" or raw.upper() == "ERROR":
                reports.append(
                    Report(name=row["report"], value=None, units=row.get("units", ""),
                           error="extraction failed")
                )
            else:
                try:
                    val: Optional[float] = float(raw)
                    err = None
                except ValueError:
                    val, err = None, f"unparseable value: {raw!r}"
                reports.append(
                    Report(name=row["report"], value=val,
                           units=row.get("units", ""), error=err)
                )
    return reports


def _parse_plots(
    sim_name: str, output_dir: Path, classification: dict
) -> list[MonitorPlot]:
    index = output_dir / f"{sim_name}__plots_index.csv"
    if not index.exists():
        log.warning("plots index missing: %s", index)
        return []

    plots: list[MonitorPlot] = []
    with index.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = row["plot"]
            csv_file = (row.get("csv_file") or "").strip()
            kind, y_log = classify_plot(name, classification)
            if csv_file == "" or csv_file.upper() == "ERROR":
                plots.append(MonitorPlot(name=name, kind=kind, y_log=y_log,
                                         error="plot export failed"))
                continue
            series = _parse_plot_series(output_dir / csv_file)
            plots.append(MonitorPlot(name=name, series=series, kind=kind, y_log=y_log))
    return plots


def _parse_plot_series(path: Path) -> list[PlotSeries]:
    """STAR-CCM+ plot export: first column is X, each subsequent column a series.

    Some exports repeat an X column per series; we handle the common single-X
    layout here and fall back to pairwise (X,Y) columns when widths suggest it.
    TODO: validate against real exports from a few plot types and tighten.
    """
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if len(rows) < 2:
        return []

    header, data = rows[0], rows[1:]
    x_label = header[0]
    series = [PlotSeries(name=col or f"series_{i}") for i, col in enumerate(header[1:], 0)]

    for r in data:
        if not r:
            continue
        try:
            x = float(r[0])
        except (ValueError, IndexError):
            continue
        for i, s in enumerate(series):
            try:
                y = float(r[i + 1])
            except (ValueError, IndexError):
                continue
            s.x.append(x)
            s.y.append(y)
    _ = x_label  # x label currently fixed to "Iteration" in the model
    return series
