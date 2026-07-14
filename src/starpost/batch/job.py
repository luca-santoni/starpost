"""A single extraction job: one .sim -> one SimResult."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Job:
    sim_file: Path

    @property
    def name(self) -> str:
        return self.sim_file.name
