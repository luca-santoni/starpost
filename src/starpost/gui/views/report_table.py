"""Numeric report viewer. Per-file long view and comparison wide view."""
from __future__ import annotations

import numbers

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, Qt
from PySide6.QtWidgets import QTableView, QVBoxLayout, QWidget

from starpost.data.models import SimResult


class _DataFrameModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame, decimals: int = 4) -> None:
        super().__init__()
        self._df = df
        self._decimals = decimals

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
            return f"{float(val):.{self._decimals}f}"
        return str(val)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return str(self._df.columns[section])
        return str(self._df.index[section])


class ReportTable(QWidget):
    def __init__(self, decimals: int = 4, parent=None) -> None:
        super().__init__(parent)
        self._table = QTableView()
        self._decimals = decimals
        self._df: pd.DataFrame | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(self._table)

    def set_decimals(self, decimals: int) -> None:
        """Update the displayed precision and re-render the current table."""
        self._decimals = max(0, int(decimals))
        if self._df is not None:
            self.show_dataframe(self._df)

    def show_dataframe(self, df: pd.DataFrame) -> None:
        self._df = df
        self._table.setModel(_DataFrameModel(df, self._decimals))
        self._table.resizeColumnsToContents()

    def show_single(self, result: SimResult) -> None:
        df = pd.DataFrame(
            [{"report": r.name, "value": r.value, "units": r.units} for r in result.reports]
        )
        self.show_dataframe(df)
