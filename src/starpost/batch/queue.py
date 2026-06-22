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

from pathlib import Path

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
    """Renders scene stills for one or more .sim files, off the GUI thread.

    Independent of the numeric BatchWorker: each job is a (sim_file, scene_names)
    pair (empty scene_names == every scene). Runs sequentially (license-safe) and
    emits the rendered artifacts per file so the UI can attach them to results.
    """

    log = Signal(str)                 # a line of render output
    progress = Signal(int, int)       # (completed, total)
    rendered = Signal(object, object)  # (sim_path: str, list[MediaArtifact])
    finished = Signal()

    def __init__(
        self,
        jobs: list[tuple[Path, list[str]]],
        runner: StarRunner,
        output_dir: Path,
    ) -> None:
        super().__init__()
        self._jobs = jobs
        self._runner = runner
        self._output_dir = output_dir

    def run(self) -> None:
        total = len(self._jobs)
        for i, (sim_file, scene_names) in enumerate(self._jobs):
            self.log.emit(f"--- [{i + 1}/{total}] rendering {sim_file.name} ---")
            try:
                artifacts = self._runner.render_scenes(
                    sim_file, self._output_dir, scene_names, log_sink=self.log.emit
                )
                self.rendered.emit(str(sim_file), artifacts)
            except Exception as e:  # noqa: BLE001 - surface any failure to the UI
                self.log.emit(f"Render failed for {sim_file.name}: {e}")
            self.progress.emit(i + 1, total)
        self.finished.emit()
