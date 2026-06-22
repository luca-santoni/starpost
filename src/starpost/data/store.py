"""In-memory result store with a JSON crash-recovery cache on disk."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, Optional

from starpost.data.models import (
    MediaArtifact,
    MonitorPlot,
    PlotKind,
    PlotSeries,
    Report,
    SimResult,
)
from starpost.utils.paths import results_cache_path


class ResultStore:
    """Keyed by sim_path. Persisted to JSON so a crash doesn't lose extractions."""

    def __init__(self) -> None:
        self._results: dict[str, SimResult] = {}

    # --- access ----------------------------------------------------------
    def put(self, result: SimResult) -> None:
        self._results[result.sim_path] = result

    def get(self, sim_path: str) -> Optional[SimResult]:
        return self._results.get(sim_path)

    def all(self) -> list[SimResult]:
        return list(self._results.values())

    def remove(self, sim_path: str) -> None:
        self._results.pop(sim_path, None)

    def clear(self) -> None:
        self._results.clear()

    def __iter__(self) -> Iterable[SimResult]:
        return iter(self._results.values())

    # --- homogeneity -----------------------------------------------------
    def is_homogeneous(self) -> bool:
        sigs = {r.signature() for r in self._results.values() if r.error is None}
        return len(sigs) <= 1

    # --- persistence -----------------------------------------------------
    def save_cache(self, path: Optional[Path] = None) -> None:
        path = path or results_cache_path()
        payload = {sp: asdict(r) for sp, r in self._results.items()}
        # No indentation: this is a machine-only crash-recovery file, and the
        # compact form is roughly half the size, so it writes and (re)loads
        # faster on startup. load_cache reads either form.
        path.write_text(json.dumps(payload), encoding="utf-8")

    def load_cache(self, path: Optional[Path] = None) -> None:
        path = path or results_cache_path()
        if not path.exists():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        self._results = {sp: _result_from_dict(d) for sp, d in payload.items()}


def _result_from_dict(d: dict) -> SimResult:
    reports = [Report(**r) for r in d.get("reports", [])]
    plots = []
    for p in d.get("plots", []):
        series = [PlotSeries(**s) for s in p.get("series", [])]
        plots.append(
            MonitorPlot(
                name=p["name"],
                series=series,
                kind=PlotKind(p.get("kind", "other")),
                x_label=p.get("x_label", "Iteration"),
                y_log=p.get("y_log", False),
                error=p.get("error"),
            )
        )
    media = [MediaArtifact(**m) for m in d.get("media", [])]
    return SimResult(
        sim_path=d["sim_path"],
        reports=reports,
        plots=plots,
        scenes=list(d.get("scenes", [])),
        media=media,
        extracted_at=d.get("extracted_at", ""),
        error=d.get("error"),
    )
