"""Numeric report viewer. Per-file long view and comparison wide view."""
from __future__ import annotations

import numbers

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, Qt
from PySide6.QtWidgets import QTableView, QVBoxLayout, QWidget

from starpost.data.models import SimResult


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
        self._df = df
        self._table.setModel(
            _DataFrameModel(df, self._decimals, self._zero_threshold)
        )
        self._table.resizeColumnsToContents()

    def show_single(self, result: SimResult, hide_zero: bool = False) -> None:
        reports = result.reports
        if hide_zero:
            # Hide reports at/below the zero threshold (errored/None values stay).
            reports = [
                r for r in reports
                if r.value is None or abs(r.value) >= self._zero_threshold
            ]
        df = pd.DataFrame(
            [{"report": r.name, "value": r.value, "units": r.units} for r in reports]
        )
        self.show_dataframe(df)
