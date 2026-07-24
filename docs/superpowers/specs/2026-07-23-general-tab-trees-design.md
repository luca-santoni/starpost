# General tab: expandable Reports & Monitors trees

**Date:** 2026-07-23
**Status:** Approved

## Problem

The Properties window's **General** tab (`_general_tab` in
`src/starpost/gui/views/properties_dialog.py`) is a flat `QFormLayout` with four
rows — File size, Reports (count), Monitors (count), Iterations (count) — plus a
"not extracted" hint. The reports and monitors are only surfaced as bare numbers.
The other tabs (Parts, Mesh, Regions, Physics) are browsable `QTreeWidget`s. This
change makes Reports and Monitors browsable trees in the same spirit, so the user
can see *what* the reports and monitors are, not just how many.

## New layout (extracted case)

The tab becomes a `QVBoxLayout` with three stacked parts:

1. **Summary form** (top) — a `QFormLayout` with only the two non-list values:
   - **File size**
   - **Iterations** (longest series length, as today)

   The old Reports/Monitors count rows are removed; their counts move into the
   tree section headings below.

2. **Reports section**
   - A section heading `QLabel` reading `Reports (N)` where N is the report count.
   - A single-column `QTreeWidget` beneath it, header hidden
     (`setHeaderHidden(True)`), `setAlternatingRowColors(True)`.
   - One top-level row per report, **name only**, in extraction order. Failed
     reports (with `error`) still appear by name.

3. **Monitors section**
   - A section heading `QLabel` reading `Monitors — P plots, S series`, where P is
     the number of monitor plots and S is the total series across all plots.
   - A `QTreeWidget` beneath it, header hidden, `setAlternatingRowColors(True)`.
   - Top-level rows are monitor **plots** (by `MonitorPlot.name`), in extraction
     order. Each plot's **series** appear as child rows (by `PlotSeries.name`).
   - **Redundant single child is shown, not suppressed:** when a plot has one
     series whose name equals the plot name, the child row is still rendered.
     Predictable and honest about the structure.
   - Trees are **collapsed by default** (no `expandAll`), so the plot rows read as
     dropdowns.

## Not-extracted case (unchanged behavior)

When `result` is `None` or `result.error` is set:
- The summary form shows **File size** and **Iterations: —**.
- The existing note is shown: "Open the file to extract its reports and monitors."
- No trees are built.

This matches the current `extracted` guard in `_general_tab`.

## Implementation notes

- Promote the `_general_tab(path, result, size_bytes)` **function** to a small
  `_GeneralTab(QWidget)` **class**, mirroring `_PartsTab` / `_RowsTab`. This lets
  it expose `self.reports_tree` and `self.monitors_tree` as attributes (each
  `None` in the not-extracted case, like `_PartsTab.tree`) so tests can reach
  them. `PropertiesDialog.__init__` swaps `_general_tab(...)` for
  `_GeneralTab(...)`.
- Counts: `reports = len(result.reports)`;
  `plots = len(result.plots)`;
  `series = sum(len(p.series) for p in result.plots)`;
  `iterations = max((len(s.x) for p in result.plots for s in p.series),
  default=0)` — same expressions used today, just relocated.
- No changes to the data model, extraction, or the other tabs.

## Testing

Update and extend `tests/test_properties_gui.py`:

- **Update** `test_general_tab_keeps_classic_summary` — it currently asserts the
  Reports/Monitors *count rows* live in the form. Reassert the new shape: File
  size and Iterations in the form; Reports/Monitors counts in the section
  headings.
- **Add** `reports_tree` lists report names (top-level count == report count).
- **Add** `monitors_tree` has one top-level row per plot, with series as children
  (assert a known plot's child count / child names).
- **Add** the Monitors heading shows the `P plots, S series` text.
- **Add** the unextracted case: `reports_tree is None` and `monitors_tree is
  None`, and the note is present.

Run with `python scripts/run_tests.py` (per CLAUDE.md; not bare pytest).

## CHANGELOG

Add a newest-first entry: the Properties window's General tab now lists reports
and monitors as browsable, expandable trees instead of bare counts.
