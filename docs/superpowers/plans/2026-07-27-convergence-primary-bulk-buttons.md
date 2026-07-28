# Convergence Monitors Bulk-Selection Buttons — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add **Select all**, **Clear** and **Reset to auto** buttons to the Convergence window's Monitors list, so the primary-QoI ticks can be set in one click instead of one checkbox at a time.

**Architecture:** Two layers. First, `MonitorConfig.is_primary` becomes tri-state (`Optional[bool]`, `None` = "let the auto rule decide") so that "Reset to auto" has something to write and a tolerance-only override stops silently freezing a monitor's primary state. Second, the dialog grows three buttons that route through one handler which writes the per-sim configuration and re-assesses exactly once.

**Tech Stack:** Python 3.11+, PySide6, numpy, pytest. No new dependencies.

**Design spec:** `docs/superpowers/specs/2026-07-27-convergence-primary-bulk-buttons-design.md`

## Global Constraints

- Line length 100, `ruff check .` must stay clean, target `py311`.
- Use the repo venv explicitly: `.venv/bin/python`. There is no system pip/venv on this machine.
- GUI tests need `QT_QPA_PLATFORM=offscreen`.
- Run a **single** test file with `python -m pytest tests/<file>.py`; that is one process and is safe. Never run a bare multi-file `pytest` — use `.venv/bin/python scripts/run_tests.py` for the full suite.
- Commit after every task (repo convention: commit after every change).
- `MonitorAssessment.is_primary` (in `models.py`, the assessment *output*) stays a plain `bool`. Only `MonitorConfig.is_primary` (in `config.py`, the user *override*) becomes tri-state. Do not confuse the two.
- Do not change `_select_auto_primary`'s own rule for which monitors it picks.

---

### Task 1: Tri-state primary override

Make `MonitorConfig.is_primary` express "no opinion", so the auto-primary rule can still run for a monitor that carries some other override.

**Files:**
- Modify: `src/starpost/core/convergence/config.py:53-59`
- Modify: `src/starpost/core/convergence/__init__.py:138-173` (`_auto_primary_reason`), `:327-331` (the `assess` branch)
- Modify: `docs/convergence-notes.md` (§6)
- Test: `tests/test_convergence_config.py:61-65`, `tests/test_convergence_verdict.py` (new tests after line 156)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `MonitorConfig.is_primary: Optional[bool]` with `None` as the default, meaning "defer to `_select_auto_primary`". Task 2's `_set_all_primary` writes `True` / `False` / `None` into this field.

- [ ] **Step 1: Update the existing config default test**

In `tests/test_convergence_config.py`, replace `test_monitor_config_defaults_to_non_primary_auto_scale` (lines 61-65) with:

```python
def test_monitor_config_defaults_to_deferring_the_primary_choice():
    """is_primary is tri-state: None means "no opinion", so the auto-primary
    rule still decides. A plain False would read as an explicit demotion, and
    would freeze the primary choice of any monitor that carries some other
    override (a tolerance edit, say) as a side effect."""
    m = ConvergenceConfig().monitor("anything")
    assert m.is_primary is None
    assert m.tolerance_fraction is None
    assert m.reference_scale is None
```

- [ ] **Step 2: Write the failing assess-level tests**

In `tests/test_convergence_verdict.py`, add after `test_explicit_override_beats_the_auto_aggregate_choice_in_both_directions` (which ends at line 156):

```python
def test_a_none_primary_override_defers_to_the_auto_rule():
    """MonitorConfig.is_primary is tri-state: None means "no opinion". The
    Convergence window's "Reset to auto" button relies on this, and so does a
    monitor whose *tolerance* was edited without touching its primary tick —
    under a plain bool that edit would freeze the monitor non-primary as a
    side effect, because the mere existence of a MonitorConfig read as an
    explicit override."""
    names = ["Downforce ALL Monitor", "Downforce wing front 1 Monitor"]
    result = make_multi_monitor_result(names, residual=healthy_residual())
    config = ConvergenceConfig(monitors={
        "Downforce ALL Monitor": MonitorConfig(tolerance_fraction=5e-4),
        "Downforce wing front 1 Monitor": MonitorConfig(),
    })
    a = assess(result, config, CLASSIFICATION)
    assert {m.name for m in a.monitors if m.is_primary} == {"Downforce ALL Monitor"}
    aggregate = next(m for m in a.monitors if m.name == "Downforce ALL Monitor")
    assert aggregate.tolerance_fraction == 5e-4


def test_the_auto_primary_reason_still_names_a_monitor_with_a_tolerance_override():
    """The INFO reason exists so a wrong auto-choice leaves a trace rather
    than silently narrowing the verdict. It excludes monitors the *user*
    pinned, so that exclusion must key on an explicit True/False — not on the
    mere presence of a MonitorConfig, which a tolerance edit alone creates."""
    names = ["Downforce ALL Monitor", "Downforce wing front 1 Monitor"]
    result = make_multi_monitor_result(names, residual=healthy_residual())
    config = ConvergenceConfig(monitors={
        "Downforce ALL Monitor": MonitorConfig(tolerance_fraction=5e-4),
    })
    a = assess(result, config, CLASSIFICATION)
    auto = [r for r in a.reasons if "auto-selected as primary" in r.message]
    assert len(auto) == 1
    assert "Downforce ALL Monitor" in auto[0].message
```

Note: "an explicit `is_primary=False` still demotes an auto-selected monitor" is already covered by the existing `test_explicit_override_beats_the_auto_aggregate_choice_in_both_directions`. Do not duplicate it.

- [ ] **Step 3: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_convergence_config.py -k defaults_to_deferring -v
```

Expected: FAIL — `assert False is None`.

```bash
.venv/bin/python -m pytest tests/test_convergence_verdict.py -k "none_primary_override or tolerance_override" -v
```

Expected: both FAIL. The first because `MonitorConfig()` yields `is_primary=False`, which reads as an explicit demotion, so no monitor is primary. The second because `_auto_primary_reason` sees a `MonitorConfig` for the aggregate and drops it, leaving `effective` empty and returning `None`, so no matching reason exists.

- [ ] **Step 4: Make `is_primary` tri-state**

In `src/starpost/core/convergence/config.py`, replace the `MonitorConfig` dataclass (lines 53-59) with:

```python
@dataclass
class MonitorConfig:
    """Per-monitor overrides. ``reference_scale`` set means rung 1 of the
    scale ladder (user-supplied physical scale) is taken.

    ``is_primary`` is deliberately tri-state: ``True``/``False`` pin the
    choice, ``None`` means "no opinion" and leaves it to
    ``_select_auto_primary``. A plain ``bool`` cannot express that, and the
    difference is not academic — the mere existence of a MonitorConfig would
    then read as an explicit override, so editing one monitor's *tolerance*
    would silently freeze its primary state too, and the auto rule could
    never run for it again."""
    is_primary: Optional[bool] = None
    tolerance_fraction: Optional[float] = None
    reference_scale: Optional[float] = None
```

- [ ] **Step 5: Honour the tri-state in `assess` and in the auto-primary reason**

In `src/starpost/core/convergence/__init__.py`, add this helper immediately after `_select_auto_primary` (i.e. after line 103):

```python
def _explicit_primary(config: ConvergenceConfig, name: str) -> Optional[bool]:
    """The user's explicit primary choice for a monitor, or None when they
    have expressed none and the auto rule should decide.

    MonitorConfig.is_primary is tri-state (see config.py), so the mere
    existence of a MonitorConfig — which editing that monitor's tolerance or
    reference scale alone creates — is not an override of the primary
    choice."""
    override = config.monitors.get(name)
    return None if override is None else override.is_primary
```

Then in `_auto_primary_reason`, replace the `effective` computation (lines 152-154):

```python
    effective = sorted(
        name for name in auto_primary_names
        if _explicit_primary(config, name) is None
    )
```

And in `assess`, replace the primary decision (lines 327-331):

```python
        explicit = _explicit_primary(config, signal.name)
        is_primary = (explicit if explicit is not None
                      else signal.name in auto_primary_names)
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_convergence_config.py tests/test_convergence_verdict.py -v
```

Expected: PASS, all tests in both files (`tests/test_convergence_verdict.py` alone carries ~90 tests; none should regress).

- [ ] **Step 7: Run the other analysis test files**

```bash
.venv/bin/python -m pytest tests/test_convergence_steady.py -W error::RuntimeWarning -q
```

Expected: PASS. `test_convergence_steady.py:483` constructs `MonitorConfig(is_primary=True, tolerance_fraction=1e-6)` — an explicit `True`, unaffected by this change.

- [ ] **Step 8: Record the decision in the handoff notes**

In `docs/convergence-notes.md`, in section 6 ("Design decisions that must not be silently undone"), add a new paragraph after the "**Aggregate monitors are preferred as auto-primary.**" entry (the last one in that section):

```markdown
**`MonitorConfig.is_primary` is tri-state, not a bool.** `None` means "no
opinion — let `_select_auto_primary` decide". Collapsing it back to a plain
`bool` silently kills the auto rule: the mere existence of a MonitorConfig
would again read as an explicit override, so editing one monitor's tolerance
would freeze its primary state as a side effect, and the Convergence window's
"Reset to auto" button would have no value to write. `_auto_primary_reason`
keys on the same distinction, so it would also stop naming monitors that carry
an unrelated override.
```

- [ ] **Step 9: Lint**

```bash
.venv/bin/python -m ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 10: Commit**

```bash
git add src/starpost/core/convergence/config.py src/starpost/core/convergence/__init__.py tests/test_convergence_config.py tests/test_convergence_verdict.py docs/convergence-notes.md
git commit -m "feat: make the primary-monitor override tri-state

None means 'no opinion', so the auto-primary rule still decides for a
monitor that carries only a tolerance or reference-scale override.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Select all / Clear / Reset to auto buttons

**Files:**
- Modify: `src/starpost/gui/views/convergence_dialog.py` — imports (lines 17-35), `_build_left` (lines 135-147), `_reassess` (lines 239-248, deletion), `_populate_monitors` (lines 359-387), `_show_placeholder` (lines 306-314), plus two new methods
- Modify: `CHANGELOG.md`
- Test: `tests/test_convergence_gui.py`

**Interfaces:**
- Consumes: `MonitorConfig.is_primary: Optional[bool]` from Task 1 — writing `None` hands the choice back to `_select_auto_primary`.
- Produces: `ConvergenceDialog._select_all_btn`, `._clear_btn`, `._reset_btn` (all `QPushButton`), and `ConvergenceDialog._set_all_primary(value: Optional[bool]) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_convergence_gui.py`:

```python
def test_select_all_marks_every_monitor_primary(app):
    dlg = open_dialog(store_with(make_aggregate_and_element_result("/tmp/a.sim")))
    dlg._select_all_btn.click()
    assessment = dlg._current()
    assert {m.name for m in assessment.monitors if m.is_primary} == {
        "Downforce ALL Monitor", "Downforce wing front 1 Monitor"}
    dlg.close()


def test_clear_leaves_no_primary_and_says_so_rather_than_erroring(app):
    """Clearing every primary is a valid state, not a failure: it is the
    midpoint of "clear, then tick the one I want". The verdict reports it
    honestly instead of forcing a minimum selection."""
    dlg = open_dialog(store_with(make_aggregate_and_element_result("/tmp/a.sim")))
    dlg._clear_btn.click()
    assert not any(m.is_primary for m in dlg._current().monitors)
    assert "no primary QoI declared" in dlg._verdict_binding.text()
    assert "Low" in dlg._verdict_confidence.text()
    dlg.close()


def test_reset_to_auto_restores_the_aggregate_preferred_choice_after_a_clear(app):
    """Without a tri-state override there would be no way back to the tool's
    own choice short of closing and reopening the window."""
    dlg = open_dialog(store_with(make_aggregate_and_element_result("/tmp/a.sim")))
    dlg._clear_btn.click()
    assert not any(m.is_primary for m in dlg._current().monitors)
    dlg._reset_btn.click()
    assert {m.name for m in dlg._current().monitors if m.is_primary} == {
        "Downforce ALL Monitor"}
    dlg.close()


def test_reset_to_auto_keeps_a_tolerance_override(app):
    """Reset hands back the *primary* choice only. The button sits in a
    primary-selection group, so silently discarding an unrelated per-monitor
    tolerance edit would be scope the label does not advertise."""
    dlg = open_dialog(store_with(make_aggregate_and_element_result("/tmp/a.sim")))
    path = dlg._results[0].sim_path
    assert dlg._monitor_table.item(0, 1).text() == "Downforce ALL Monitor"
    dlg._monitor_table.item(0, 2).setText("0.2 %")
    dlg._reset_btn.click()
    assert dlg._monitor_configs[path]["Downforce ALL Monitor"].tolerance_fraction == (
        pytest.approx(0.002))
    aggregate = next(m for m in dlg._current().monitors
                     if m.name == "Downforce ALL Monitor")
    assert aggregate.tolerance_fraction == pytest.approx(0.002)
    assert aggregate.is_primary is True
    dlg.close()


def test_a_bulk_click_re_assesses_once_not_once_per_monitor(app, monkeypatch):
    """The buttons write the configuration and re-assess once. Driving the
    checkboxes instead would emit itemChanged per row, and _on_monitor_edited
    re-assesses *every* loaded data set — 2 monitors x 2 sims here, but 40 x
    10 on a real workspace, i.e. 400 assessments for one click."""
    import starpost.gui.views.convergence_dialog as module

    dlg = open_dialog(store_with(make_aggregate_and_element_result("/tmp/a.sim"),
                                 make_aggregate_and_element_result("/tmp/b.sim")))
    calls = []
    real_assess = module.assess

    def counting_assess(*args, **kwargs):
        calls.append(1)
        return real_assess(*args, **kwargs)

    monkeypatch.setattr(module, "assess", counting_assess)
    dlg._select_all_btn.click()
    # One assess() per loaded data set, for exactly one re-assessment pass.
    assert len(calls) == 2
    dlg.close()


def test_the_bulk_buttons_are_disabled_with_no_data_sets_loaded(app):
    dlg = open_dialog(store_with())
    assert dlg._select_all_btn.isEnabled() is False
    assert dlg._clear_btn.isEnabled() is False
    assert dlg._reset_btn.isEnabled() is False
    dlg.close()


def test_the_bulk_buttons_are_enabled_once_a_data_set_is_loaded(app):
    dlg = open_dialog(store_with(make_result("/tmp/a.sim")))
    assert dlg._select_all_btn.isEnabled() is True
    assert dlg._clear_btn.isEnabled() is True
    assert dlg._reset_btn.isEnabled() is True
    dlg.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_convergence_gui.py -k "bulk or select_all or clear_leaves or reset_to_auto" -v
```

Expected: all FAIL with `AttributeError: 'ConvergenceDialog' object has no attribute '_select_all_btn'`.

- [ ] **Step 3: Import QPushButton**

In `src/starpost/gui/views/convergence_dialog.py`, add `QPushButton` to the `PySide6.QtWidgets` import block, keeping alphabetical order (between `QLabel` and `QSplitter`):

```python
    QLabel,
    QPushButton,
    QSplitter,
```

- [ ] **Step 4: Add the buttons to the left panel**

In `_build_left`, immediately after the `self._monitor_table.itemChanged.connect(self._on_monitor_edited)` line (line 138), insert:

```python
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
```

Then, in the same method, add the row to the panel layout immediately after `box.addWidget(self._monitor_table)`:

```python
        box.addLayout(buttons)
```

- [ ] **Step 5: Add the handler and the enablement helper**

In `src/starpost/gui/views/convergence_dialog.py`, add both methods to the `--- editing ---` section, immediately after `_on_preset_changed`:

```python
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
```

- [ ] **Step 6: Drive the button enablement**

In `_populate_monitors`, add this as the last statement of the `try:` block (after the `for` loop over `assessment.monitors`, still inside `try`):

```python
            self._set_bulk_buttons_enabled(bool(assessment.monitors))
```

In `_show_placeholder`, add after `self._gate_table.setRowCount(0)`:

```python
        self._set_bulk_buttons_enabled(False)
```

- [ ] **Step 7: Delete the seeding loop**

In `_reassess`, delete these lines entirely (lines 239-248):

```python
        # Seed the per-monitor configuration from the first assessment, so the
        # auto-primary choice is visible and editable rather than implicit.
        for path, assessment in self._assessments.items():
            known = self._monitor_configs.setdefault(path, {})
            for monitor in assessment.monitors:
                known.setdefault(monitor.name, MonitorConfig(
                    is_primary=monitor.is_primary,
                    tolerance_fraction=None,
                    reference_scale=None,
                ))
```

`_reassess` then goes straight from building `self._assessments` to `self._populate_summary()`. Under tri-state this loop would write only `None` entries, which carry no information: `_on_monitor_edited` already creates a `MonitorConfig` on demand via `configs.get(name, MonitorConfig())`, and `_config_for` handles an absent dict. Leaving it in place would also pin an explicit `is_primary` on every monitor after the first assessment — exactly what stops the auto rule ever running again, and what "Reset to auto" now exists to undo.

Keep the `MonitorConfig` import: `_on_monitor_edited` and the new `_set_all_primary` both use it.

- [ ] **Step 8: Run the new tests**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_convergence_gui.py -v
```

Expected: PASS, every test in the file including the seven new ones. Pay attention to `test_g1_the_tolerance_column_shows_a_percent_suffix_and_edits_round_trip` and `test_f4_editing_the_tolerance_cell_with_no_space_before_the_percent_sign` — both read `dlg._monitor_configs[path]["Drag"]` and both do so *after* an edit that creates the entry, so deleting the seeding loop must not affect them.

- [ ] **Step 9: Lint**

```bash
.venv/bin/python -m ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 10: Add the CHANGELOG entry**

In `CHANGELOG.md`, under `## [Unreleased]` → `### New Features`, add a new bullet after the existing "Extraction now records solver precision…" bullet (which ends at line 58):

```markdown
- **Convergence tool: Select all, Clear and Reset to auto for the monitor
  list.** Primary monitors are the ones that gate the headline verdict, and a
  real car-aero export carries around 40 of them, so picking a different one
  by hand meant unticking dozens of checkboxes. Three buttons under the
  Monitors table now set them in one click, for the selected data set. *Reset
  to auto* hands the choice back to the tool's own rule, which prefers an
  aggregate monitor (Downforce ALL) over its per-element siblings — previously
  the automatic choice was frozen the first time a data set was assessed, so
  there was no way back to it short of closing and reopening the window.
  Reset keeps any tolerance and reference-scale edits; it restores the primary
  ticks only. Clearing every monitor is allowed and reports honestly — the
  verdict reads "no primary QoI declared" at Low confidence until you tick one.
```

- [ ] **Step 11: Commit**

```bash
git add src/starpost/gui/views/convergence_dialog.py tests/test_convergence_gui.py CHANGELOG.md
git commit -m "feat: bulk primary selection in the Convergence monitors list

Select all / Clear / Reset to auto, acting on the selected data set. Each
writes the configuration and re-assesses once rather than driving the
checkboxes, which would re-assess every loaded data set per row.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Full-suite verification

**Files:** none modified.

**Interfaces:**
- Consumes: the complete implementation from Tasks 1 and 2.
- Produces: nothing — this is the verification gate.

- [ ] **Step 1: Run the full suite**

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/run_tests.py
```

Expected: `All files passed.` across 40 files. The baseline before this work was fully green, so any failure is a regression from these two tasks.

If `tests/test_main_window.py`, `tests/test_shortcuts.py` or `tests/test_plot_view.py` fail, re-run that file on its own before calling it a regression — those three are known to fail intermittently under the parallel runner and pass per-file:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window.py -q
```

- [ ] **Step 2: Verify against real data**

The ten real car-aero exports live in `/home/luca/Downloads/temp output/` (user's machine, not in the repo) and load without STAR-CCM+. Task 1 changes how the primary choice is resolved, so confirm the auto-selected primaries and the resulting verdict are unchanged for a data set with no overrides:

```bash
.venv/bin/python -c "
from pathlib import Path
from starpost.data.portable import read_sim_csv
from starpost.core.convergence import assess
from starpost.core.convergence.config import ConvergenceConfig
from starpost.core.settings import Settings
r = read_sim_csv(Path('/home/luca/Downloads/temp output/SDM25-RW-014@03000.csv'))
a = assess(r, ConvergenceConfig(), Settings().plot_classification)
print(a.state, a.confidence, a.convergence_index, a.binding_constraint)
print(sorted(m.name for m in a.monitors if m.is_primary))
"
```

Expected, per `docs/convergence-notes.md` §3: `STALLED Medium 0.176 Continuity: only 1.1 of 3 required decades`, with the primary set containing only the aggregate ("ALL") monitors. An empty-config `assess` takes the `_explicit_primary(...) is None` path for every monitor, so this must match the recorded table exactly.

If the directory is missing, say so and skip this step rather than inventing a substitute — do not mark it done.

- [ ] **Step 3: Report**

State plainly: full suite result, the real-data check result (or that it was skipped and why), and anything left undone. Do not claim completion without the command output to back it.
