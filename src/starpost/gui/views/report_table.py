"""Numeric report viewer. Per-file long view and comparison wide view."""
from __future__ import annotations

import numbers

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, Qt
from PySide6.QtWidgets import QMenu, QTableView, QVBoxLayout, QWidget

from starpost.data.models import SimResult

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
        if pd.isna(val):
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
        return str(self._df.index[section])


class ReportTable(QWidget):
    def __init__(
        self, decimals: int = 4, zero_threshold: float = 1e-5, parent=None
    ) -> None:
        super().__init__(parent)
        self._table = QTableView()
        self._decimals = decimals
        self._zero_threshold = zero_threshold
        self._df: pd.DataFrame | None = None
        self._sort: tuple[str, bool] | None = None  # (column, ascending)

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
        self._table.setModel(
            _DataFrameModel(self._sorted(df), self._decimals, self._zero_threshold)
        )
        self._table.resizeColumnsToContents()

    # --- sorting (per-file view) ----------------------------------------
    def _sorted(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the active sort, if the column exists (per-file view only)."""
        if self._sort is None:
            return df
        column, ascending = self._sort
        if column not in df.columns:
            return df  # e.g. comparison wide view has no report/value/units columns
        # Names/units sort case-insensitively; values sort numerically.
        key = (lambda s: s.str.lower()) if column in ("report", "units") else None
        return df.sort_values(
            by=column, ascending=ascending, kind="stable", key=key, na_position="last"
        ).reset_index(drop=True)

    def set_sort(self, column: str, ascending: bool) -> None:
        """Set the active sort and re-render the current table."""
        self._sort = (column, ascending)
        if self._df is not None:
            self.show_dataframe(self._df)

    def _show_header_menu(self, pos) -> None:
        # Sorting applies to the per-file report view (report/value/units).
        if self._df is None or not _SINGLE_COLUMNS.issubset(self._df.columns):
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
        self.show_dataframe(df)
