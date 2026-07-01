"""Run a configured batch export.

For each selected data set / .sim the batch produces, into a folder named after
that data set: the selected report table, an image of each saved plot, and the
saved-scene stills. All the per-data-set folders are then packed into a single
``.zip`` written to the user's output folder.

Plots are rendered with a real :class:`PlotView`, so this runs on the GUI thread
(Qt widgets can't be created off it). Extraction and scene rendering shell out to
STAR-CCM+ via the injected :class:`StarRunner`.
"""
from __future__ import annotations

import dataclasses
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from starpost.batch.aggregator import reports_long_frame, write_report_table
from starpost.core.starccm_runner import StarRunner
from starpost.data.models import SimResult
from starpost.gui.views.plot_view import PlotView

LogSink = Callable[[str], None]
Progress = Callable[[float, str], None]  # (fraction 0..1, current-action message)

_FORBIDDEN = '/\\:*?"<>|'


def _safe_name(name: str) -> str:
    """A filesystem-safe folder/file name (path separators etc. replaced)."""
    cleaned = "".join("_" if c in _FORBIDDEN else c for c in (name or "")).strip()
    return cleaned or "item"


@dataclass
class BatchSource:
    """One data set / .sim to process. ``result`` is its already-extracted data
    (loaded data sets); when None, ``sim_file`` is extracted first. ``sim_file``
    is also the .sim that scene rendering needs (None == no scenes)."""
    name: str
    result: Optional[SimResult] = None
    sim_file: Optional[Path] = None


@dataclass
class BatchConfig:
    """Everything the run needs beyond the sources: which reports to write (and
    how), and the saved plots / scenes (each ``{"name", "data"}``)."""
    sources: list[BatchSource]
    reports: set[str] = field(default_factory=set)
    report_format: str = "csv"          # csv | tsv | xlsx | ods
    include_units: bool = True
    saved_plots: list[dict] = field(default_factory=list)
    saved_scenes: list[dict] = field(default_factory=list)


def _plot_size(plot_data: dict, default=(1280, 720)) -> tuple[int, int]:
    """The export size for a plot, honouring its captured aspect ratio (keeping
    the default width); "Custom"/blank keeps the default size."""
    w, h = default
    aspect = plot_data.get("aspect") or ""
    if ":" in aspect:
        try:
            aw, ah = (int(x) for x in aspect.split(":"))
            if aw > 0 and ah > 0:
                return w, max(1, round(w * ah / aw))
        except ValueError:
            pass
    return w, h


def render_saved_plot(result: SimResult, plot_data: dict, settings, path) -> bool:
    """Render one saved plot for ``result`` to ``path`` in its captured image
    format. Returns False (writing nothing) when none of the plot's monitor
    groups exist in this result, or nothing ends up drawn."""
    monitors = plot_data.get("monitors") or {}
    plots = [p for p in result.plots if p.name in set(monitors)]
    if not plots:
        return False

    view = PlotView()
    view.set_category_controls_visible(False)
    if settings is not None:
        view.set_filter(settings.hide_empty_monitors, settings.monitor_zero_threshold)
        view.set_region_stats(settings.region_stats)
    view.apply_theme(plot_data.get("theme") or "light")
    view.show_plots(plots)
    view.set_monitor_selection(monitors)
    view.set_color_overrides(
        plot_data.get("series_colors") or {}, plot_data.get("pair_colors") or {}
    )
    view.set_title_override(plot_data.get("title", ""))
    view.set_x_label_override(plot_data.get("x_label", ""))
    view.set_y_label_override(plot_data.get("y_label", ""))
    view.set_grid_visible(bool(plot_data.get("grid", True)))
    for key, setter in (
        ("legend_scale", view.set_legend_scale),
        ("line_width", view.set_line_width),
        ("title_size", view.set_title_size),
        ("axis_label_size", view.set_axis_label_size),
    ):
        if plot_data.get(key) is not None:
            setter(plot_data[key])
    view.resize(*_plot_size(plot_data))
    try:
        if not view.has_content():
            return False
        view.export(str(path), (plot_data.get("format") or "png").lower())
    finally:
        view.deleteLater()
    return True


def _scene_runner(settings, scene_data: dict, base: StarRunner) -> StarRunner:
    """A runner whose media settings use the saved scene's resolution/format, so
    each scene renders at the size/type it was saved with."""
    res = scene_data.get("resolution")
    fmt = scene_data.get("format")
    if settings is None or (not res and not fmt):
        return base
    media = dataclasses.replace(
        settings.media,
        image_resolution=res or settings.media.image_resolution,
        image_format=fmt or settings.media.image_format,
    )
    return StarRunner(dataclasses.replace(settings, media=media))


def _zip_dir(src_dir: Path, dest_zip: Path) -> None:
    """Zip every file under ``src_dir`` into ``dest_zip`` (paths relative to
    ``src_dir``, so the archive's top level is the per-data-set folders)."""
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(src_dir.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(src_dir).as_posix())


def _source_steps(config: BatchConfig, source: BatchSource) -> int:
    """How many progress steps a source contributes: an extraction (for a .sim),
    the report table, one per saved plot, and one per saved scene (when the source
    can render scenes)."""
    n = 0
    if source.result is None and source.sim_file is not None:
        n += 1
    if config.reports:
        n += 1
    n += len(config.saved_plots)
    if source.sim_file is not None:
        n += len(config.saved_scenes)
    return n


class _Steps:
    """Tracks completed steps out of a known total and reports a 0..1 fraction
    plus a message for the current action to a progress callback."""

    def __init__(self, total: int, progress: Optional[Progress]) -> None:
        self.total = max(total, 1)
        self.done = 0
        self._progress = progress

    def at(self, message: str) -> None:
        """Announce the action about to run, at the fraction done so far."""
        if self._progress:
            self._progress(self.done / self.total, message)

    def advance(self, n: int = 1) -> None:
        self.done += n

    def finish(self, message: str) -> None:
        self.done = self.total
        if self._progress:
            self._progress(1.0, message)


def build_batch_archive(
    config: BatchConfig,
    settings,
    runner: StarRunner,
    dest_zip: Path,
    *,
    log: Optional[LogSink] = None,
    progress: Optional[Progress] = None,
    plot_renderer: Optional[Callable[[SimResult, dict, Path], bool]] = None,
) -> Path:
    """Produce ``dest_zip`` from ``config``: one folder per data set holding its
    reports, saved-plot images and saved-scene stills. Reports a 0..1 fraction and
    the current action to ``progress``. Returns ``dest_zip``.

    When run off the GUI thread, ``plot_renderer`` renders a saved plot on the GUI
    thread instead (Qt widgets can't be built off it); by default plots render on
    the calling thread."""
    log = log or (lambda _s: None)
    render_plot = plot_renderer or (
        lambda result, pdata, path: render_saved_plot(result, pdata, settings, path)
    )
    dest_zip = Path(dest_zip)
    steps = _Steps(
        sum(_source_steps(config, s) for s in config.sources) + 1,  # +1 = packaging
        progress,
    )
    total = len(config.sources)
    with tempfile.TemporaryDirectory(prefix="starpost_batch_") as tmp:
        out_root = Path(tmp) / "out"     # this gets zipped
        work_root = Path(tmp) / "work"   # extraction scratch, not zipped
        for i, source in enumerate(config.sources):
            log(f"--- {source.name} ({i + 1}/{total}) ---")
            planned = _source_steps(config, source)
            done_before = steps.done
            folder = out_root / _safe_name(source.name)
            folder.mkdir(parents=True, exist_ok=True)

            result = source.result
            if result is None and source.sim_file is not None:
                steps.at(f"Opening {source.name}…")
                result = runner.extract(
                    source.sim_file, work_root / _safe_name(source.name), log_sink=log
                )
                steps.advance()
            if result is None or result.error:
                log(f"Skipping {source.name}: "
                    f"{result.error if result else 'no data'}")
                steps.advance(planned - (steps.done - done_before))  # skip the rest
                continue

            if config.reports:
                steps.at(f"Writing reports for {source.name}…")
                df = reports_long_frame(
                    result, config.reports, config.include_units
                )
                rpath = folder / f"reports.{config.report_format.lower()}"
                write_report_table(df, rpath, config.report_format)
                log(f"  reports -> {rpath.name}")
                steps.advance()

            for entry in config.saved_plots:
                name = entry.get("name", "plot")
                steps.at(f"Rendering plot “{name}” for {source.name}…")
                pdata = entry.get("data") or {}
                fmt = (pdata.get("format") or "png").lower()
                ppath = folder / f"{_safe_name(name)}.{fmt}"
                if render_plot(result, pdata, ppath):
                    log(f"  plot -> {ppath.name}")
                steps.advance()

            if source.sim_file is not None:
                for entry in config.saved_scenes:
                    name = entry.get("name", "scene")
                    steps.at(f"Rendering scene “{name}” for {source.name}…")
                    sdata = entry.get("data") or {}
                    show = sdata.get("displayers") or {}
                    if show:
                        _scene_runner(settings, sdata, runner).render_scenes(
                            source.sim_file, folder, show,
                            sdata.get("views") or [], log_sink=log,
                        )
                    steps.advance()

        steps.at("Packaging archive…")
        _zip_dir(out_root, dest_zip)
        steps.finish("Done")
    log(f"Wrote {dest_zip}")
    return dest_zip
