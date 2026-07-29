# Convergence assessment export — design

## Goal

Let the Convergence window write its assessment out as a table, so a verdict
can leave the screen: into a design review, a study spreadsheet, or a record of
what a run looked like at the time it was judged.

StarPost's whole purpose is exporting post-processing artifacts — report tables
in csv/tsv/xlsx/ods, plots, scene stills, batch bundles. The Convergence tool
produces the richest analysis in the app and is currently the only thing that
cannot be exported at all. `docs/convergence-notes.md` §9 lists "Export of the
assessment" under *deliberately not implemented*; this closes that.

## Scope

- **Deliverable: a comparison table across data sets**, not a prose report and
  not an evidence plot. Both were considered and deferred: the readable
  per-run document is new territory (no prose-document writer exists in the
  app), and the evidence plot is a separate chunk of pyqtgraph work. §9 keeps
  listing the evidence plot as not implemented.
- **Four tables**, covering everything the window shows.
- **Triggered from the Convergence window only.** Folding a convergence report
  into the Run-batch wizard's `.zip` is a natural follow-up but touches
  `batch/run.py` and its config/profile plumbing, which is meaningfully more
  scope and risk. Out of scope here.
- **All loaded data sets**, not just the selected row. The summary is a
  cross-run comparison; restricting it to one row would defeat the point.

## Design

### 1. Shaping logic: `core/convergence/export.py`

A new Qt-free module beside the assessment model it shapes, mirroring how
`batch/aggregator.py` builds DataFrames separately from any GUI. pandas is
imported lazily inside the functions, per the repo's startup-latency
convention (`CLAUDE.md`).

```python
summary_frame(assessments)   -> DataFrame   # one row per data set
gates_frame(assessments)     -> DataFrame   # one row per data set x monitor
residuals_frame(assessments) -> DataFrame   # one row per data set x equation
reasons_frame(assessments)   -> DataFrame   # one row per reason
write_assessment(assessments, path, fmt) -> list[Path]
```

`write_assessment` returns the paths it actually wrote, so the window can
report exactly what landed on disk rather than assuming.

Every frame's first column is `Data set`, so the four can be joined back
together by the reader.

### 2. Packaging per format

| format | packaging |
|---|---|
| `xlsx`, `ods` | one file, four sheets: `Summary`, `QoI gates`, `Residuals`, `Reasons` |
| `csv`, `tsv` | four sibling files, since the format holds one table |

For csv/tsv, choosing `study.csv` writes `study-summary.csv`,
`study-qoi-gates.csv`, `study-residuals.csv`, `study-reasons.csv`.

Consistent suffixes on all four, rather than letting the named file be the
summary: four files read better as a set in a folder, and the success dialog
names what was written so the extra suffix is not a surprise.

### 3. Columns

**Summary** — one row per data set:

`Data set`, `State`, `Confidence`, `Confidence rule`, `Convergence index`,
`Unbounded primary monitors`, `Binding constraint`, `Flags`, `Segments`,
`Integrity errors`, `Tolerance (%)`, `Required residual drop (decades)`.

The last two are load-bearing, not decoration. A comparison table whose rows
were produced under different tolerances is misleading precisely because it
looks comparable, so the settings the export was made under travel with it.

**QoI gates** — one row per data set × monitor. Mirrors the window's tab plus
the quantities behind it:

`Data set`, `Monitor`, `Primary`, `Mean`, `Std`, `Reference scale`,
`Scale source`, `Tolerance (abs)`, `Band (95%)`, `Projected drift`,
`Two-halves delta`, `Iterative error`, `N_eff`, `D_N`, `Window start`,
`Window end`, `Window samples`, `Margin`, `Binding gate`, `Passed`.

`Iterative error` must follow the same rule the window's cell already does:
the gate's own tested value, marked when it is not the geometric-tail
estimate, and `unbounded` when infinite. A blank there while the verdict names
that gate as binding is exactly the confusion that cell was written to avoid.

That rule currently lives in `convergence_dialog._iterative_cell`. `core/`
must not import from `gui/`, and duplicating the rule would let the window and
the export drift apart. So the rule **moves** into `export.py` as a public
`iterative_error_text(monitor)`, and `_iterative_cell` becomes a call to it.
One behaviour, one definition, in the Qt-free layer where both can reach it.

**Residuals** — one row per data set × equation:

`Data set`, `Equation`, `Class`, `R_ref`, `R_terminal`, `Decades dropped`,
`Log slope`, `Decay factor`, `Fit r^2`, `State`, `Iterations to target`.

**Reasons** — one row per reason:

`Data set`, `Severity`, `Target`, `Message`, `Suggested action`,
`Estimated extra iterations`.

This is the table that carries "recommendations are the product" — the
tool's own first design principle — which is why a summary-only export was
rejected.

### 4. The button

`Export assessment…` in a button row under the Data sets table, mirroring the
bulk-selection row under the Monitors table.

- Disabled when no data sets are loaded, like the bulk buttons.
- `QFileDialog.getSaveFileName` with four format filters, starting in
  `settings.default_output_dir`.
- **The selected filter decides the format**, and the matching extension is
  appended when the typed name lacks it. Deciding from the typed extension
  instead would silently write an `.ods` whose contents are csv whenever the
  two disagree.
- On success: an information dialog naming the file(s) written.
- On failure: an error dialog carrying the exception message. A silent failure
  on an export is worse than a slow one — the user would believe they have a
  record they do not have.

The export reads `self._assessments`, which is already up to date for every
loaded data set; it never re-runs `assess()`.

## Testing

`tests/test_convergence_export.py` (new, no Qt):

- Each frame's columns and row counts over a hand-built two-data-set
  assessment; one data set with monitors and residuals, one without.
- `summary_frame` records the tolerance and residual-drop the assessment used,
  so two exports at different settings are distinguishable.
- `reasons_frame` carries the suggested action and the estimated extra
  iterations, not just the message.
- `gates_frame`'s `Iterative error` shows `unbounded` for an infinite gate
  value and marks a largest-change fallback.
- Every frame starts with a `Data set` column and attributes each row to the
  right data set.
- `write_assessment` with `csv`/`tsv` writes exactly four suffixed siblings and
  returns their paths; with `xlsx`/`ods` writes one file, re-read to confirm
  four sheets with the expected names.
- An unsupported format raises rather than writing a partial set.
- `iterative_error_text` returns the same string the window's cell shows, for
  a valid estimate, a largest-change fallback and an unbounded gate.

`tests/test_convergence_gui.py`:

- The export button is disabled with no data sets loaded and enabled with one.
- Clicking it with `QFileDialog.getSaveFileName` stubbed to a `tmp_path`
  target writes real, non-empty files.

## Documentation

- `CHANGELOG.md` entry in the existing style.
- `docs/convergence-notes.md` §9 — remove "Export of the assessment" from
  *deliberately not implemented*, leaving the evidence plot listed there.

No new keyboard shortcuts, so `src/starpost/gui/shortcuts.py` and
`docs/starpost_hotkeys.txt` are untouched.

## Out of scope

- The Run-batch wizard bundling a convergence report.
- The evidence plot (monitor history with the trailing window shaded).
- A prose/PDF report per run.
- Re-importing an exported assessment.
