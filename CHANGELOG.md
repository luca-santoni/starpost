# Changelog

All notable changes to StarPost are recorded here. Versions follow the
`MAJOR.MINOR.PATCH` scheme; the newest release is listed first.

## [2.0.0] — 2026-06-22

A major release adding **scene-still rendering**: StarPost can now render images
of a `.sim`'s scenes, alongside the existing report and monitor-plot extraction.

### New Features
- **Scenes tab** — render scene stills from a `.sim`. Extraction now also
  discovers each sim's **scenes** (with their **scalar/vector displayers**) and
  **saved camera views**, which populate a **scene → displayer tree** and a
  **Saved views** list in the selection panel.
- **Run** renders the checked scenes of the **single** ticked data set to image
  stills, showing only the checked displayers and rendering once per checked
  saved view (or the scene's current view). Results appear in a **thumbnail
  gallery** — double-click to open, **right-click → Properties** (file size,
  resolution, format, parent `.sim`, data set, scene, displayers, saved view),
  and **Clear scenes** to remove them.
- **Settings → Scenes** — **Image resolution** (1080p / 2160p) and **Image
  format** (JPG / PNG). **Settings → STAR-CCM+** adds **Parallel cores** (the
  `-np` count for rendering) and **Scenes per license** (scenes per checkout).
- **First-open warning** that scene rendering is memory-heavy (≥16 GB
  recommended), with a "Do not show this again" opt-out.

### Changes
- **"Add folder…"** in the Files tab now imports a folder's `.sim` files into a
  **new internal folder named after it**, instead of adding them at the top level.
- Rendering runs as a **separate macro pass** (`printAndWait`), **in parallel**
  (`starccm+ -np`), closing each scene after its hardcopy to limit memory growth.
- Rendered files are named **`Dataset-Scene-Displayers-View`**.

### Notes
- The extraction macro (reports, plots, and scene/view discovery) has been run
  against a live STAR-CCM+ 2310 install. The scene-render *apply-saved-view* call
  is the one remaining version-specific operation still being validated.

## [1.5.0] — 2026-06-21

This release adds program-wide text scaling, a more informative plot Y axis,
and a round of dropdown, list, and export-menu polish.

### New Features
- **Adjustable text size** — a new **Text size** control in
  Settings → Appearance scales the font of every button and label across the
  app (1.0× to 1.5×; 1.0× is the original size). The plot title and axis labels
  in the main view scale with it too (the export preview keeps its own sizes).
- **Plot Y axis shows the physical quantity** — the vertical axis now reads e.g.
  **“Force (lbf)”** instead of just **“lbf”**, inferring the quantity (Force,
  Pressure, Mass Flow, Velocity, Temperature, …) from the monitor’s unit.
  Unknown units fall back to the unit alone; mixed/absent units show “Value”.

### Changes
- **Folder open/closed state persists** — expanding or collapsing a folder in
  the Files or Data tab is now remembered across restarts.
- **Dropdown menus** — the hovered item is outlined in the accent colour (was a
  black outline), rows have more vertical spacing, and dropdowns always open
  downward instead of opening upward over the control.
- **Menu checkmarks stay visible** — a checked right-click menu item (e.g. the
  Sort options) keeps its checkmark visible when highlighted.

### Fixes
- **Run batch respects Cancel** — cancelling the “Folder for extracted data”
  dialog after **Run batch** no longer runs the batch into a default folder.
- **Tab labels no longer clip** — the Files/Data/Reports/Plots tabs widen with
  the text size instead of cutting off at larger sizes.
- **No leftover row outline** — clicking empty space in a list/tree no longer
  leaves a faint outline on the previously-clicked row.
- **Clicking a monitor name selects it** — in the export menu’s Plots tab,
  clicking a monitor or group name (not just its checkbox) now toggles it.

### Maintenance
- Removed the unused matplotlib dependency — plot image export already runs
  through the in-app (pyqtgraph) renderer.

## [1.4.1] — 2026-06-20

A patch release fixing a crash that made the export menu unusable in 1.4.0.

### Fixes
- **Export menu no longer crashes on open** — both **Export…** (Reports/Plots)
  and **Export Data** raised an error because a shared checklist widget was
  removed during the 1.4.0 Data-tab rework. It has been restored.

## [1.4.0] — 2026-06-20

This release brings the Files tab's virtual-folder organisation to the Data tab,
makes residual plots one-click, and gives the UI consistent spacing across
Windows and Linux.

### New Features
- **Virtual folders in the Data tab** — organise data sets into in-app nested
  folders, mirroring the Files tab: right-click for **New Folder**, drag data
  sets/folders to re-parent them, sort per folder, and **Check all / Uncheck
  all**, **Rename**, **Delete folder**, and **Properties** on a folder. The
  folder layout persists across sessions.

### Changes
- **Residual plots draw all monitors at once** — checking a residual monitor
  group (in the main view or the export menu) now plots every monitor in it,
  instead of revealing them unticked. Other groups are unchanged.

### Fixes
- **Consistent UI spacing across platforms** — the app now uses the Fusion style
  everywhere, so list rows and tabs no longer space wider on Windows than on
  Linux.

## [1.3.0] — 2026-06-19

This release focuses on **plot customization** — both in the live view and the
export menu — plus a smoothing option and faster startup.

### Plot export menu
The Plots tab of the export menu gained a full set of appearance controls, all
applied live to the preview and carried through to the exported image:

- **Per-monitor line colours** — each monitor has a colour swatch; click it to
  recolour its line (palette or custom). When two or more data sets are plotted,
  each monitor shows **one swatch per data set**, so every line can be coloured
  individually.
- **Legend scale** slider — resize the legend from half to double size
  (mid-point = natural size).
- **Line thickness** slider — set the pen width of every line at once.
- **Title size** and **Axis label size** sliders — scale the title and both axis
  labels (X and Y kept in step) independently.
- **Show grid** toggle — show or hide the plot's background grid.

### Plot colours in the main UI
- **Per-monitor colour swatches** are now available directly in the main
  window's Monitor plots list, working the same way as the export menu (one
  swatch per plotted data set).
- **Colours mirror to the export menu** — colours chosen in the main UI carry
  over to the export preview when it is opened.
- **Distinct colours per line in comparison mode** — when multiple data sets and
  monitors are shown together, every line now gets its own colour instead of
  sharing one colour per data set, so individual monitors are easy to tell apart.

### Monitor selection & layout
- **Monitor picking moved into the list** — choosing which monitors are drawn is
  now done from a tree in the Monitor plots list (check a group to reveal its
  monitors), replacing the dropdown row that used to sit under the plot.
- **Focused selection panel** — the panel now shows only the checklist for the
  active centre tab (Reports list on the Reports tab, Monitor plots on the Plots
  tab), and the visible list expands to fill the space. Both selections are
  always remembered.

### Data smoothing
- **Smooth data** toggle under the plot applies a moving average to the shown
  monitors. The window size is configurable via the new **Moving average width**
  setting (Settings → Plots), defaulting to 10.

### Performance
- **Faster startup** — the crash-recovery cache is now written compactly (about
  half the size, faster to reload), and the pandas import is deferred off the
  launch path, cutting roughly ~170 ms from cold start.

### Packaging
- New Linux build: **`StarPost-1.3.0-x86_64.AppImage`**.

## [1.2.0] — 2026-06-18

Auto-updates, credential safety, and UI polish.

### Added
- **In-app auto-update** for the packaged Windows build: checks GitHub for a
  newer release on startup, and (when one is found) downloads and launches the
  installer.
- **"New update available"** note shown under the toolbar version label.
- **"Clear all temp files"** button in the Misc settings tab.
- **Hover tooltips** describing every button in the UI.

### Changed
- The tooltip timer now resets when moving between buttons, instead of showing
  the next tooltip instantly.
- `__version__` is now the single source of truth for the version (the installer
  and packaging derive from it).

### Security
- The **Power-on-Demand key is masked** in the setup wizard and settings dialogs.
- Settings and log files are restricted to **owner-only** permissions.
- License credentials are **redacted** from logged STAR-CCM+ commands.

## [1.1.0] — 2026-06-18

Initial public, feature-complete release. (The `1.0.0` and `1.1.0` tags point to
the same commit; see 1.0.0 below.)

### Extraction & batch processing
- Batch-open solved STAR-CCM+ `.sim` files and extract all report values and
  monitor plots; processing runs sequentially (license-safe).
- Live progress (an *x/N* counter and a thin progress-bar underline) with a
  streaming log of STAR-CCM+ output.
- Skip already-loaded files (with a force option) and a crash-recovery cache that
  restores loaded data on the next launch.

### Files / Data workspace
- Persistent **Files** list with a **virtual folder** system (nesting,
  drag-and-drop re-parenting, per-folder sorting, folder Properties, and a
  configurable folder-icon colour).
- **Data** list with checkable selection that drives the views and switches into
  comparison mode when two or more are ticked.
- **Portable data import/export** to a self-contained StarPost CSV (re-importable
  without STAR-CCM+), plus **Properties** on any file, data set, or folder.

### Viewing
- **Report table** with configurable decimals, hide-empty/zero-threshold, sorting,
  and a comparison (wide) view.
- **Monitor plot viewer** (pyqtgraph): multiple groups at once with per-group
  monitor dropdowns, automatic log/linear axis classification, a hover readout
  (configurable X/Y decimals and optional monitor name), **Shift+drag region
  statistics** (selectable Avg/Median/Std Dev/Var/Min/Max/Range in a draggable
  panel), and a theme-aware plot.

### Selection & profiles
- Reports/plots checklists with Select all / Clear and A–Z / Z–A sorting.
- **Profiles**: save, load, and delete named selections (including which monitors
  show per group and which region statistics show), with a reserved built-in
  **Default** profile and a details view.

### Settings, appearance & onboarding
- Full settings dialog (Appearance/theme, Reports, Plots, Export defaults,
  Profiles, About, Misc) with scrollable pages and a Reset button.
- Dark theme with a configurable accent, checkmark, and folder colour.
- First-run welcome/setup wizard.

### Export
- Export menu with **Reports** and **Plots** tabs.

### Packaging & platform
- Cross-platform support (Linux + Windows) with a platform-aware executable
  picker, a **Linux AppImage** build script, a **Windows Inno Setup** installer,
  the MIT licence, and the app icon plus toolbar version label.

## [1.0.0] — 2026-06-18

Initial release of StarPost. This tag points to the **same commit as 1.1.0**, so
the two share an identical feature set — see the 1.1.0 notes above.
