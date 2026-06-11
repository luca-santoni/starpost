"""Aggregate per-sim results into comparison-friendly tables and exports.

Report comparison CSV is wide: one row per sim, one column per report, with
units embedded in the header (e.g. "Drag Force [N]").
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from starpost.data.models import SimResult


def reports_wide_frame(
    results: list[SimResult], selected: Optional[set[str]] = None
) -> pd.DataFrame:
    """Wide report table: rows = sims, columns = "Report [units]"."""
    units: dict[str, str] = {}
    rows: list[dict] = []
    for res in results:
        row: dict[str, object] = {"sim": res.sim_name}
        for rep in res.reports:
            if selected is not None and rep.name not in selected:
                continue
            units.setdefault(rep.name, rep.units)
            row[rep.name] = rep.value
        rows.append(row)

    df = pd.DataFrame(rows).set_index("sim") if rows else pd.DataFrame()
    # Embed units in headers.
    df = df.rename(
        columns={
            name: f"{name} [{units[name]}]" if units.get(name) else name
            for name in df.columns
        }
    )
    return df


def export_reports_csv(
    results: list[SimResult], path: Path, selected: Optional[set[str]] = None
) -> None:
    reports_wide_frame(results, selected).to_csv(path)


def export_single_sim_reports_csv(res: SimResult, path: Path) -> None:
    """Per-file long CSV: report, value, units."""
    df = pd.DataFrame(
        [{"report": r.name, "value": r.value, "units": r.units} for r in res.reports]
    )
    df.to_csv(path, index=False)
