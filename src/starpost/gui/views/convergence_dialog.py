"""'Convergence' window: does this simulation look converged, and if not, why?

Reads cached monitor histories only — it never re-runs STAR-CCM+. Every loaded
data set is assessed independently and summarised in one table; selecting a row
drives the verdict card, the reasons list, and the detail tables.

The window deliberately never shows a bare percentage. The headline is a state
plus an auditable High/Medium/Low confidence, a convergence index, and the
binding constraint — the one string that tells the engineer what to do next.
"""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from starpost.core.convergence import assess
from starpost.core.convergence.config import (
    TOLERANCE_PRESETS,
    ConvergenceConfig,
    MonitorConfig,
)
from starpost.core.convergence.steady import GATE_ITERATIVE

_PRESET_LABELS = {
    "Screening (0.1%)": TOLERANCE_PRESETS["screening"],
    "Production (0.05%)": TOLERANCE_PRESETS["production"],
}

_MONITOR_COLUMNS = ("Primary", "Monitor", "Tolerance", "Reference scale")
_SUMMARY_COLUMNS = ("Data set", "State", "Confidence", "Index", "Binding constraint")
_RESIDUAL_COLUMNS = ("Equation", "Decades", "Slope", "rho", "r^2", "State",
                     "Iterations to target")
_GATE_COLUMNS = ("Monitor", "Primary", "Mean", "Band (95%)", "Drift",
                 "Iterative error", "N_eff", "Margin", "Binding gate")


class ConvergenceDialog(QDialog):
    """Non-modal convergence assessment over every loaded data set."""

    def __init__(self, store, settings, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._settings = settings
        self._assessments: dict = {}
        self._results: list = []
        # Per-sim monitor configuration, kept across re-assessments so editing
        # a tolerance does not reset the primary ticks.
        self._monitor_configs: dict[str, dict[str, MonitorConfig]] = {}
        self._updating = False

        self.setWindowTitle("Convergence")
        self.resize(1100, 700)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

        self.reload()

    # --- construction ---------------------------------------------------

    def _build_left(self) -> QWidget:
        self._preset = QComboBox()
        self._preset.addItems([*_PRESET_LABELS, "Custom"])
        self._preset.currentTextChanged.connect(self._on_preset_changed)

        self._custom = QDoubleSpinBox()
        self._custom.setDecimals(4)
        self._custom.setRange(0.0001, 100.0)
        self._custom.setSuffix(" %")
        self._custom.setValue(TOLERANCE_PRESETS["screening"] * 100.0)
        self._custom.setEnabled(False)
        self._custom.valueChanged.connect(lambda _v: self._reassess())

        # The required residual drop. 3 decades is the ASME Journal of Fluids
        # Engineering editorial policy's figure and the default, but it is a
        # judgement a practice can legitimately make differently — several real
        # runs settle their loads well inside tolerance while their residuals
        # plateau around 2.5 decades, and whether that counts as converged is
        # the engineer's call, not the tool's.
        self._d_min = QDoubleSpinBox()
        self._d_min.setDecimals(1)
        self._d_min.setRange(0.5, 8.0)
        self._d_min.setSingleStep(0.5)
        self._d_min.setSuffix(" decades")
        self._d_min.setValue(ConvergenceConfig().d_min)
        self._d_min.setToolTip(
            "Residual drop required of the continuity, momentum and energy "
            "equations before the solve counts as healthy.\n"
            "3 decades is the published ASME requirement and the default. "
            "Turbulence equations (Tke, Sdr, ...) are held to a lower bar and "
            "never held to a stricter one than this."
        )
        self._d_min.valueChanged.connect(lambda _v: self._reassess())

        form = QFormLayout()
        form.addRow("Tolerance", self._preset)
        form.addRow("Custom", self._custom)
        form.addRow("Residual drop", self._d_min)

        self._summary = QTableWidget(0, len(_SUMMARY_COLUMNS))
        self._summary.setHorizontalHeaderLabels(_SUMMARY_COLUMNS)
        self._summary.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._summary.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._summary.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._summary.verticalHeader().setVisible(False)
        self._summary.itemSelectionChanged.connect(self._on_selection_changed)

        self._monitor_table = QTableWidget(0, len(_MONITOR_COLUMNS))
        self._monitor_table.setHorizontalHeaderLabels(_MONITOR_COLUMNS)
        self._monitor_table.verticalHeader().setVisible(False)
        self._monitor_table.itemChanged.connect(self._on_monitor_edited)

        # Bulk primary selection. A real car-aero export carries ~40 monitors,
        # so "clear everything, then tick the one I care about" is otherwise a
        # 40-click operation. Each button rewrites the selected data set's
        # configuration and re-assesses once — see _set_all_primary.
        self._select_all_btn = QPushButton("Select all")
        self._select_all_btn.setToolTip(
            "Mark every monitor in this data set as a primary QoI."
        )
        self._select_all_btn.clicked.connect(lambda: self._set_all_primary(True))
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setToolTip(
            "Mark every monitor in this data set as non-primary. With no "
            "primary QoI the verdict reads 'no primary QoI declared' at Low "
            "confidence until you tick one."
        )
        self._clear_btn.clicked.connect(lambda: self._set_all_primary(False))
        self._reset_btn = QPushButton("Reset to auto")
        self._reset_btn.setToolTip(
            "Hand the primary choice back to the tool, which prefers an "
            "aggregate monitor (Downforce ALL) over its per-element siblings. "
            "Tolerance and reference-scale edits are kept."
        )
        self._reset_btn.clicked.connect(lambda: self._set_all_primary(None))

        buttons = QHBoxLayout()
        for button in (self._select_all_btn, self._clear_btn, self._reset_btn):
            buttons.addWidget(button)
        buttons.addStretch(1)

        panel = QWidget()
        box = QVBoxLayout(panel)
        box.addLayout(form)
        box.addWidget(QLabel("Data sets"))
        box.addWidget(self._summary)
        box.addWidget(QLabel("Monitors"))
        box.addWidget(self._monitor_table)
        box.addLayout(buttons)
        return panel

    def _build_right(self) -> QWidget:
        self._verdict_state = QLabel("No data sets loaded")
        self._verdict_state.setObjectName("convergenceState")
        self._verdict_confidence = QLabel()
        self._verdict_index = QLabel()
        self._verdict_binding = QLabel()
        self._verdict_binding.setWordWrap(True)
        self._verdict_flags = QLabel()
        self._verdict_flags.setWordWrap(True)

        card = QFrame()
        card.setObjectName("convergenceVerdict")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card_box = QVBoxLayout(card)
        card_box.addWidget(self._verdict_state)
        row = QHBoxLayout()
        row.addWidget(self._verdict_confidence)
        row.addWidget(self._verdict_index)
        row.addStretch(1)
        card_box.addLayout(row)
        card_box.addWidget(self._verdict_binding)
        card_box.addWidget(self._verdict_flags)

        self._reasons = QTreeWidget()
        self._reasons.setHeaderLabels(("Severity", "Target", "Reason"))
        self._reasons.setRootIsDecorated(True)

        self._residual_table = QTableWidget(0, len(_RESIDUAL_COLUMNS))
        self._residual_table.setHorizontalHeaderLabels(_RESIDUAL_COLUMNS)
        self._residual_table.verticalHeader().setVisible(False)

        self._gate_table = QTableWidget(0, len(_GATE_COLUMNS))
        self._gate_table.setHorizontalHeaderLabels(_GATE_COLUMNS)
        self._gate_table.verticalHeader().setVisible(False)

        tabs = QTabWidget()
        tabs.addTab(self._reasons, "Reasons")
        tabs.addTab(self._residual_table, "Residuals")
        tabs.addTab(self._gate_table, "QoI gates")

        panel = QWidget()
        box = QVBoxLayout(panel)
        box.addWidget(card)
        box.addWidget(tabs)
        for table in (self._summary, self._monitor_table,
                      self._residual_table, self._gate_table):
            table.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.ResizeToContents
            )
        return panel

    # --- data -----------------------------------------------------------

    def reload(self) -> None:
        """Re-snapshot the store and re-assess. Called on reopen so a re-raised
        window reflects the current workspace."""
        self._results = [r for r in self._store.all()
                         if r.error is None and r.plots]
        self._reassess()

    def _tolerance_fraction(self) -> float:
        label = self._preset.currentText()
        if label in _PRESET_LABELS:
            return _PRESET_LABELS[label]
        return self._custom.value() / 100.0

    def _config_for(self, result) -> ConvergenceConfig:
        d_min = self._d_min.value()
        return ConvergenceConfig(
            tolerance_fraction=self._tolerance_fraction(),
            d_min=d_min,
            # Turbulence equations are deliberately held to a weaker bar than
            # the primary ones — they routinely stall one to two orders above
            # the momentum residuals without harming the QoIs. Clamping keeps
            # that ordering true when the user lowers the primary requirement
            # below the turbulence default, which would otherwise invert it.
            d_min_turb=min(ConvergenceConfig().d_min_turb, d_min),
            monitors=dict(self._monitor_configs.get(result.sim_path, {})),
        )

    def _reassess(self) -> None:
        # Capture the selection by sim_path (not row index) so it survives a
        # re-population even though the row count/order can change.
        previous_path = self._selected_path()
        classification = self._settings.plot_classification
        self._assessments = {
            r.sim_path: assess(r, self._config_for(r), classification)
            for r in self._results
        }
        self._populate_summary()
        self._restore_selection(previous_path)

    # --- population -----------------------------------------------------

    def _selected_path(self) -> Optional[str]:
        """The sim_path of the currently selected summary row, if any."""
        row = self._summary.currentRow()
        if row < 0:
            return None
        item = self._summary.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _restore_selection(self, previous_path: Optional[str]) -> None:
        """Re-select the row for `previous_path` after a re-population,
        falling back to row 0 when there was no previous selection or that
        data set is no longer present."""
        if not self._results:
            self._show_placeholder()
            return
        target_row = 0
        if previous_path is not None:
            for row, result in enumerate(self._results):
                if result.sim_path == previous_path:
                    target_row = row
                    break
        # selectRow does not re-emit itemSelectionChanged when the target row
        # is already the current one (e.g. re-assessing while the same row
        # stays selected), so the detail panes are refreshed explicitly
        # rather than relying solely on the signal.
        self._summary.selectRow(target_row)
        self._on_selection_changed()

    def _populate_summary(self) -> None:
        self._updating = True
        try:
            self._summary.setRowCount(len(self._results))
            for row, result in enumerate(self._results):
                assessment = self._assessments[result.sim_path]
                cells = (
                    result.sim_name,
                    assessment.state.value,
                    assessment.confidence.value,
                    _index_text(assessment),
                    assessment.binding_constraint,
                )
                for column, text in enumerate(cells):
                    item = QTableWidgetItem(text)
                    if column == 0:
                        # Stashed so _selected_path can identify the row by
                        # sim_path rather than by index, which can shift.
                        item.setData(Qt.ItemDataRole.UserRole, result.sim_path)
                    self._summary.setItem(row, column, item)
        finally:
            self._updating = False

    def _show_placeholder(self) -> None:
        self._verdict_state.setText("No data sets loaded")
        for label in (self._verdict_confidence, self._verdict_index,
                      self._verdict_binding, self._verdict_flags):
            label.setText("")
        self._reasons.clear()
        self._monitor_table.setRowCount(0)
        self._residual_table.setRowCount(0)
        self._gate_table.setRowCount(0)
        self._set_bulk_buttons_enabled(False)

    def _current(self):
        row = self._summary.currentRow()
        if row < 0 or row >= len(self._results):
            return None
        return self._assessments[self._results[row].sim_path]

    def _on_selection_changed(self) -> None:
        if self._updating:
            return
        assessment = self._current()
        if assessment is None:
            # Defensive: currently unreachable, since _restore_selection always
            # selects a row when any data set is loaded and the table is in
            # SingleSelection mode. Disabling here keeps "no selection means no
            # bulk action" true locally, rather than resting on that argument.
            self._set_bulk_buttons_enabled(False)
            return
        self._populate_verdict(assessment)
        self._populate_reasons(assessment)
        self._populate_monitors(assessment)
        self._populate_residuals(assessment)
        self._populate_gates(assessment)

    def _populate_verdict(self, assessment) -> None:
        self._verdict_state.setText(assessment.state.value)
        self._verdict_confidence.setText(f"Confidence: {assessment.confidence.value}")
        self._verdict_index.setText(f"Convergence index: {_index_text(assessment)}")
        self._verdict_binding.setText(f"Binding: {assessment.binding_constraint}")
        self._verdict_flags.setText(
            "  ".join(flag.value for flag in assessment.flags)
        )

    def _populate_reasons(self, assessment) -> None:
        self._reasons.clear()
        for reason in assessment.reasons:
            item = QTreeWidgetItem(
                (reason.severity.value, reason.target, reason.message)
            )
            if reason.suggested_action:
                item.addChild(QTreeWidgetItem(("", "", reason.suggested_action)))
            if reason.estimated_extra_iterations:
                item.addChild(QTreeWidgetItem((
                    "", "",
                    f"Estimated ~{reason.estimated_extra_iterations:,} more "
                    "iterations (assumes the current rate persists)",
                )))
            self._reasons.addTopLevelItem(item)

    def _populate_monitors(self, assessment) -> None:
        self._updating = True
        try:
            self._monitor_table.setRowCount(len(assessment.monitors))
            for row, monitor in enumerate(assessment.monitors):
                # Column 0 is the checkbox alone; column 1 carries the name,
                # which _on_monitor_edited reads back to identify the row.
                primary = QTableWidgetItem("")
                primary.setFlags(
                    (primary.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    & ~Qt.ItemFlag.ItemIsEditable
                )
                primary.setCheckState(
                    Qt.CheckState.Checked if monitor.is_primary
                    else Qt.CheckState.Unchecked
                )
                self._monitor_table.setItem(row, 0, primary)
                self._monitor_table.setItem(row, 1, self._readonly(monitor.name))
                self._monitor_table.setItem(
                    row, 2,
                    QTableWidgetItem(f"{monitor.tolerance_fraction * 100:.4g} %")
                )
                self._monitor_table.setItem(
                    row, 3,
                    QTableWidgetItem(f"{monitor.reference_scale:.6g} "
                                     f"({monitor.scale_source.value})")
                )
            self._set_bulk_buttons_enabled(bool(assessment.monitors))
        finally:
            self._updating = False

    def _readonly(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _populate_residuals(self, assessment) -> None:
        self._residual_table.setRowCount(len(assessment.residuals))
        for row, residual in enumerate(assessment.residuals):
            projection = residual.iterations_to_target
            cells = (
                residual.name,
                f"{residual.decades_dropped:.2f}",
                f"{residual.log_slope:.3g}",
                f"{residual.decay_factor:.5f}",
                f"{residual.fit_r2:.3f}",
                residual.state.value,
                "—" if projection is None else f"{projection:,.0f}",
            )
            for column, text in enumerate(cells):
                self._residual_table.setItem(row, column, self._readonly(text))

    def _populate_gates(self, assessment) -> None:
        self._gate_table.setRowCount(len(assessment.monitors))
        for row, monitor in enumerate(assessment.monitors):
            cells = (
                monitor.name,
                "yes" if monitor.is_primary else "no",
                f"{monitor.mean:.6g}",
                f"{monitor.band_p95:.4g}",
                f"{monitor.projected_drift:.4g}",
                _iterative_cell(monitor),
                f"{monitor.n_eff:.0f}",
                _margin_cell(monitor),
                monitor.binding_gate,
            )
            for column, text in enumerate(cells):
                self._gate_table.setItem(row, column, self._readonly(text))

    # --- editing --------------------------------------------------------

    def _on_preset_changed(self, label: str) -> None:
        self._custom.setEnabled(label == "Custom")
        self._reassess()

    def _set_all_primary(self, value: Optional[bool]) -> None:
        """Bulk-set the primary tick for every monitor in the selected data
        set. ``True``/``False`` pin the choice; ``None`` hands it back to the
        auto rule (see MonitorConfig.is_primary).

        This writes the configuration and re-assesses once rather than driving
        the checkboxes: each checkbox write emits itemChanged, and
        _on_monitor_edited re-assesses *every* loaded data set, so ticking 40
        monitors across 10 loaded sims would run 400 assessments for a single
        click. The table is repopulated from the fresh assessment, exactly as
        it is after any single-cell edit."""
        row = self._summary.currentRow()
        if row < 0 or row >= len(self._results):
            return
        path = self._results[row].sim_path
        assessment = self._assessments.get(path)
        if assessment is None:
            return
        configs = self._monitor_configs.setdefault(path, {})
        # Only the monitors the assessment actually carries. Ones excluded
        # upstream — every value exactly zero at every iteration, i.e. a part
        # not present in this configuration — must not be resurrected by a
        # bulk selection.
        for monitor in assessment.monitors:
            existing = configs.get(monitor.name, MonitorConfig())
            existing.is_primary = value
            configs[monitor.name] = existing
        self._reassess()

    def _set_bulk_buttons_enabled(self, enabled: bool) -> None:
        for button in (self._select_all_btn, self._clear_btn, self._reset_btn):
            button.setEnabled(enabled)

    def _on_monitor_edited(self, item: QTableWidgetItem) -> None:
        if self._updating:
            return
        row = self._summary.currentRow()
        if row < 0 or row >= len(self._results):
            return
        path = self._results[row].sim_path
        configs = self._monitor_configs.setdefault(path, {})
        name_item = self._monitor_table.item(item.row(), 1)
        if name_item is None:
            return
        name = name_item.text()
        existing = configs.get(name, MonitorConfig())
        if item.column() == 0:
            existing.is_primary = item.checkState() == Qt.CheckState.Checked
        elif item.column() == 2:
            existing.tolerance_fraction = _parse_percent(item.text())
        elif item.column() == 3:
            existing.reference_scale = _parse_float(item.text())
        configs[name] = existing
        self._reassess()


def _iterative_cell(monitor) -> str:
    """The QoI-gates table's 'Iterative error' cell.

    ``monitor.iterative.u_iter`` is None whenever the geometric-tail estimator
    declined, which is common (a settled monitor, or now, per the
    Mann-Kendall check in ``steady.assess_monitor``, a creeping one). But the
    iterative gate can still be the binding constraint, so showing a blank
    there while the verdict names it as binding is confusing. Show the gate's
    own value instead — the quantity actually tested against the tolerance —
    and mark it when it is not the geometric-tail estimate."""
    gate = next(g for g in monitor.gates if g.name == GATE_ITERATIVE)
    if monitor.iterative.valid:
        return f"{gate.value:.4g}"
    if not math.isfinite(gate.value):
        return "unbounded"
    return f"{gate.value:.4g} (largest change)"


def _margin_cell(monitor) -> str:
    """The QoI-gates table's 'Margin' cell.

    ``monitor.margin`` (D2, steady.py) is the min over only the gates whose
    tested *value* is finite, so an infinite gate value — the iterative
    gate's value whenever the static-monitor escape hatch is denied — can no
    longer erase the monitor's other, perfectly good margins down to a false
    0.00. It is None only in the practically unreachable case where every
    one of the monitor's gates is unbounded, which is shown here the same
    way R2 shows an unmeasurable run-level index."""
    if monitor.margin is None:
        return "unbounded"
    return f"{monitor.margin:.2f}"


def _index_text(assessment) -> str:
    """The verdict card's and summary table's 'Convergence index' text.

    ``assessment.convergence_index`` is already honestly None when it could
    not be measured (R2) — this only adds the count of unbounded primary
    monitors so that information is not lost, whether or not a finite index
    could still be reported from the rest."""
    index = assessment.convergence_index
    text = "—" if index is None else f"{index:.2f}"
    count = assessment.unbounded_primary_count
    if count:
        plural = "s" if count != 1 else ""
        text += f" ({count} primary monitor{plural} unbounded)"
    return text


def _parse_percent(text: str) -> Optional[float]:
    # The rendered cell is "0.1 %", but a user editing it may type "0.2%"
    # with no space; _parse_float's split() then leaves the "%" glued to the
    # number and float() rejects it. Strip the sign before splitting so both
    # spellings recover the same value.
    value = _parse_float(text.replace("%", ""))
    return None if value is None else value / 100.0


def _parse_float(text: str) -> Optional[float]:
    try:
        return float(text.split()[0])
    except (ValueError, IndexError):
        return None
