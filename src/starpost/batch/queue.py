"""Sequential batch worker, designed to run off the GUI thread.

Runs jobs one at a time (license-safe) and emits Qt signals for
progress/log/result. A batch is never killed mid-write: once started, every
file runs to completion.

Usage (from the GUI):
    worker = BatchWorker(jobs, runner, output_dir, store)
    thread = QThread(); worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    # connect worker.log / progress / sim_done to UI slots
    thread.start()
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from starpost.batch.job import Job
from starpost.core.starccm_runner import StarRunner
from starpost.data.models import SimResult
from starpost.data.store import ResultStore


class BatchWorker(QObject):
    log = Signal(str)                 # a line of run output
    progress = Signal(int, int)       # (completed, total)
    sim_done = Signal(object)         # SimResult
    finished = Signal()               # whole batch finished

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

    def run(self) -> None:
        total = len(self._jobs)
        for i, job in enumerate(self._jobs):
            self.log.emit(f"--- [{i + 1}/{total}] {job.name} ---")

            try:
                result: SimResult = self._runner.extract(
                    job.sim_file, self._output_dir, log_sink=self.log.emit
                )
            except Exception as e:  # noqa: BLE001 - surface any failure to the UI
                result = SimResult(sim_path=str(job.sim_file), error=str(e))

            self._store.put(result)
            self._store.save_cache()  # crash-recovery checkpoint after each file

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
    recording = Signal(str)            # a screenplay's record just began (label)
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
        """Log sink for the runner: progress markers from the record macro
        become signals (not log lines); everything else passes through to the
        log. Two markers: per-frame counts (frame-loop path) drive the
        determinate bar, and a per-screenplay 'recording' notice drives the
        busy indicator for the native path, which then renders silently."""
        if line.startswith("starpost-progress: frame "):
            tail = line.rsplit(" ", 1)[-1]  # "X/Y"
            done_s, _, total_s = tail.partition("/")
            try:
                self.frame_progress.emit(int(done_s), int(total_s))
                return
            except ValueError:
                pass  # malformed marker — let it fall through to the log
        elif line.startswith("starpost-progress: recording "):
            self.recording.emit(line[len("starpost-progress: recording "):])
            return
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
