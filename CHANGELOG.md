# Changelog

All notable changes to StarPost are recorded here. Versions follow the
`MAJOR.MINOR.PATCH` scheme; the newest release is listed first.

## [Unreleased]

### New Features
- **File menu** — a new **File** dropdown sits first in the top bar (before
  Run batch), offering **Add ▸ Files… / Folder…** (the Files tab's add
  dialogs), **Import data…** and **Export data…** (the Data tab's
  portable-CSV import/export) — the same operations, reachable without
  switching tabs.

### Improvements
- **Menu-bar-style dropdowns** — the top bar's **File** and **Run batch**
  menus now open on click (no more hover-open) and stay open wherever the
  mouse goes; with one open, hovering the other menu button switches to it,
  and a click anywhere else dismisses it — like a traditional menu bar.

### Bug Fixes
- **Open-menu button highlight** — the **File** and **Run batch** buttons kept
  their bright hover highlight while their dropdown was open instead of fading
  to the near-invisible pressed shade, so it's now clear which menu is active.

## [2.4.0] — 2026-07-12

### New Features
- **Screenplays in Run batch** — the Run-batch wizard gains a **Screenplays** tab
  (Source → Reports → Plots → Scenes → Screenplays → Summary). Capture one or more
  screenplay setups — the checked screenplays and their scene displayers, saved
  camera views, and per-entry movie options (resolution, format, frame rate,
  quality) — with **Save Screenplay**; each is recorded to a movie per data set,
  landing in that data set's folder in the archive alongside its reports, plots
  and scene stills. Batch profiles remember the saved screenplays, and **Express
  batch** records them too. A screenplay that fails to record is logged and
  skipped without aborting the rest of the archive.

### Improvements
- **Faster Settings dialog** — the dialog is now built once and reused, so every
  open after the first is instant (its ~12 pages no longer rebuild each time);
  and cancelling no longer re-applies the app theme (a few-hundred-ms whole-app
  restyle) unless a live preview actually changed the appearance.
- **Faster close** — closing the app no longer freezes while it re-saves the
  crash-recovery cache; the save now runs off the GUI thread (the window closes
  immediately and the write finishes in the background). For a large workspace
  this removes a multi-second stall. The cache is also written atomically (temp
  file + replace), so a quick relaunch never reads a half-written file.
- **Resizable Saved views pane** — on the Scenes and Screenplays tabs, a
  draggable divider now sits between the scene/screenplay list and the Saved
  views list, so you can rebalance how much height each gets. The two tabs
  remember their divider position independently, and it persists across
  restarts.
- **Consistent right-panel width** — all four centre tabs share one panel
  width, reserved for the widest tab (Screenplays), so switching tabs never
  nudges the divider. The destructive "Clear scenes / Clear screenplays" button
  sits beside Clear.
- **Selected file dot stays visible** — a selected row in the Files tree now
  draws its leaf node dot in the accent's contrast colour instead of the same
  hue, so it no longer blends into the selection highlight.
- **Single menu/title bar (STAR-CCM+ style)** — the main window is frameless
  with one fixed top bar: the StarPost badge and menu items (Run batch, Export,
  Settings) on the left, and the version plus integrated minimise / maximise /
  close buttons on the right, all in one line. The bar is menu-bar styled (flat
  items, subtle hover, no chrome fill) on the dark/light theme background; the
  window buttons sit flush in the corner and close turns red on hover. Dragging
  the bar moves the window, double-clicking it maximises, and pressing near an
  edge resizes — all via the window manager, so native snapping is preserved.
  The version wordmark is a muted gray, as before.
- **Run batch dropdown auto-closes** — the hover-opened Full Batch / Express
  batch menu now closes itself once the pointer moves well away from it, instead
  of lingering until clicked; moving onto another toolbar item (Export, Settings,
  …) closes it immediately.
- **Screenplays first-time warning** — reworded to state that a movie can take
  several minutes to fully render, and raised the recommended memory floor to
  **32 GB**.
- **Recording feedback on the fast path** — during a screenplay's native
  STAR-CCM+ record, the progress bar now shows an indeterminate
  "Recording <name>…" busy animation, so the app clearly signals it is working.
  (The native record renders every frame silently in batch — STAR reports frame
  progress only to its GUI, which is absent here — so a real per-frame count
  isn't available on that path; the slower frame-by-frame fallback keeps its
  exact per-frame bar.)

## [2.3.0] — 2026-07-07

### New Features
- **Screenplays tab** — a new centre tab (after Scenes) that records STAR-CCM+
  screenplays to movie files. Screenplays are discovered during normal
  extraction (no extra license checkout); the selection panel's Screenplays
  tree mirrors the Scenes tree (checkable screenplays with their scene's
  scalar/vector displayers), and the shared **Saved views** list records one
  movie per screenplay × view. **Record** runs off the GUI thread, one license
  checkout at a time. Gallery tiles show a poster frame with a play badge;
  double-clicking opens the movie in the system video player.
- **Settings → Screenplays** — movie resolution (1080p/2160p), container
  (MP4/AVI/MOV), frame rate, encoder quality, and screenplays-per-license
  checkout batching.
- **Recording progress** — while a screenplay records, the progress bar
  advances with every rendered frame, not just per license checkout.

## [2.2.0] — 2026-07-06

### New Features
- **Express batch** — the toolbar **Run batch** button is now a hover dropdown
  with **Full Batch** (the full wizard) and **Express batch**, a lean window for
  users who already have a saved batch profile: pick the profile and sources, set
  the archive options, and run. Batch profiles now also remember the report
  format, "include units", and "combined report" settings.

## [2.1.1] — 2026-07-05

### New Features
- **Run batch → Summary** — the *Archive format* selector now works: batches can
  be packed as **ZIP** or **7Z**. The unavailable **RAR** option has been removed.

## [2.1.0] — 2026-07-01

A refinement release polishing the Files-tab appearance and the Run batch
dialog's saved plots/scenes.

### New Features
- **Node-dot colour** — the Files-tab leaf node dots now follow the theme
  accent by default, with a new **Settings → Appearance** option ("Node dots"
  match-theme toggle + "Node colour" picker) to set them independently, mirroring
  the checkmark-colour controls.
- **Run batch → Scenes tab** — saved scenes gain a right-click **Properties**
  (image resolution/format, saved views, and each captured scene with its
  scalar/vector displayers) and **Delete**, matching the Saved Plots menu.
- **Run batch → Summary tab** — the plots and scenes lists carry the same
  right-click **Properties / Delete** menu; deleting there also removes the entry
  from its source Saved list.
- **Run batch → Plots tab** — a new **Preview** action on saved plots loads the
  captured settings (title, axis labels, sizes, theme, legend, line width, grid,
  format, monitor selection and colours) back into the controls and the live
  preview.
- **Settings → Profiles** — a new **Batch profiles** section lists saved
  Run-batch selections with **Show Details** (reports, saved plots and scenes)
  and **Delete**, alongside the existing report/plot profiles. In the details
  window, right-click a saved plot or scene for **Properties** to view its
  captured contents.
- **Run batch → Summary tab** — a new **"Include dataset .csv"** export option:
  when ticked, each data set's portable StarPost CSV (the same file the Data
  tab's **Export Data** button writes) is added to its folder in the output
  archive, ready to re-import.
- **Run batch → Reports tab** — a new **"Combined report"** option (on by
  default): as well as each data set's own report in its folder, one report
  combining every data set (a column per sim) is written at the archive root.
- **Multi-select in lists** — selectable lists (the scene gallery, the Files /
  Data trees, and the Run-batch and Profile-details lists) now support
  **Shift+click** to select a range and **Ctrl+click** to toggle items, matching
  common desktop behaviour.
- **Shift+click to tick a range** — in the checkbox lists (Data tab, the
  report / monitor / plot / scene selection lists, the export dialogs and the
  region-statistics list), clicking one item then Shift+clicking another now
  ticks (or unticks) every item between them, matching the anchor's state.

### Changes
- **Faster startup** — the table library behind the comparison view (a ~0.4 s
  import) no longer loads while the main window opens; it loads the first time
  a comparison table is actually shown. The Java-macro templating engine is
  likewise deferred until a run actually starts, and the plot view (whose
  graphics libraries are another ~0.3 s of imports) is now built in the
  background right after the window first appears. Altogether the window shows
  in roughly a fifth of the time it previously took.
- **Faster plot redraws** — changing which data sets, plots or monitors are
  shown now draws the plot once instead of twice, roughly halving the delay
  after each click (also in the Export and Run batch previews and the batch
  plot rendering).
- **Faster empty-monitor filtering** — each monitor's magnitude is now scanned
  once and remembered, instead of re-checking every data point on every redraw
  and selection change (noticeable with hundreds of thousands of points).
- **One refresh per burst of changes** — rapid checkbox changes (most notably a
  Shift+click range tick, which used to redraw the views once per item) are now
  collapsed into a single refresh at the end of the burst.
- **No hidden plot redraws** — the monitor plot no longer re-renders while the
  Reports or Scenes tab is in front (it redraws when the Plots tab is next
  opened), so report and data-set toggles respond much faster on large
  workspaces.
- **No more freezes when the workspace saves** — the crash-recovery cache is
  now written in the background (previously the interface stalled for a
  fraction of a second when deleting, importing or clearing data, when scene
  renders finished, and during each batch file's checkpoint).
- **Less work per plot redraw** — each monitor's data points are converted for
  drawing once and reused, instead of being re-converted on every redraw.
- **The window opens before the cache loads** — restoring a large workspace's
  crash-recovery cache now happens just after the main window appears instead
  of before it, and a cache that fails to parse is skipped (with a log entry)
  rather than blocking the launch.

### Bug Fixes
- **Run batch saved-plot legend position** — a saved plot's legend position is
  now applied reliably when the batch renders it (and when a saved plot is
  reloaded via **Preview**), instead of occasionally snapping back to the
  default corner: the position is read/restored only once the plot area has its
  final size, rather than while its layout may still be pending.
- **Plots tab monitor list** — clicking a monitor group or monitor **name** now
  toggles its checkbox (previously only the small checkbox itself responded),
  matching the app's other checklists.
- **Scene Properties** — long **Vector/Scalar name** values now wrap onto
  further lines instead of stretching the window ever wider, in both the
  rendered-scene Properties (main UI) and the Run batch saved-scene Properties.
- **Scene rendering** — a scene with more than one visible scalar/vector field
  no longer joins every field name into the still's file name (which could make
  the name too long); it now uses **"multiple-fields"** instead. The full field
  list is still recorded and shown in the still's Properties.

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
