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
    results: list[SimResult],
    selected: Optional[set[str]] = None,
    include_units: bool = True,
) -> pd.DataFrame:
    """Wide report table: rows = sims, columns = "Report [units]" (units embedded
    only when ``include_units``)."""
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
    if include_units:
        df = df.rename(
            columns={
                name: f"{name} [{units[name]}]" if units.get(name) else name
                for name in df.columns
            }
        )
    return df


def write_report_table(df: pd.DataFrame, path: Path, fmt: str) -> None:
    """Write a report table to ``path`` in ``fmt`` (csv | tsv | xlsx | ods)."""
    fmt = fmt.lower()
    if fmt == "csv":
        df.to_csv(path, index=False)
    elif fmt == "tsv":
        df.to_csv(path, sep="\t", index=False)
    elif fmt == "xlsx":
        df.to_excel(path, index=False, engine="openpyxl")
    elif fmt == "ods":
        df.to_excel(path, index=False, engine="odf")
    else:
        raise ValueError(f"Unsupported export format: {fmt}")
