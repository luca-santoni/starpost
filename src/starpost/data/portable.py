"""Portable CSV (de)serialisation of a SimResult.

A full-fidelity, round-trippable dump of one .sim's extracted post-processing
(reports plus monitor plots and their series), written so another StarPost
instance can re-import the data without opening the .sim in STAR-CCM+.

The file is a single CSV whose first line is a ``FORMAT,VERSION`` signature.
Every following row is tagged by its first cell, except a plot's data rows,
which are stored *columnar* (a shared X column plus one column per series) to
keep the file compact:

    starpost-data,2
    meta,sim_path,/cases/caseA.sim
    meta,extracted_at,2026-06-16T12:00:00+00:00
    report,Drag Force,12.5,N,
    plot,Residuals,residual,Iteration,true,
    head,Iteration,Continuity,X-momentum
    1,0.1,0.2
    2,0.01,0.02

A ``head`` row names the X axis and the series filling each column; the
numeric rows beneath it are the data, one per X value, until the next tag.
Series that don't share an X vector are written as separate head/data blocks
under the same plot. One file holds exactly one data set (sim).
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

from starpost.data.models import (
    MonitorPlot,
    PlotKind,
    PlotSeries,
    Report,
    SimResult,
)

# Signature written on the first line. Bump VERSION if the layout changes in a
# way older readers can't handle; readers verify FORMAT and the version.
FORMAT = "starpost-data"
VERSION = 2

# Row tags (first cell). A row whose first cell isn't one of these is a numeric
# data row belonging to the current head block.
_TAGS = {"meta", "report", "plot", "head"}


def _bool(v: bool) -> str:
    return "true" if v else "false"


def _num_str(v: float) -> str:
    """Compact, round-trippable text for a number: drop the ``.0`` on integral
    values (e.g. iteration counts), otherwise the shortest exact float repr."""
    if math.isfinite(v) and v == int(v):
        return str(int(v))
    return repr(v)


def _group_series(series: list[PlotSeries]) -> list[tuple[list[float], list[PlotSeries]]]:
    """Group series that share an identical X vector so each group can be written
    as one columnar block (shared X stored once). Order is preserved."""
    groups: dict[tuple[float, ...], tuple[list[float], list[PlotSeries]]] = {}
    order: list[tuple[float, ...]] = []
    for s in series:
        key = tuple(s.x)
        if key not in groups:
            groups[key] = (list(s.x), [])
            order.append(key)
        groups[key][1].append(s)
    return [groups[k] for k in order]


def write_sim_csv(result: SimResult, path: Path | str) -> None:
    """Write ``result`` to ``path`` as a portable StarPost data CSV."""
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([FORMAT, VERSION])

        w.writerow(["meta", "sim_path", result.sim_path])
        w.writerow(["meta", "extracted_at", result.extracted_at])
        if result.error:
            w.writerow(["meta", "error", result.error])

        for rep in result.reports:
            w.writerow(
                [
                    "report",
                    rep.name,
                    "" if rep.value is None else _num_str(rep.value),
                    rep.units,
                    rep.error or "",
                ]
            )

        for plot in result.plots:
            w.writerow(
                [
                    "plot",
                    plot.name,
                    plot.kind.value,
                    plot.x_label,
                    _bool(plot.y_log),
                    plot.error or "",
                ]
            )
            for xs, group in _group_series(plot.series):
                # Column header, then one row per X value: X first, then each
                # series' Y in column order.
                w.writerow(["head", plot.x_label] + [s.name for s in group])
                for i, x in enumerate(xs):
                    w.writerow([_num_str(x)] + [_num_str(s.y[i]) for s in group])


def _num(text: str) -> float | None:
    """Parse a report value cell: blank means extraction failed (None)."""
    return float(text) if text != "" else None


def read_sim_csv(path: Path | str) -> SimResult:
    """Reconstruct a SimResult from a portable CSV written by ``write_sim_csv``.

    Raises ValueError if the file isn't a StarPost data export of a supported
    version.
    """
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        try:
            signature = next(reader)
        except StopIteration:
            raise ValueError(f"empty file: {path.name}")
        if not signature or signature[0] != FORMAT:
            raise ValueError(f"not a StarPost data export: {path.name}")
        if len(signature) < 2 or signature[1] != str(VERSION):
            raise ValueError(
                f"unsupported StarPost data version in {path.name}: "
                f"{signature[1:] or ['?']}"
            )

        result = SimResult(sim_path="")
        plot: MonitorPlot | None = None
        block: list[PlotSeries] = []  # series filling the current head block's columns
        for row in reader:
            if not row:
                continue
            tag = row[0]
            if tag == "meta":
                key = row[1]
                val = row[2] if len(row) > 2 else ""
                if key == "sim_path":
                    result.sim_path = val
                elif key == "extracted_at":
                    result.extracted_at = val
                elif key == "error":
                    result.error = val or None
            elif tag == "report":
                result.reports.append(
                    Report(
                        name=row[1],
                        value=_num(row[2]) if len(row) > 2 else None,
                        units=row[3] if len(row) > 3 else "",
                        error=(row[4] if len(row) > 4 else "") or None,
                    )
                )
            elif tag == "plot":
                plot = MonitorPlot(
                    name=row[1],
                    kind=PlotKind(row[2] or "other"),
                    x_label=row[3] or "Iteration",
                    y_log=(len(row) > 4 and row[4] == "true"),
                    error=(row[5] if len(row) > 5 else "") or None,
                )
                result.plots.append(plot)
                block = []
            elif tag == "head":
                # row[1] is the X label (already on the plot); row[2:] name the
                # series filling each subsequent column.
                block = []
                if plot is not None:
                    for sname in row[2:]:
                        s = PlotSeries(name=sname)
                        plot.series.append(s)
                        block.append(s)
            else:
                # A numeric data row for the current head block: X then each Y.
                x = float(tag)
                for i, s in enumerate(block):
                    cell = row[i + 1] if i + 1 < len(row) else ""
                    if cell == "":
                        continue
                    s.x.append(x)
                    s.y.append(float(cell))
        return result
