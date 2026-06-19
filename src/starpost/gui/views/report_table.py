"""Numeric report viewer. Per-file long view and comparison wide view."""
from __future__ import annotations

import math
import numbers
import re
from typing import TYPE_CHECKING

from PySide6.QtCore import QAbstractTableModel, Qt
from PySide6.QtWidgets import QMenu, QTableView, QVBoxLayout, QWidget

from starpost.data.models import SimResult

# pandas is imported lazily (only where a DataFrame is actually built/queried) so
# it stays off the startup path — it's a heavy import (~175 ms) and the report
# table does no work until a data set is selected. Type hints below are strings
# (see ``from __future__ import annotations``); this import is for type checkers
# only and never runs at import time.
if TYPE_CHECKING:
    import pandas as pd

# Per-file report columns and the sort options offered on the header menu:
# (label, column, ascending).
_SORT_OPTIONS = [
    ("Name (A–Z)", "report", True),
    ("Name (Z–A)", "report", False),
    ("Value (ascending)", "value", True),
    ("Value (descending)", "value", False),
    ("Units (A–Z)", "units", True),
    ("Units (Z–A)", "units", False),
]
_SINGLE_COLUMNS = {"report", "value", "units"}

# Comparison-view row labels embed units as "Name [unit]" (see reports_wide_frame).
_LABEL_RE = re.compile(r"^(.*?)\s*\[([^\]]*)\]\s*$")


def _split_label(label: str) -> tuple[str, str]:
    """Split a "Name [unit]" comparison row label into (name, unit)."""
    m = _LABEL_RE.match(str(label))
    return (m.group(1), m.group(2)) if m else (str(label), "")


class _DataFrameModel(QAbstractTableModel):
    def __init__(
        self, df: pd.DataFrame, decimals: int = 4, zero_threshold: float = 1e-5
    ) -> None:
        super().__init__()
        self._df = df
        self._decimals = decimals
        self._zero_threshold = zero_threshold

    def rowCount(self, parent=None) -> int:
        return len(self._df.index)

    def columnCount(self, parent=None) -> int:
        return len(self._df.columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        val = self._df.iat[index.row(), index.column()]
        # Empty cell for missing values (None or a float NaN, incl. numpy's),
        # without needing pandas here — this runs once per visible cell.
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return ""
        # Format real (non-integer) numbers to the configured precision.
        if isinstance(val, numbers.Real) and not isinstance(val, (bool, numbers.Integral)):
            fval = float(val)
            if abs(fval) < self._zero_threshold:  # round sub-threshold down to 0
                fval = 0.0
            return f"{fval:.{self._decimals}f}"
        return str(val)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return str(self._df.columns[section])
        # Row numbers down the side, 1-based (the report name itself is a
        # column, so the index is purely positional numbering).
        return str(section + 1)


class ReportTable(QWidget):
    def __init__(
        self, decimals: int = 4, zero_threshold: float = 1e-5, parent=None
    ) -> None:
        super().__init__(parent)
        self._table = QTableView()
        self._decimals = decimals
        self._zero_threshold = zero_threshold
        self._df: pd.DataFrame | None = None
        # Default to sorting report names A–Z; (column, ascending).
        self._sort: tuple[str, bool] | None = ("report", True)
        # Single-file view header for the value column: the data set's name
        # (set by show_single). Falls back to "Value" until a result is shown.
        self._value_label = "Value"

        header = self._table.horizontalHeader()
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_header_menu)

        layout = QVBoxLayout(self)
        layout.addWidget(self._table)

    def set_decimals(self, decimals: int) -> None:
        """Update the displayed precision and re-render the current table."""
        self._decimals = max(0, int(decimals))
        if self._df is not None:
            self.show_dataframe(self._df)

    def set_zero_threshold(self, threshold: float) -> None:
        """Update the round-to-zero threshold and re-render the current table."""
        self._zero_threshold = max(0.0, float(threshold))
        if self._df is not None:
            self.show_dataframe(self._df)

    def clear(self) -> None:
        """Blank the table — used when all loaded data is cleared."""
        self._df = None
        self._table.setModel(None)

    def show_dataframe(self, df: pd.DataFrame) -> None:
        # Keep the source frame; display a sorted view if a sort is active.
        self._df = df
        display = self._sorted(df)
        if _SINGLE_COLUMNS.issubset(df.columns):
            # Single-file view: capitalise the headers and label the value
            # column with the data set's name (the canonical lowercase columns
            # are kept on self._df so sorting still works).
            display = display.rename(
                columns={
                    "report": "Report",
                    "value": self._value_label,
                    "units": "Units",
                }
            )
        else:
            # Comparison view: the report names live in the index (as
            # "Name [unit]"), which Qt renders in the grey vertical header and
            # replaces the row numbers. Lift them into regular leading columns
            # — name and units split apart — so they show on the normal dark
            # data background, units get their own column (matching the
            # single-file view), and the side keeps its row numbers via the
            # default integer index.
            display = display.reset_index()
            label_col = display.columns[0]
            split = [_split_label(lbl) for lbl in display[label_col]]
            display = display.drop(columns=[label_col])
            display.insert(0, "Report", [name for name, _ in split])
            # Units sit in the right-most column (after every sim's values),
            # matching the single-file view.
            display["Units"] = [unit for _, unit in split]
        self._table.setModel(
            _DataFrameModel(display, self._decimals, self._zero_threshold)
        )
        self._table.resizeColumnsToContents()

    # --- sorting ---------------------------------------------------------
    def _sorted(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the active sort to either layout (per-file long or comparison)."""
        if self._sort is None:
            return df
        key, ascending = self._sort
        if _SINGLE_COLUMNS.issubset(df.columns):
            return self._sorted_single(df, key, ascending)
        return self._sorted_comparison(df, key, ascending)

    def _sorted_single(self, df: pd.DataFrame, key: str, ascending: bool) -> pd.DataFrame:
        """Per-file long view: sort rows by the report/value/units column."""
        # Names/units sort case-insensitively; values sort numerically.
        keyfn = (lambda s: s.str.lower()) if key in ("report", "units") else None
        return df.sort_values(
            by=key, ascending=ascending, kind="stable", key=keyfn, na_position="last"
        ).reset_index(drop=True)

    def _sorted_comparison(
        self, df: pd.DataFrame, key: str, ascending: bool
    ) -> pd.DataFrame:
        """Comparison view: rows are reports ("Name [unit]"), columns are sims."""
        import pandas as pd

        if df.empty:
            return df
        if key == "value":
            # No single value per report across sims, so order by the row mean.
            order = df.apply(pd.to_numeric, errors="coerce").mean(axis=1)
            ordered = order.sort_values(ascending=ascending, na_position="last").index
        else:
            part = 0 if key == "report" else 1  # name vs unit from the label
            ordered = sorted(
                df.index,
                key=lambda lbl: _split_label(lbl)[part].lower(),
                reverse=not ascending,
            )
        return df.loc[ordered]

    def set_sort(self, column: str, ascending: bool) -> None:
        """Set the active sort and re-render the current table."""
        self._sort = (column, ascending)
        if self._df is not None:
            self.show_dataframe(self._df)

    def _show_header_menu(self, pos) -> None:
        # Available in both views: per-file sorts by column, comparison sorts
        # the report rows (name/unit from the label, value by row mean).
        if self._df is None:
            return
        menu = QMenu(self)
        actions = {}
        for label, column, ascending in _SORT_OPTIONS:
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(self._sort == (column, ascending))  # tick the active sort
            actions[act] = (column, ascending)
        chosen = menu.exec(self._table.horizontalHeader().mapToGlobal(pos))
        if chosen in actions:
            self.set_sort(*actions[chosen])

    def show_single(
        self, result: SimResult, hide_zero: bool = False, selected: set[str] | None = None
    ) -> None:
        import pandas as pd

        reports = result.reports
        if selected is not None:
            # Honour the selection panel: only show checked reports.
            reports = [r for r in reports if r.name in selected]
        if hide_zero:
            # Hide reports at/below the zero threshold (errored/None values stay).
            reports = [
                r for r in reports
                if r.value is None or abs(r.value) >= self._zero_threshold
            ]
        # Pin the columns so an empty result is a 0-row table (with headers)
        # rather than a column-less frame the table model can't query.
        df = pd.DataFrame(
            [{"report": r.name, "value": r.value, "units": r.units} for r in reports],
            columns=["report", "value", "units"],
        )
        # Label the value column with this data set's name in the display.
        self._value_label = result.sim_name
        self.show_dataframe(df)
