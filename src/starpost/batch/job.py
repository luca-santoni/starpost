"""A single extraction job: one .sim -> one SimResult."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class JobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Job:
    sim_file: Path
    state: JobState = JobState.PENDING
    message: str = ""

    @property
    def name(self) -> str:
        return self.sim_file.name
