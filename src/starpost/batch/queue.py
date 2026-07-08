"""Sequential batch worker, designed to run off the GUI thread.

Runs jobs one at a time (license-safe), emits Qt signals for progress/log/result,
and supports a cooperative "stop after current file" — batch sessions must not be
killed mid-write, so we finish the in-flight file before halting.

Usage (from the GUI):
    worker = BatchWorker(jobs, runner, output_dir, store)
    thread = QThread(); worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    # connect worker.log / progress / sim_done to UI slots
    thread.start()
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from starpost.batch.job import Job, JobState
from starpost.core.starccm_runner import StarRunner
from starpost.data.models import SimResult
from starpost.data.store import ResultStore


class BatchWorker(QObject):
    log = Signal(str)                 # a line of run output
    progress = Signal(int, int)       # (completed, total)
    job_state = Signal(int, str)      # (index, JobState value)
    sim_done = Signal(object)         # SimResult
    finished = Signal()               # whole batch finished/stopped

    def __init__(
        self,
        jobs: list[Job],
        runner: StarRunner,
        output_dir: Path,
        store: ResultStore,
    ) -> None:
        super().__init__()
        self._jobs = jobs
        self._runner = runner
        self._output_dir = output_dir
        self._store = store
        self._stop_requested = False

    def request_stop(self) -> None:
        """Stop *after* the current file completes."""
        self._stop_requested = True
        self.log.emit("Stop requested — will halt after the current file.")

    def run(self) -> None:
        total = len(self._jobs)
        for i, job in enumerate(self._jobs):
            if self._stop_requested:
                job.state = JobState.SKIPPED
                self.job_state.emit(i, JobState.SKIPPED.value)
                continue

            job.state = JobState.RUNNING
            self.job_state.emit(i, JobState.RUNNING.value)
            self.log.emit(f"--- [{i + 1}/{total}] {job.name} ---")

            try:
                result: SimResult = self._runner.extract(
                    job.sim_file, self._output_dir, log_sink=self.log.emit
                )
            except Exception as e:  # noqa: BLE001 - surface any failure to the UI
                result = SimResult(sim_path=str(job.sim_file), error=str(e))

            self._store.put(result)
            self._store.save_cache()  # crash-recovery checkpoint after each file

            if result.error:
                job.state, job.message = JobState.FAILED, result.error
            else:
                job.state = JobState.DONE
            self.job_state.emit(i, job.state.value)
            self.sim_done.emit(result)
            self.progress.emit(i + 1, total)

        self.finished.emit()


class SceneRenderWorker(QObject):
    """Renders scene stills off the GUI thread, one .sim per STAR-CCM+ process.

    Each job is a (sim_file, scene_show) pair, where scene_show maps each scene to
    render to the displayers to keep visible; all of a job's scenes are rendered
    in a single starccm+ invocation — one license checkout, with the sim loaded
    once. Runs sequentially (license-safe) and emits the rendered artifacts per
    file so the UI can attach them to results.
    """

    log = Signal(str)                 # a line of render output
    progress = Signal(int, int)       # (completed, total)
    rendered = Signal(object, object)  # (sim_path: str, list[MediaArtifact])
    finished = Signal()

    def __init__(
        self,
        jobs: list[tuple[Path, dict[str, list[str]]]],
        runner: StarRunner,
        output_dir: Path,
        views: Optional[list[str]] = None,
    ) -> None:
        super().__init__()
        self._jobs = jobs
        self._runner = runner
        self._output_dir = output_dir
        self._views = list(views or [])

    def run(self) -> None:
        total = len(self._jobs)
        for i, (sim_file, scene_show) in enumerate(self._jobs):
            self.log.emit(f"--- [{i + 1}/{total}] rendering {sim_file.name} ---")
            try:
                artifacts = self._runner.render_scenes(
                    sim_file, self._output_dir, scene_show, self._views,
                    log_sink=self.log.emit,
                )
                self.rendered.emit(str(sim_file), artifacts)
            except Exception as e:  # noqa: BLE001 - surface any failure to the UI
                self.log.emit(f"Render failed for {sim_file.name}: {e}")
            self.progress.emit(i + 1, total)
        self.finished.emit()


# STAR-CCM+'s native record() reports frame progress to its GUI
# ProgressPresenter (absent under -batch), but it also echoes frame/percentage
# text to the process log. These patterns lift a (done, total) pair out of that
# text so the fast native path — which never runs our own frame-loop markers —
# still advances the bar. The frame form ("...frame 100 of 330", "frame 100/330")
# is preferred; a bare percentage counts only on a movie/animation line.
_NATIVE_FRAME_RE = re.compile(r"frame\s+(\d+)\s*(?:of|/)\s*(\d+)", re.IGNORECASE)
_NATIVE_PCT_RE = re.compile(r"(?<!\d)(\d{1,3})\s*%")
_PCT_CONTEXT = ("frame", "animation", "movie", "hardcopy", "encod")


def _parse_native_progress(line: str) -> Optional[tuple[int, int]]:
    """Pull a (done, total) frame pair from STAR's own native record output, or
    None if the line carries no recognisable movie progress. Handles an explicit
    frame count ("...frame 100 of 330", "frame 100/330") and a bare percentage on
    a movie/animation line ("Writing animation: 45%")."""
    m = _NATIVE_FRAME_RE.search(line)
    if m:
        done, total = int(m.group(1)), int(m.group(2))
        if total > 0 and 0 <= done <= total:
            return done, total
    low = line.lower()
    if any(k in low for k in _PCT_CONTEXT):
        m = _NATIVE_PCT_RE.search(line)
        if m:
            pct = int(m.group(1))
            if 0 <= pct <= 100:
                return pct, 100
    return None


class ScreenplayRecordWorker(QObject):
    """Records screenplay movies off the GUI thread, one .sim per STAR-CCM+
    process. Each job is a (sim_file, screenplay_show) pair, where
    screenplay_show maps each screenplay to record to the displayers to keep
    visible; all of a job's screenplays are recorded in a single starccm+
    invocation — one license checkout, the sim loaded once. Runs sequentially
    (license-safe) and emits the recorded artifacts per file so the UI can
    attach them to results. Mirrors SceneRenderWorker.
    """

    log = Signal(str)                  # a line of record output
    progress = Signal(int, int)        # (completed, total)
    frame_progress = Signal(int, int)  # (frame, frames) within the current job
    recorded = Signal(object, object)  # (sim_path: str, list[MediaArtifact])
    finished = Signal()

    def __init__(
        self,
        jobs: list[tuple[Path, dict[str, list[str]]]],
        runner: StarRunner,
        output_dir: Path,
        views: Optional[list[str]] = None,
    ) -> None:
        super().__init__()
        self._jobs = jobs
        self._runner = runner
        self._output_dir = output_dir
        self._views = list(views or [])

    def _sink(self, line: str) -> None:
        """Log sink for the runner. Two progress sources feed the bar. Our own
        frame-loop markers ("starpost-progress: frame X/Y") become frame_progress
        signals and are hidden from the visible log. STAR's native record()
        progress text (the fast native path, where our markers never fire) is
        recognised too, but — being genuine STAR output — is kept in the log."""
        if line.startswith("starpost-progress: frame "):
            tail = line.rsplit(" ", 1)[-1]  # "X/Y"
            done_s, _, total_s = tail.partition("/")
            try:
                self.frame_progress.emit(int(done_s), int(total_s))
                return
            except ValueError:
                pass  # malformed marker — let it fall through to the log
        else:
            native = _parse_native_progress(line)
            if native is not None:
                self.frame_progress.emit(*native)
        self.log.emit(line)

    def run(self) -> None:
        total = len(self._jobs)
        for i, (sim_file, screenplay_show) in enumerate(self._jobs):
            self.log.emit(f"--- [{i + 1}/{total}] recording {sim_file.name} ---")
            try:
                artifacts = self._runner.record_screenplays(
                    sim_file, self._output_dir, screenplay_show, self._views,
                    log_sink=self._sink,
                )
                self.recorded.emit(str(sim_file), artifacts)
            except Exception as e:  # noqa: BLE001 - surface any failure to UI
                self.log.emit(f"Recording failed for {sim_file.name}: {e}")
            self.progress.emit(i + 1, total)
        self.finished.emit()
