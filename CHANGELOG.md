# Changelog

All notable changes to StarPost are recorded here. Versions follow the
`MAJOR.MINOR.PATCH` scheme; the newest release is listed first.

## [Unreleased]

### New Features
- **Convergence tool.** Tools → Convergence assesses whether each loaded data
  set has converged, for steady runs. It reports a state (converged, still
  converging, stalled, diverged, drifting), a High/Medium/Low confidence with
  the rule that produced it, a convergence index, the binding constraint, and a
  list of reasons with suggested actions and an estimate of the iterations
  remaining. Residual health, remaining iterative error and the engineering
  quantities are assessed separately and then combined; residuals can veto a
  verdict but never certify one on their own, so a run left with no usable
  residual history is held at "still converging" rather than reading as
  converged. The Monitors table's Tolerance column shows its '%' suffix, and
  the QoI-gates table's Iterative error column shows the value the gate was
  actually decided on (including "unbounded", or the largest single-iteration
  change) instead of a blank dash whenever the geometric-tail estimator
  declined but the gate still bound the verdict. A new advisory flag,
  AUTOCORRELATION_UNRELIABLE, fires when a monitor's decorrelation estimate
  does not meet its own validity assumption. A second new flag,
  ITERATIVE_ERROR_UNBOUNDED, fires whenever a primary monitor's geometric-tail
  estimator declined for any reason (no structure to extrapolate, too little
  data, or genuine stagnation): the monitor can still pass, and a reason names
  it, since the remaining iterative error was never actually bounded.
  Confidence is capped at Medium only when that monitor is also still moving
  at an appreciable fraction of its tolerance — a settled monitor barely
  moving keeps its High rating, because the estimator declines for every
  noisy signal and a cap that always fires would carry no information. The static-monitor
  escape hatch's denial (for a monitor creeping toward its asymptote with
  noise on top) now measures how far the monitor has moved across its whole
  record rather than within the trailing window alone, which no longer
  under-reads the remaining approach as the creep rate approaches one. A data
  set or monitor set with no residual (or QoI monitor) history at all is no
  longer treated the same as one where that evidence existed and was then
  destroyed by an integrity failure — the former can still reach CONVERGED,
  with a reason noting the verdict rests on the other evidence alone, while
  the latter still holds the verdict at "still converging". Unsteady runs are
  reported as not yet supported rather than assessed with steady tests; a run
  whose solver regime cannot be determined at all is refused the same way,
  since assessing an unknown regime as steady would risk a confident wrong
  answer on a case that may actually be transient. A **Residual drop** control
  sits under the tolerance selector: 3 decades is the published ASME
  requirement and the default, but whether a run whose loads are settled well
  inside tolerance counts as converged with a shallower residual drop is an
  engineering judgement, so the requirement is yours to set. Turbulence
  equations keep their weaker bar and are never held to a stricter one than the
  primary equations. Reads cached data only —
  no STAR-CCM+ re-run.
- Extraction now records solver precision, residual normalization mode, and the
  unsteady solver parameters. Convergence assessment refuses a data set
  outright — rather than assessing it at reduced confidence — when its solver
  regime cannot be determined at all; a cached result or portable CSV old
  enough to carry no properties whatsoever falls into that case and needs
  re-extraction before it can be assessed.
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

### Fixes
- **Convergence tool: a well-settled run is no longer reported at Low
  confidence for a reason its own gate had already dismissed.** The
  window-adequacy gate has a relaxed route, because its "at least 20
  independent samples" requirement is unsatisfiable on a very smooth monitor —
  smoothness *is* high autocorrelation — and that route instead measures the
  thing the requirement stands in for: whether the mean is known to well
  inside tolerance, and whether the preceding stretch of the run agrees with
  it. The confidence rule then applied the original sample-count floor
  regardless, so a monitor that had just been forgiven on that number was
  still marked down for it. On a real 2500-iteration export that produced
  "converged, Low confidence — only 5 effective samples" while both of its
  primary monitors cleared the gate with margins of 4.4 and 2.4. The floor
  still applies in full to any monitor that did not need the relaxation, and a
  monitor that only barely clears it is still reported as marginal.
- **Convergence window: editing is no longer laggy.** Every edit — a checkbox,
  a tolerance keystroke, a residual-drop step — re-ran the full assessment of
  *every* loaded data set on the GUI thread. With ten data sets loaded that was
  1.7 s per edit, and because a spin box emits a change per keystroke, typing
  a four-digit tolerance ran four complete passes and froze the window for
  close to seven seconds. Two things changed. The expensive per-monitor
  statistics (the Theil-Sen slope and the Mann-Kendall trend test, together
  81% of a pass) are now memoised on the data they are computed from: they do
  not depend on the tolerance or residual-drop values being edited, so the
  same numbers were being recomputed from scratch on every keystroke. And the
  two spin boxes now wait for a pause in typing before re-assessing, instead
  of firing on each digit. Ticking a checkbox went from 1.7 s to 0.19 s;
  typing stays responsive throughout and settles about 1.2 s after you stop.
  No verdict changes — the cached statistics are identical, which is checked
  against all ten reference data sets.
- **Disabled fields and their labels now actually look disabled.** The
  Convergence window's custom-tolerance box is only live when the Tolerance
  preset is *Custom*, but it and its "Custom" label rendered exactly like the
  editable rows above and below, so the greying was invisible and the field
  looked editable. Two theme rules were missing behind that: the stylesheet's
  unconditional label colour also painted disabled labels at full brightness,
  and spin boxes had no disabled styling at all. Both are fixed app-wide, in
  the light and dark themes, so the license-mode rows in Settings and Welcome
  — which have always disabled their labels alongside their fields — now grey
  too. Purpose-coloured labels such as the tab hints are unaffected.
- **Convergence tool: the auto-primary default now prefers an aggregate
  monitor over its per-element siblings.** A monitor whose name matches a
  force keyword (force, drag, lift, moment, cd, cl) is auto-marked primary
  when the user hasn't set it by hand, and primary monitors alone gate the
  headline verdict. A data set that reports both a total ("Downforce ALL")
  and its per-element contributors ("Downforce wing front 1", "Downforce
  wing rear 1", ...) matched every one of them, so the verdict rode on
  whichever sub-component happened to be noisiest — a real 40-monitor
  car-aero run had 36 primaries and its headline state was set by
  `Downforce undertray Monitor` rather than the `Downforce ALL Monitor` the
  engineer actually cared about. Auto-selection now prefers monitors whose
  name matches a new, configurable aggregate keyword (ALL, Total, Sum,
  Overall, Combined — `plot_classification.aggregate_keywords` in Settings,
  matched as a whole word so "Wall" doesn't match "ALL") among the
  force-keyword matches; when at least one aggregate is detected, only the
  aggregate(s) are primary and the per-element monitors are still assessed
  and can still raise warnings, they just don't gate. When no aggregate is
  detectable, every force-keyword match is primary, exactly as before. A new
  INFO reason names which monitors were auto-selected and why (or that no
  aggregate was found and every match was kept), and a user can still tick
  or untick any monitor by hand in the Convergence window, which overrides
  the auto choice either way.
- **Convergence tool: an oscillating residual no longer reads as DIVERGING.**
  The sustained-growth rung fit only the last 50 iterations and trusted its
  slope regardless of fit quality; on a residual that oscillates around a
  plateau, that window lands on whatever phase the record happens to end on,
  so the slope was oscillation phase, not trend (r^2 as low as 0.03), and
  whether DIVERGED fired depended on where the run happened to stop. The
  slope is now trusted only when the tail fit actually explains the data
  (new `s_div_min_r2` threshold, default 0.5); genuine divergence, which
  fits cleanly, is still caught within 50 iterations as before.
- **Convergence tool: an oscillating residual could still misfire as
  DIVERGING even with the r^2 floor above.** The floor alone was
  insufficient: a half-cycle of an oscillation is itself well fitted by a
  straight line, so its r^2 lands wherever the phase happens to put it — a
  real STAR-CCM+ run measured tail-fit r^2 as high as 0.61 on residuals that
  were only oscillating about a flat plateau, well above the 0.5 floor, and
  the run's terminal state read DIVERGED though nothing was diverging.
  Sustained growth now also requires the tail window's median to have
  shifted relative to the block immediately preceding it (new
  `s_div_level_ratio` threshold, default 3.0): an oscillation returns to its
  prior level, a genuine divergence does not. Measured across 18 real
  oscillating residual series the worst level-shift ratio was 1.71; a 0.05
  decades/iteration synthetic divergence measured 10.6, so 3.0 separates the
  two comfortably. Divergence growing slower than ~0.02 decades/iteration is
  not separable from oscillation within one 50-iteration window and is left
  to the growth-vs-reference rung to catch as it continues.
- **Convergence tool: the convergence index no longer collapses to a false
  0.00.** Whenever a primary monitor's remaining iterative error could not
  be bounded at all, the index arithmetic divided by infinity and always
  landed on exactly 0.0 — indistinguishable from a monitor that was
  genuinely measured and found hopeless, and the first thing a real run
  exposed as "the tool looks broken". The index is now the worst *finite*
  margin among primary monitors; a new `unbounded_primary_count` field on
  the assessment records how many monitors could not be bounded, the
  binding-constraint string names the true worst offender and says so when
  it is one of them, and the index is `None` (not 0.0) only when every
  primary monitor is unbounded. The Convergence window's verdict card,
  summary table and per-monitor gate table all render this honestly instead
  of printing a misleading "0.00".
- **Convergence tool: an unbounded gate no longer erases a monitor's four
  other good margins.** The previous fix excluded an unbounded *monitor*
  from the run-level index, but `MonitorAssessment.margin` itself was still
  the minimum over all five of that monitor's gates — and an unbounded
  gate's margin is exactly 0.0, so it still overwhelmed the other four,
  perfectly measurable margins whenever every primary monitor had one. Two
  of three real runs hit exactly this: every primary monitor had a good
  drift, band, two-halves and window margin, yet the index still reported
  "None" because the iterative gate alone was unbounded on all of them. A
  monitor's margin is now the minimum over only its finite-valued gates, so
  the run-level index is once again simply the worst primary monitor's
  margin. `unbounded_primary_count` and the ITERATIVE_ERROR_UNBOUNDED flag
  are unchanged, and the binding-constraint string is tighter: it names the
  monitor and gate compactly, adding "(iterative error unbounded)" as a
  short suffix only when the worst monitor is itself one of them, instead of
  a full sentence.
- **Convergence tool: RESTART_SUSPECTED no longer fires on a single
  turbulence spike.** The restart heuristic flagged any single-iteration
  ratio above 10x on any residual, including turbulence equations (Tke,
  Sdr, ...), which spike by nature; a real run tripped it on one 31x Sdr
  spike with a strictly increasing iteration index and no restart at all.
  The check now only considers primary-class equations, and requires the
  jump to persist (the median of several following samples must still sit
  above the pre-jump level by the same factor) rather than firing on a
  single sample that returns to baseline right after.
- **Convergence tool: a residual no longer reads CONVERGING on a slope with
  no explanatory power.** The state ladder's last rung trusted the
  main-window fit's slope outright once it crossed `-s_flat`, with no check
  on how well that fit explained the data — the third occurrence of a
  pattern this tool has now hit three times (a rho, then a divergence
  slope, now a convergence slope, each trusted past a threshold with no
  fit-quality condition). A real run had four primary residuals all flat
  within their own noise (r^2 <= 0.02) with three landing STALLED and the
  fourth reading CONVERGING purely because its noise-driven slope crossed
  the threshold by 0.000019, producing both an inconsistency between
  equations doing the same thing and a false claim of progress ("still
  converging at 0.01 decades per 100 iterations") extrapolated from a fit
  explaining under 2% of the variance. CONVERGING now also requires the
  main-window fit to clear a new `s_conv_min_r2` threshold (default 0.5,
  shared with the `iterations_to_target` projection gate so the state and
  the projection cannot disagree); below it the residual falls through to
  the same STALLED/PLATEAU_LOW split its flat siblings use. Checked against
  a synthetic decay with realistic per-iteration noise (r^2 in the 0.5-0.8
  range) to confirm the floor does not reject a genuinely converging-but-
  noisy residual, only ones with no resolvable trend at all.

## [2.7.0] — 2026-07-25

### New Features
- **Legend panel** — the plot legend now sits on a panel filled with the plot's
  own background colour (white on light plots, near-black on dark plots) that
  hides the grid and curves behind it, like STAR-CCM+'s legend. Its opacity is
  adjustable under Settings ▸ Plots ▸ *Legend opacity* (default 80%) and
  per-export via the *Legend opacity* slider in the Export and Run batch
  dialogs — at 100% the panel is fully opaque (nothing shows through), at 0%
  completely see-through. A thin light-gray border outlines the panel so its
  edge stays clear even when the fill is transparent.
- **Reports & Monitors trees in the Properties window** — the General tab now
  lists a data set's reports and monitors as browsable, expandable trees
  instead of bare counts. Reports show by name; monitors are grouped as
  plot ▸ series, matching STAR-CCM+'s own structure. File size and Iterations
  stay as a summary above them. Reads cached data only — no STAR-CCM+ re-run.
- **Part Search window** — Tools → Part Search opens a searchable window: type
  part-name text into the search bar and the list of loaded data sets filters
  to only those containing a matching part, expanded to show which parts
  matched. Double-click any row to open that data set's Properties. Reads
  cached part data only — no STAR-CCM+ re-run.
- **"Tools" menu in the top bar** — a new toolbar dropdown sits between Export
  and Settings, with entries for Correlation, Convergence, and Part Search.
  Correlation and Convergence are UI scaffolding only for now; Part Search is
  functional (see above).
- **Unit conversion for reports and monitor plots** — Settings → Reports and
  Settings → Plots each gain a "Unit system" dropdown (Default / SI /
  Imperial) applied to the live views (reports table, including comparison
  mode, and monitor plots with a converted Y-axis label). The Run-batch
  window adds a global reports unit system and a per-plot unit system saved
  with each plot; express-batch honours the saved reports unit system too.
  Conversion is display/export-only — cached data stays raw, and unknown or
  dimensionless units pass through unchanged. Covers force, moment, pressure,
  mass/volumetric flow, velocity, temperature, mass, power, energy, length,
  area, volume, density, and angular velocity.

### Improvements
- **Unbuilt Tools entries marked "(coming soon)"** — Tools ▸ *Correlation* and
  *Convergence* have no implementation yet, so they now read
  "Correlation (coming soon)" / "Convergence (coming soon)" and are greyed out
  instead of looking like working entries that do nothing when clicked.
- **Smaller default legend** — plot legends now draw at 75% of pyqtgraph's
  natural size, taking up roughly half the plot area they did before. The
  Export and Run batch dialogs open their *Legend scale* sliders at the same
  size, so what the plot window shows is what they render; the sliders still
  reach the old sizes, and already-saved batch plots keep the size they stored.

### Fixes
- **No stray legend box on an empty plot** — the legend is hidden while nothing
  is plotted, instead of leaving a small empty box on the plot beside the
  "Select a monitor to begin" hint. It reappears as soon as a monitor is shown.
- **Selected folder icon now inverts** — in the Files and Data tabs, a selected
  folder's icon recolours to the accent's contrast colour (like its name)
  instead of keeping its same-hue silhouette, so it stays legible on the accent
  highlight. Mirrors the leaf node dot's selected variant.

### New Features
- **Screenplay recording length & start time** — Settings → Screenplays gains
  "Start time (s)" and "Animation length (s)" (Auto = each screenplay's own
  length, matching STAR-CCM+'s Write Animation dialog). The run-batch window's
  screenplay options carry the same two fields, and "Save Screenplay" captures
  them per saved screenplay. Recordings now always start at the configured
  start time (default 0) rather than the screenplay's preferred start time.

## [2.6.0] — 2026-07-17

### New Features
- **Sim properties captured at extraction** — loading a .sim now also records
  the simulation's own metadata: solution state (iteration, physical time,
  CPU/elapsed time), mesh cell/face/vertex counts, regions with their
  boundary-type breakdown and physics continuum, physics models per continuum,
  solvers and stopping criteria, the mesh-operation pipeline (meshers, base
  size, surface sizes, prism layers), the Geometry ▸ Parts tree (top-level
  parts plus every leaf part with its tree path), interfaces, tags, and
  the STAR-CCM+ version used. Everything rides the same single extraction
  pass (no extra license checkout), survives restarts via the crash-recovery
  cache, and is included in portable data-CSV exports. **Note:** portable data exports are
  now format v3 — older StarPost releases cannot import them; v2 files still
  import fine.
- **Properties window: Parts, Mesh, Regions and Physics tabs** — the per-sim
  Properties window (Files and Data tabs) is now tabbed. **General** keeps
  the classic size/reports/monitors/iterations summary; **Parts** shows the
  sim's Geometry ▸ Parts tree — composites, nested sub-assemblies and every
  leaf part with its surface and curve counts — sorted like STAR-CCM+'s own
  tree; **Mesh** shows the cell/face/vertex counts and the mesh-operation
  pipeline with each operation's meshers and key sizes; **Regions** lists
  each region's physics continuum and boundary-type breakdown plus the
  interfaces; **Physics** lists each continuum's enabled models, the solvers
  and the stopping criteria. Everything is read from the extracted sim
  properties — data sets extracted before this version show a re-extract
  hint instead.

### Improvements
- **Click a highlighted item to un-highlight it** — clicking an
  already-selected row in any list, tree or table (the Files/Data tabs, the
  Reports table, galleries, dialog lists…) now clears the accent selection
  highlight, so it no longer lingers on the last-clicked item with no way to
  remove it. Everything else about clicking is unchanged: Ctrl/Shift
  multi-select, dragging, double-click actions, right-click menus and
  checkbox ticks all behave as before, and navigation lists that need a
  permanent selection (the Settings dialog's group list) are unaffected.

### Bug Fixes
- **No more stray CSVs in the output folder** — loading .sim files no longer
  litters the default output folder (or the home folder) with the extraction's
  intermediate files: the per-plot CSVs, the reports table and the
  scene/screenplay/view index CSVs the STAR-CCM+ macro exports. Extraction now
  writes them to a temporary scratch folder it cleans up after parsing; only
  files you explicitly export end up in your output folder. (Existing stray
  files can simply be deleted — they are not read back.)
- **Crisp text in exported plots** — the title, axis and legend text in
  exported plot images is now rendered with plain grayscale antialiasing.
  Previously the capture baked the screen's RGB-subpixel hinting into the
  image, leaving colour fringes on every glyph that read as blur when the
  image was viewed at any other scale. The grid, ticks and axis frame also
  keep their subtle hairline weight at every export resolution rather than
  thickening with it.
- **Exported plots match the preview** — plot images (Export menu, Run batch)
  now render their curves at the same relative thickness as the plot preview.
  The high-resolution capture scaled everything except the lines (drawn with
  cosmetic pens, which keep a fixed pixel width), so an exported plot's lines
  came out three times thinner than the preview showed.
- **Data tab folders survive a restart** — data sets filed into the Data tab's
  virtual folders no longer fall out to the top level when StarPost restarts.
  Startup refreshed the tab once before the crash-recovery cache had loaded,
  and that momentarily-empty pass erased the saved folder memberships.

## [2.5.0] — 2026-07-13

### New Features
- **File menu** — a new **File** dropdown sits first in the top bar (before
  Run batch), offering **Add ▸ Files… / Folder…** (the Files tab's add
  dialogs), **Import data…** and **Export data…** (the Data tab's
  portable-CSV import/export) — the same operations, reachable without
  switching tabs.
- **Keyboard shortcuts** — the main views and actions now have hotkeys, shown
  in menus and tooltips (hover a tab or button to see its key):
  **F1**/**F2** switch the left panel to Files/Data; **1**–**4** switch the
  centre tabs (Reports, Plots, Scenes, Screenplays); **Ctrl+Shift+B** /
  **Ctrl+Shift+E** open Full Batch / Express batch; **Ctrl+N** /
  **Ctrl+Shift+N** add files / a folder to the Files list; **Alt+Shift+I** /
  **Alt+Shift+E** import / export portable data CSVs; **Ctrl+Shift+A** /
  **Ctrl+Shift+D** select-all / clear the current checklist; **Ctrl+R** runs
  (Scenes) or records (Screenplays); **Alt+Shift+S** toggles Smooth data on
  the Plots tab; and in the Files list **Ctrl+L** loads, **Ctrl+P** shows
  properties, **Delete** removes (with the usual confirmation). The Files
  right-click menu's **Open** is now **Load file**, and it gains a **Remove**
  entry. The full list is in `docs/starpost_hotkeys.txt`.
- **Menu icons** — the File and Run batch dropdowns now show a small glyph
  beside each entry (add, import/export, play/fast-forward…), STAR-CCM+
  style. The glyphs follow the light/dark theme and the accent's contrast
  colour on the highlighted row.
- **Remove data sets from the right-click menu** — right-clicking a data set
  on the Data tab now offers **Remove** (shown with its **Delete** key, which
  also works whenever the data list has focus). It asks for confirmation,
  then deletes the selected data sets — like removing files on the Files tab.
- **Clear in the tab right-click menus** — the Files and Data tabs'
  right-click menus now end with a red **Clear** entry beneath the sort
  options; it asks for confirmation and empties the list. Hovering it inverts
  the entry to a red fill with white text, its take on the other items'
  highlight.

### Improvements
- **Menu-bar-style dropdowns** — the top bar's **File** and **Run batch**
  menus now open on click (no more hover-open) and stay open wherever the
  mouse goes; with one open, hovering the other menu button switches to it,
  and a click anywhere else dismisses it — like a traditional menu bar.
- **Tab button rows removed** — the rows of buttons beneath the Files list
  (Add files, Add folder, Remove, Clear) and the Data list (Import, Export
  Data, Delete, Clear Data) are gone; every action lives in the File menu,
  the right-click menus, or on a hotkey, leaving the panels' full height to
  the lists. One behavioural note: data deletion now acts on the *selected*
  data sets (right-click ▸ Remove or the Delete key) rather than the checked
  ones.
- **Saved views buttons removed** — the Saved views pane on the Scenes and
  Screenplays tabs no longer shows Select all / Clear; a render uses a single
  view, so bulk check/uncheck served no purpose.

### Bug Fixes
- **Window buttons** — the minimise / maximise / close buttons in the top-right
  corner now fill the title bar's full height; previously they sat centred with
  a small gap above and below, so their hover highlight didn't reach the
  window edge.
- **Open-menu button highlight** — the **File** and **Run batch** buttons kept
  their bright hover highlight while their dropdown was open instead of fading
  to the near-invisible pressed shade, so it's now clear which menu is active.

### Maintenance
- **Dead-code cleanup** — removed the orphaned batch stop machinery
  (`BatchWorker.request_stop` and the unused `JobState` / `Job.state` /
  `Job.message` fields, left behind when the non-functional "Stop after
  current" button was dropped), the unused `PlotView.monitor_selection`
  getter, and several unreferenced constants (`MAX_FILES`, `_TAGS`,
  `_TAB_NAMES`).

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
