"""In-memory result store with a JSON crash-recovery cache on disk."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, Optional

from starpost.data.models import (
    Displayer,
    MediaArtifact,
    MonitorPlot,
    PlotKind,
    PlotSeries,
    PropertyGroup,
    Report,
    Scene,
    Screenplay,
    SimProperties,
    SimResult,
)
from starpost.utils.paths import results_cache_path


class ResultStore:
    """Keyed by sim_path. Persisted to JSON so a crash doesn't lose extractions."""

    def __init__(self) -> None:
        self._results: dict[str, SimResult] = {}
        # Cache writes: one writer at a time, and a generation counter so an
        # older in-flight async save never overwrites a newer one's file.
        self._save_lock = threading.Lock()
        self._save_gen = 0

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
    def _snapshot(self) -> tuple[dict, int]:
        """A JSON-ready snapshot of the store plus its save generation.

        The snapshot's dicts are freshly built, so later store changes can't
        reach it; the plot x/y lists are shared by reference (copying every
        point is what made ``dataclasses.asdict`` ~15x slower) — safe because a
        series' data is immutable once extracted."""
        payload = {sp: _result_to_dict(r) for sp, r in self._results.items()}
        with self._save_lock:
            self._save_gen += 1
            return payload, self._save_gen

    def _write_cache(self, payload: dict, path: Path, gen: int) -> None:
        with self._save_lock:
            if gen < self._save_gen:
                return  # a newer save exists/is queued; don't write stale state
            # Streamed via iterencode, not json.dumps: the C serializer holds
            # the GIL for its whole run (~130 ms for a large workspace), which
            # stalls the GUI even from a background thread; the streaming
            # encoder yields between chunks, capping stalls at ~10 ms. Compact
            # separators: this is a machine-only crash-recovery file, and the
            # compact form is smaller, so it writes and (re)loads faster.
            # load_cache reads any JSON form.
            encoder = json.JSONEncoder(separators=(",", ":"))
            # Write to a temp file in the same directory, then atomically replace
            # the target, so a reader (e.g. a quickly relaunched app reading the
            # cache while a background save from the closing app is still writing)
            # never sees a half-written file.
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
            )
            tmp = Path(tmp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    for chunk in encoder.iterencode(payload):
                        fh.write(chunk)
                os.replace(tmp, path)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise

    def save_cache(self, path: Optional[Path] = None) -> None:
        path = path or results_cache_path()
        payload, gen = self._snapshot()
        self._write_cache(payload, path, gen)

    def save_cache_async(self, path: Optional[Path] = None) -> threading.Thread:
        """save_cache with the serialize + write (a few hundred ms for a large
        workspace) on a background thread, for GUI-thread callers that must not
        freeze. The snapshot is taken synchronously, so the file reflects the
        store as of this call; the write lock keeps concurrent saves (e.g. the
        batch worker's synchronous checkpoints) from interleaving. Returns the
        started (non-daemon, so never killed mid-write) thread."""
        path = path or results_cache_path()
        payload, gen = self._snapshot()
        thread = threading.Thread(
            target=self._write_cache, args=(payload, path, gen),
            name="starpost-cache-save",
        )
        thread.start()
        return thread

    def load_cache(self, path: Optional[Path] = None) -> None:
        path = path or results_cache_path()
        if not path.exists():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        self._results = {sp: _result_from_dict(d) for sp, d in payload.items()}


def _result_to_dict(r: SimResult) -> dict:
    """``asdict(r)``, but with the plot series built by hand: asdict deep-copies
    every x/y point, which dominates the save cost, while json.dumps only needs
    to read them. The small fixed-size parts still use asdict, so new fields on
    those dataclasses keep round-tripping without touching this. The output is
    identical to asdict's (see the store tests)."""
    return {
        "sim_path": r.sim_path,
        "reports": [asdict(rep) for rep in r.reports],
        "plots": [
            {
                "name": p.name,
                "series": [{"name": s.name, "x": s.x, "y": s.y} for s in p.series],
                "kind": p.kind.value,
                "x_label": p.x_label,
                "y_log": p.y_log,
                "error": p.error,
            }
            for p in r.plots
        ],
        "scenes": [asdict(sc) for sc in r.scenes],
        "views": list(r.views),
        "screenplays": [asdict(sp) for sp in r.screenplays],
        "media": [asdict(m) for m in r.media],
        "properties": asdict(r.properties) if r.properties is not None else None,
        "extracted_at": r.extracted_at,
        "error": r.error,
    }


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
    scenes = [_scene_from_dict(s) for s in d.get("scenes", [])]
    screenplays = [_screenplay_from_dict(s) for s in d.get("screenplays", [])]
    return SimResult(
        sim_path=d["sim_path"],
        reports=reports,
        plots=plots,
        scenes=scenes,
        views=list(d.get("views", [])),
        screenplays=screenplays,
        media=media,
        properties=_properties_from_dict(d.get("properties")),
        extracted_at=d.get("extracted_at", ""),
        error=d.get("error"),
    )


def _properties_from_dict(d) -> Optional[SimProperties]:
    """Rebuild SimProperties from its asdict form; JSON stores the (key, value)
    entry tuples as lists. None/absent (pre-properties caches) stays None."""
    if not d:
        return None
    return SimProperties(
        groups=[
            PropertyGroup(
                section=g["section"],
                name=g.get("name", ""),
                entries=[(k, v) for k, v in g.get("entries", [])],
            )
            for g in d.get("groups", [])
        ]
    )


def _scene_from_dict(s) -> Scene:
    # Back-compat: caches written before displayers stored scenes as plain names.
    if isinstance(s, str):
        return Scene(name=s)
    return Scene(
        name=s["name"],
        displayers=[Displayer(**d) for d in s.get("displayers", [])],
    )


def _screenplay_from_dict(s: dict) -> Screenplay:
    return Screenplay(
        name=s["name"],
        scene=s.get("scene", ""),
        displayers=[Displayer(**d) for d in s.get("displayers", [])],
    )
