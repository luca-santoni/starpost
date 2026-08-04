# Convergence tool — handoff notes

Working notes for anyone picking up the Convergence tool. Covers what exists,
what is known broken, which design decisions are load-bearing, and the traps
that have already cost time.

Current as of `main` at `ed8a7f4`, plus the unmerged branch
`fix/solver-precision-probe` (see §11). Full suite green
(`python scripts/run_tests.py`, 41 files); `ruff check .` clean.

**If you are picking this up on a different machine, read §10 first** — the
validation method these notes lean on depends on data files that live outside
the repo, and they will not be there.

---

## 1. What it is

**Tools → Convergence** assesses whether a solved *steady* STAR-CCM+ run has
converged, and if not, says why. It reads cached `SimResult` data only and
never re-invokes STAR-CCM+.

Output is never a bare boolean. Every verdict carries:

- a **state** — `CONVERGED`, `CONVERGED_MACHINE`, `CONVERGING`, `SLOW_DRIFT`,
  `STALLED`, `DIVERGED`, `UNSTEADY_UNSUPPORTED`, `INTEGRITY_FAIL`
- a **confidence** — High / Medium / Low, with the rule that produced it
- a **convergence index** — the worst primary monitor's margin; `>= 1` passes
- a **binding constraint** — the one string saying what to fix
- **advisory flags** and a **reasons list** with suggested actions

### Where the code lives

```
src/starpost/core/convergence/     Qt-free, STAR-CCM+-free analysis package
  stats.py        numeric primitives (OLS, Theil-Sen, Mann-Kendall, ACF, Student-t)
  models.py       output schema (dataclasses + enums)
  config.py       every threshold, each with [S]/[D] provenance
  metadata.py     SimProperties -> RunMetadata, with per-field provenance
  signals.py      preconditioning: integrity, restarts, classification, windowing
  residuals.py    layer 1 — residual health and the state ladder
  iterative.py    layer 2 — geometric-progression remaining-error estimate
  steady.py       layer 3 — the five QoI gates
  verdict.py      roll-up: state ladder, confidence, reasons
  __init__.py     assess(result, config, classification) — the only public entry
src/starpost/gui/views/convergence_dialog.py    the window
src/starpost/macros/extract_all.java.j2         propsConvergence section
```

`assess()` is the only entry point. Do not reimplement analysis in the GUI.

---

## 2. Read this first

**The mathematics comes from a theory specification that is NOT in this repo.**
Section references in code comments (`§5.4`, `§10.12`, …) point at that
document, which the user supplied as
`convergence_assessment_theory_spec` revision 2. Without it you cannot verify a
citation — that is expected, and an unverifiable `§` reference is not a defect.
What you *can* and should check is whether the code's own stated reasoning is
internally coherent.

The design doc **is** in the repo:
`docs/superpowers/specs/2026-07-25-convergence-tool-design.md`. It records
scope, the confidence rule, the state list and the deliberate omissions.

Three principles from that design are load-bearing. Do not quietly undo them:

1. **Residuals are necessary, never sufficient.** They can veto (`DIVERGED`,
   `STALLED`) but cannot certify. The verdict lives in the engineering
   quantities.
2. **Never claim more than the evidence supports.** Where a quantity cannot be
   determined, say so and degrade — do not guess. This is why `precision`
   is never derived, why an unbounded remaining error raises a flag, and why
   unsteady runs are refused rather than assessed with steady tests.
3. **Recommendations are the product.** "Not converged" is a diagnosis;
   "Continuity: only 1.1 of 3 required decades" is help.

---

## 3. Validation against real data

Ten real car-aero exports were run through the tool (steady coupled RANS,
K-Omega SST, 40 monitors each). This is the current state.

**The confidence column assumes precision is unknown**, i.e. these CSVs were
exported before §5.1's fix and still carry an empty `precision`. Re-exporting
them from the `.sim` files with the fixed macro moves `2500Iter_Bodywork` to
**High** and leaves the other nine unchanged. Every state and index in the
table is unaffected either way — those are the values to regress against.

| sim | state | conf | index | binding |
|---|---|---|---|---|
| 2500Iter_Bodywork | CONVERGED | Medium* | 2.383 | Drag ALL: window adequacy |
| FW-006-hood-tires | CONVERGING | Low | 0.261 | Downforce ALL: window adequacy |
| Baseline-RW-18-heave | SLOW_DRIFT | Low | 0.009 | Downforce ALL: band |
| SDM24 Rad-1-Shroud-Sus-v2 | STALLED | Low | 0.155 | Continuity: only 1.8 of 3 decades |
| SDM25-RW-014 | STALLED | Medium | 0.176 | Continuity: only 1.1 of 3 decades |
| SDM25-UT-007-212mm | STALLED | Medium | 0.090 | Continuity: only 1.5 of 3 decades |
| SDM25RWstudyslotgap15mm | STALLED | Low | 0.055 | X-momentum: only 1.4 of 3 decades |
| SDM25_RW_1_1_no_mesh_fixed | STALLED | Medium | 1.494 | Continuity: only 2.2 of 3 decades |
| SDM26-WindTunnel | STALLED | Low | 0.041 | Y-momentum: only 1.1 of 3 decades |
| SDM27-REDESIGN-UTONLY | STALLED | Medium | 0.094 | X-momentum: only 2.3 of 3 decades |

**Every one of those ten runs found at least one defect that synthetic tests
had missed.** If you change anything in the analysis layers, re-run all ten
before believing the unit tests.

### How to run real data without STAR-CCM+

The exports are portable StarPost CSVs in `/home/luca/Downloads/temp output/`
(user's machine; not in the repo). They load without STAR-CCM+:

```python
from pathlib import Path
from starpost.data.portable import read_sim_csv
from starpost.core.convergence import assess
from starpost.core.convergence.config import ConvergenceConfig
from starpost.core.settings import Settings

r = read_sim_csv(Path("/home/luca/Downloads/temp output/SDM25-RW-014@03000.csv"))
a = assess(r, ConvergenceConfig(), Settings().plot_classification)
print(a.state, a.confidence, a.convergence_index, a.binding_constraint)
```

`SDM25_RW_1_1_no_mesh_fixed` is the most instructive: its QoIs pass every gate
(index 1.49) while its residuals stall at 2.2 decades. It is the case that
proves the residual-veto behaviour and the residual-derived binding constraint.

`2500Iter_Bodywork` is the only run that reaches `CONVERGED`. Treat it as the
regression case for anything touching the window gate.

---

## 4. The recurring bug pattern — read before changing any estimator

**Five separate defects in this module had the same shape: a fitted slope or a
statistic was trusted as evidence without checking that the fit explained
anything.** Each one produced a confident wrong verdict, and each was found
only when real data hit it.

| where | symptom | guard now in place |
|---|---|---|
| `iterative.py` rho | white noise (r²≈2e-4) read as `ASYMPTOTICALLY_STAGNANT`, making every settled monitor un-passable | `min_fit_r2 = 0.10` |
| `residuals.py` divergence rung | an oscillation's rising limb (r²=0.03) read as `DIVERGING` | `s_div_min_r2 = 0.5` |
| same rung, again | r² alone was insufficient — a half-cycle of an oscillation genuinely fits a line (r²=0.61) | `s_div_level_ratio = 3.0` level-shift conjunct |
| `residuals.py` CONVERGING branch | a noise-driven slope crossing `s_flat` by 2e-5 labelled one equation `CONVERGING` while three identical siblings read `STALLED` | `s_conv_min_r2` |
| `steady.py` escape hatch | Mann-Kendall significance with no effect size refused monitors drifting at 1% of tolerance | `mk_trend_departure_fraction = 0.25` |

**If you add or change any slope-driven decision, pair it with a fit-quality
*and* an effect-size condition.** Significance alone is not evidence; a slope
from a fit that explains nothing is not a trend.

One place that looks like this pattern but is **not** a bug, already checked:
`GATE_DRIFT` uses an OLS slope with no r² guard, but it compares an effect size
in physical units. For white noise the projected drift is a constant ~74×
smaller than the band, so across 100 noise realisations it never failed while
the band passed. Leave it alone.

### The second pattern: fixes that open a neighbouring hole

Four consecutive fix rounds were each correct on the reproduction they were
given and wrong one step outside it. When you fix something here, **sweep the
parameter** (ρ, noise scale, period, record length) rather than testing the
single case that prompted the change. Several tests in this repo now do exactly
that, deliberately.

---

## 5. Open issues

Ranked by what a user would notice.

### 5.1 `precision` — RESOLVED. `auto_norm_sample_count` — still open

**Precision is captured now.** The old probe called `isDoublePrecision` on
`Simulation`, which has no such method (verified: `Simulation` exposes 144
methods and not one mentions precision). The accessor lives on
`star.common.SystemInformation`, reached via `Simulation
.getSystemInformation()`. Found by sweeping all 48,847 classes across the 143
STAR modules of a real 20.04.007-R8 install; `isDoublePrecision` appears in
exactly two of them, and only one is reachable from a Simulation.

Verified live: extracting `SDM27-REDESIGN-UTONLY.sim` now yields
`precision = 'double'`.

**Read what it measures carefully.** `SystemInformation` describes the server
*running the macro* — StarPost's extraction run — not the run that solved the
case. Nothing in the Java API records the latter. The two agree wherever one
build is installed (this machine has only the `-R8` double-precision build),
which is the normal case. At a site with both builds installed StarPost never
passes `-dp`, so it would extract in single and could report `single` for a
case solved in double — which would grant a false `CONVERGED_MACHINE`, the
strongest verdict this module makes. That is why the value is recorded with
`Provenance.DERIVED` rather than `EXTRACTED` (see `metadata._proxy_field`) and
why an INFO reason states where it came from. Do not "tidy" that to EXTRACTED.

Effect on the ten reference exports: only `2500Iter_Bodywork` changes, and it
reaches **CONVERGED / High** — the first High ever seen on real data. It took
both this and the window-relaxation confidence fix; either alone leaves it at
Medium.

**`auto_norm_sample_count` is still empty, and the reason is not yet known.**
The old probe called `getNormalizationIterations` / `getNumberOfSamples`, which
exist nowhere in the API. The right accessor is `getAutoNormalizeIndex()` on
`star.base.report.PlotableMonitor`, which `ResidualMonitor` inherits through
`ScalarMonitor`. That is now what the macro calls — and it *still* returns
empty on a real run.

What makes this odd, and worth recording rather than re-deriving: the macro
reaches those monitors through the same loop and the same
`simpleName(m).contains("Residual")` filter that `residualNormalizationOf`
uses, and that one succeeds (`residual_normalization = 'auto'`). Both
`getNormalizeOption` and `getAutoNormalizeIndex` are public methods declared on
the same public `PlotableMonitor`, called on the same objects. One works, one
does not, so the call is presumably throwing inside `invokeQuiet`, which
swallows it. Resolving it needs a diagnostic run that dumps the runtime class
and the actual exception — not another guess at the name.

Impact is second-order: the value sets how many leading samples form the
residual reference `r_ref`, and the reader falls back to STAR-CCM+'s own
default of 5.

### 5.2 A short record reads as `SLOW_DRIFT` when it is simply early

`Baseline-RW-18-heave` is 290 iterations with residuals dropping steeply
(r²≈0.9, ~1 decade per 100 iterations) — a healthy run stopped early. It
reports `SLOW_DRIFT`, which reads as pathological.

Cause: the window is `max(200, 0.2N)`, so on a 290-iteration record the window
is 200 samples — 69% of the run, including much of the initial transient. The
drift gate then correctly sees movement. The gate is not wrong; the *label* is
misleading.

Options: report `CONVERGING` when the record is too short for the window rule
to exclude the transient; or scale the window floor down for short records; or
add a `RECORD_TOO_SHORT` advisory. Not yet decided.

### 5.3 One uncovered regime: imperceptibly slow creep

A monitor creeping at ρ ≳ 0.999995 reads `CONVERGED`. Over a 3000-iteration
record it moves 0.13× tolerance while 10.9× remains — *less* movement than a
benign drift shows.

**This is not fixable from the record.** Distinguishing "flat because
converged" from "flat because creeping imperceptibly" requires the contraction
ratio, which is exactly what noise destroyed (it is why the estimator declined
in the first place). No statistic derived from that record recovers it.

It is made safe rather than closed: such a run always carries
`ITERATIVE_ERROR_UNBOUNDED`, is capped at Medium confidence, and the confidence
rule names why. Do not attempt to "fix" this by tuning a threshold — three
attempts failed and each opened a different hole.

### 5.4 Non-engineering monitors are assessed as QoIs

`Solver Iteration Elapsed Time Monitor` (a timing diagnostic in seconds) is
assessed like an engineering quantity. It is non-primary so it cannot gate the
verdict, but it produces reasons and occupies a row. There is no notion of
"this monitor is not a QoI" beyond the primary tick.

### 5.5 Deferred minor findings

Recorded during development, deliberately not fixed:

- `stats.py` — `theil_sen_slope`'s 2000-point subsampling branch is untested.
- `stats.py` — degenerate-input handling is inconsistent: `ols_fit` raises
  `ValueError`, `theil_sen_slope` and `mann_kendall` return neutral values.
- `signals.py` `_is_residual` — the keyword fallback fires for any non-RESIDUAL
  kind, not just the legacy `OTHER`. Benign today because `classify_plot` tests
  residual keywords first.
- `test_convergence_iterative.py` — no case with a *partially* masked change
  series (some zeros among positives), so a future misalignment of
  `index[positive]` vs `changes[positive]` would go uncaught.
- `iterative.py` — `_no_estimate`'s `safety_factor` default is unreachable.
- `metadata.py` — `auto_norm_sample_count` parses with bare `int()` while the
  `_int` helper uses `int(float(...))`; a macro-emitted `"5.0"` would fall back
  to the default.
- `config.py` — `d_min_advisory = 4.0` is declared and never read.
- `steady.py` — `two_halves_t` is computed but only used in detail text, not in
  the pass/fail decision. (This is per the design: gate 3 is the engineering
  test only. Noted so nobody "fixes" it by gating on the p-value.)
- Monitor identity is the bare series name. De-duplication is by name, so two
  *genuinely different* monitors sharing a name in different plots would
  collide. Not seen in real data.
- `binding_constraint` on a `CONVERGED` run names the *tightest passing* gate.
  Informative, but the word "binding" implies something is blocking.
- `export.py` `iterative_error_text` looks up its gate with an unguarded
  `next(...)`, matching the long-standing pattern in `verdict._gate`, so a
  hand-built `MonitorAssessment` lacking that gate would raise
  `StopIteration`. Unreachable via `assess_monitor`, which always produces
  all five gates.

---

## 6. Design decisions that must not be silently undone

Each of these looks wrong at first glance and is deliberate. All were arrived
at by finding the failure that motivated them.

**`INCOMPLETE_EVIDENCE` is raised unconditionally and excluded from the
confidence rule.** Phase 1 performs no global-conservation check, so the flag is
always true. Letting a permanently-true flag cap confidence would make High
unreachable and the level meaningless. The same trap was reintroduced twice
afterwards (by the unbounded-error cap, then by the empty-monitor logic) —
watch for it.

**A confidence cap must discriminate.** `ITERATIVE_ERROR_UNBOUNDED` fires on
essentially every noisy settled monitor, so it caps confidence *only* when the
monitor is also still moving at an appreciable fraction of tolerance
(`iterative_unbounded_confidence_fraction`). An unconditional cap made High
unreachable across every noise scale from 1e-6 to 1e-2.

**A perfectly static monitor must be able to pass.** Its all-zero change series
gives the estimator nothing to fit, so it declines. Failing the gate on that
would make a fully converged monitor permanently un-passable. The escape hatch
judges it on its largest single-iteration change instead —
`ASYMPTOTICALLY_STAGNANT` is deliberately excluded from that route.

**`D_N` is estimated from the *detrended* window.** A smooth settled monitor's
autocorrelation stays near 1 for hundreds of lags purely because of its trend,
so estimating from the raw window reports a handful of effective samples for
exactly the runs that converged best.

**The window-adequacy gate has a relaxed route.** The 20-independent-samples
requirement is a *proxy* for "is the mean known to within tolerance". On a very
smooth monitor it is unsatisfiable — smoothness *is* high autocorrelation. The
relaxed route requires all three of: the length floor; the CI half-width within
`window_relax_ci_fraction` of tolerance; **and** the preceding equal-length
block's mean agreeing within tolerance. That third condition is what still
refuses a brief flat stretch inside a slow oscillation — it is the guard, not
decoration.

**Margins exclude non-finite gates.** An infinite gate value would otherwise
drag a monitor's margin to exactly 0 and erase four good measurements, making
the convergence index a sentinel rather than a measurement.

**Turbulence equations are held to a weaker bar** (`d_min_turb`) and can never
force a verdict. When the user lowers `d_min` below the turbulence default, it
is clamped so turbulence is never *stricter* than the primary equations.

**Monitors that are exactly zero at every iteration are excluded.** In real
car-aero exports 14–29 of 40 monitors are parts not present in that
configuration. The rule is **exactly zero**, not a threshold: a 1e-5 threshold
would silently discard a monitor whose values are legitimately small. **Never
apply this to residuals** — `Sdr` sits at ~1e-6 in real data and would be
discarded.

**A relaxed window-gate pass is not re-punished in the confidence rule.**
`n_eff >= lambda_ind` is only ever a *proxy* for "is the mean known to within
tolerance", and the window gate's relaxed route measures that quantity
directly because the proxy is unsatisfiable on a very smooth monitor. So
`confidence_of` skips its `n_eff` floor for a monitor whose gate took that
route (`MonitorAssessment.window_relaxed`). Without this the tool contradicted
itself on the same number: `2500Iter_Bodywork`, the only CONVERGED run in the
reference set, read "CONVERGED / Low — only 5 effective samples" while both its
primary monitors passed that gate at margins of 4.40 and 2.38. The floor is
untouched for a monitor that never needed the relaxation, and a barely-relaxed
pass is still caught by the marginal-margin check.

**Aggregate monitors are preferred as auto-primary.** With 36 force-keyword
monitors, ticking them all made the headline hostage to the noisiest
sub-component rather than `Downforce ALL`.

**`MonitorConfig.is_primary` is tri-state, not a bool.** `None` means "no
opinion — let `_select_auto_primary` decide". Collapsing it back to a plain
`bool` silently kills the auto rule: the mere existence of a MonitorConfig
would again read as an explicit override, so editing one monitor's tolerance
would freeze its primary state as a side effect, and the Convergence window's
"Reset to auto" button would have no value to write. `_auto_primary_reason`
keys on the same distinction, so it would also stop naming monitors that carry
an unrelated override.

---

## 7. Threshold provenance

`config.py` carries every threshold with an `[S]` (sourced to the literature) or
`[D]` (design choice) tag, and a test asserts full coverage. Two `[S]` values
must not drift: `d_min = 3.0` (ASME JFE editorial policy) and
`safety_factor = 1.25`.

These were **calibrated against real data**, not taken from the source. If you
change them, re-run all ten exports:

| threshold | value | why this value |
|---|---|---|
| `min_fit_r2` | 0.10 | separates white noise (r²≈2e-4) from real geometric decay (r²≈1) |
| `s_div_min_r2` | 0.5 | necessary but insufficient on its own — see `s_div_level_ratio` |
| `s_div_level_ratio` | 3.0 | real oscillations shift level 0.82–1.71×; divergence at 0.05 dec/iter shifts 10.6× |
| `s_div_baseline_window` | 200 | baseline for the level-shift comparison |
| `mk_trend_departure_fraction` | 0.25 | creeping monitors sit at 0.42–0.53 of tolerance; false refusals at 0.006–0.15 |
| `iterative_unbounded_confidence_fraction` | 0.10 | static monitors sit at 0.00004–0.045; a genuinely moving one at 0.45 |
| `window_relax_ci_fraction` | 0.25 | a factor of 4 on the theory's own criterion; at 1.0 it admits an autocorrelated record whose mean is known only to 87% of tolerance, at 0.10 it refuses a real run known to 10.5% |

---

## 8. Testing

- **Run the full suite with `python scripts/run_tests.py`**, never a bare
  multi-file `pytest`. GUI tests share one `QApplication` and never dispose
  their widgets; the runner isolates each file in its own process. A single
  file via `python -m pytest tests/test_x.py` is fine.
- Prefix GUI tests with `QT_QPA_PLATFORM=offscreen`.
- Run the analysis tests with `-W error::RuntimeWarning`. Log-space work on
  data containing zeros is where stray numpy warnings appear.
- `tests/test_main_window.py` (109), `tests/test_shortcuts.py` (17) and
  `tests/test_plot_view.py` (30) intermittently fail under the parallel runner
  but pass per-file. **Re-run per-file before calling anything a regression.**
- To drive the real window headlessly, see `.claude/skills/verify/`. The app
  runs fully under `QT_QPA_PLATFORM=offscreen` and `QWidget.grab().save()`
  captures pixel-accurate screenshots. Looking at the rendered window found two
  defects the data structures hid (a 130-entry reasons list, and fabricated
  `1 (robust record range)` scales on empty monitors).

---

## 9. Deliberately not implemented

Phase 1 answers three of the theory spec's five questions. These are out of
scope by decision, not oversight:

- **Unsteady / statistically-stationary assessment** — no MSER or other
  initial-transient detection, no autocorrelation-corrected CI on a
  time-average, no slow-drift guard for stationary records, no periodic-content
  correction. Unsteady runs, and runs whose regime cannot be determined, are
  **refused** with `UNSTEADY_UNSUPPORTED`.
- **Global conservation check** (mass/energy imbalance) — hence the permanent
  `INCOMPLETE_EVIDENCE`.
- **Full limit-cycle confirmation** — the signature is detected
  (`OSCILLATORY_SUSPECTED`: no drift, wide band) but there is no periodogram and
  no `CONVERGED_OSCILLATORY` state.
- **`NONPHYSICAL` sentinel bounds** — needs user-supplied physical limits.
- **The evidence plot** with the trailing window shaded. (Export of the
  assessment itself is now implemented — see `core/convergence/export.py`.)
- **Restart detection is heuristic** — index resets are caught; a restart that
  continued the iteration count monotonically is not.

The highest-value future extension named in the theory spec: emitting a
field-max change of the primary solution variables from the macro (one scalar
per iteration) would unlock the *validated* L∞ iterative-error estimator instead
of the scalar analogue used here. StarPost already owns the macro path.

---

## 10. Environment — and what a new machine has to re-establish

Everything in this section is about the *development machine*, not the repo.
None of it moves with a `git clone`.

### 10.1 What breaks immediately on a new machine

**The ten reference exports.** §3's table, and every "re-run all ten before
believing the unit tests" instruction in these notes, depends on portable
StarPost CSVs that were kept at `~/Downloads/temp output/` on the original
machine. They are **not in the repo** (they are customer geometry, and large).
Without them the validation method these notes prescribe does not exist.

**Keep them in a folder that is not `default_output_dir`.** On the original
machine both were `~/Downloads/temp output/`, so an assessment export dropped
`convergence-assessment-*.csv` straight in beside the ten reference files — and
`read_sim_csv` then raises `not a StarPost data export` on the first one it
globs, which reads like a regression in the tool rather than a stray file.
Either point exports somewhere else or glob defensively:

```python
files = [p for p in sorted(ref_dir.glob("*.csv"))
         if not p.name.startswith("convergence-assessment-")]
```

Re-establishing it is the first thing to do on a new machine, in order of
preference:

1. Copy the same ten CSVs across. They are the calibration set every threshold
   in §7 was measured against; substituting different runs silently changes
   what "unchanged" means.
2. Failing that, export a fresh set from real solved cases via the Data tab and
   **re-record §3's table from scratch**, marking it as a new baseline rather
   than pretending it is comparable to the old one.
3. Failing both, the unit tests still pass and still catch a lot — but §4 is
   explicit that every one of the ten real runs found a defect the synthetic
   tests had missed. Treat "unit tests green" as much weaker evidence than
   these notes elsewhere assume.

**The `.sim` files.** Eleven solved cases sat at `~/Downloads/sim files/`.
These are what let a macro change be verified end to end (§11.2 did exactly
that for the precision probe). Without at least one, any macro change is
unverifiable beyond "the accessor exists in the jars".

**The STAR-CCM+ install.** Was `/opt/Siemens/20.04.007-R8/`, **not on PATH**,
and configured in StarPost via `starccm_path` in `settings.yaml`. Note the
`-R8` suffix: that is the double-precision build, and it was the only one
installed. That matters for §5.1 — on a machine with both builds present, the
precision StarPost reports can differ from the precision a case was solved at.

### 10.2 Local conventions that were machine-specific

- No system pip/venv; the venv was at `.venv/` with pip bootstrapped via
  `get-pip.py`, so commands used `.venv/bin/python` explicitly. On a machine
  with a normal Python this is unnecessary — but check before assuming.
- `/tmp` was a 16 GB tmpfs. It filled at least twice during development
  (once from Chrome temp files, once losing the session scratch directory
  mid-run). Two consequences worth keeping in mind anywhere: `ENOSPC` from
  tool calls means check `df /tmp` before believing the error, and
  `QPixmap.save()` returns `False` silently when its target directory has
  vanished — a screenshot step can report success and write nothing, so check
  the return value.

### 10.3 Reading the STAR-CCM+ Java API without documentation

§5.1 was resolved by reading the installed jars directly rather than the
Simcenter help. The recipe, since it will be needed again:

```bash
JAVAP=<install>/jdk/*/bin/javap
JAR=<install>/star/lib/java/platform/modules/ext/starbase.jar
$JAVAP -cp "$JAR" star.common.Simulation | grep -i <thing>
```

To sweep for a name whose owning class is unknown, extract the module jars and
grep the class files:

```bash
for j in <install>/star/lib/java/platform/modules/ext/*.jar; do
  mkdir -p "$(basename $j .jar)" && (cd "$(basename $j .jar)" && unzip -qq -o "$j" '*.class')
done
grep -ral "<methodName>" .        # the -a is not optional
```

**The `-a` is the trap.** `grep -r` silently skips binary files, so a sweep
without it returns zero matches for names that are definitely present. That
produced a confident wrong "there is no such accessor anywhere" during the
§5.1 investigation. **Always run a positive control** — grep for a name you
know exists (`Simulation`, `getMonitorManager`) and confirm it returns
non-zero — before trusting any negative result from this method.

---

## 11. State of play at the machine handover

### 11.1 Unmerged work

`fix/solver-precision-probe` (`5c54043`) was complete, tested and verified
against a real run, but **not merged and not pushed** at handover — and §10 to
§12 of this document were written on that same branch. So if you are reading
these three sections at all, the branch survived. If §5.1 instead still
describes precision as permanently unknown, the branch was lost in the move and
the fix needs redoing; §5.1's history records what it changed and how the
accessor was found.

### 11.2 What was proposed and not built

These were the ranked options at handover. Ranking is by user value, and the
evidence behind each is in the section named.

| # | change | value | effort | risk | see |
|---|---|---|---|---|---|
| 1 | **Evidence plot** — monitor history with the trailing window shaded and the tolerance band drawn. The one part of the assessment that still cannot leave the screen; also the fastest way for an engineer to sanity-check a verdict. | High | Medium | Low | §9 |
| 2 | **`SLOW_DRIFT` on a too-short record** — a healthy run stopped early is labelled pathological. | Medium | Small–Med | **Medium** — a state-ladder change, and §4 records that this module's state changes have repeatedly been right on their reproduction and wrong one step outside it | §5.2 |
| 3 | **Run-batch integration** — fold a convergence report into the toolbar wizard's `.zip`. Deliberately out of scope for the export work; touches `batch/run.py` and its profile plumbing. | Medium | Medium | Low | export design doc |
| 4 | **`auto_norm_sample_count`** — still empty on a real run for reasons not yet understood. Needs a diagnostic macro run, not another guess at a name. | Low | Small once diagnosed | Low | §5.1 |
| 5 | **Non-QoI monitors** — `Solver Iteration Elapsed Time Monitor` is assessed as an engineering quantity. Cannot gate anything, but adds rows and reasons. | Low | Small | Low | §5.4 |
| 6 | **Convergence-window cold open** — ~2.1 s with ten data sets (the first uncached assessment pass). Per-edit lag is already fixed. | Low | Small | Low | §12 |
| 7 | **Prose/PDF report per run** — considered during the export design and deferred; the app has no prose-document writer. | Low | Large | Low | export design doc |

### 11.3 The diagnostic that `auto_norm_sample_count` needs

Do not guess another accessor name — `getAutoNormalizeIndex` is confirmed
present on `PlotableMonitor`, which `ResidualMonitor` inherits, and the macro
already calls it. The open question is why it comes back empty when
`getNormalizeOption`, declared on the *same class* and called on the *same
objects* in the *same loop*, succeeds.

One run of a macro that, for the first monitor whose simple name contains
"Residual", prints: its runtime class name, the full `getClass().getMethods()`
list, and the caught exception from `getAutoNormalizeIndex()` (rather than
`invokeQuiet` swallowing it) will answer it outright. Everything needed is one
`sim.println` in `autoNormSampleCountOf`.


---

## 12. Performance: what the responsiveness rests on

Editing in the Convergence window used to re-run the full assessment of every
loaded data set on the GUI thread, per edit. With ten data sets that was 1.7 s
per checkbox tick, and because a spin box emits a change per keystroke, typing
a four-digit tolerance ran four complete passes — close to seven seconds of
frozen window. Two things fixed it, and both are load-bearing:

**The pairwise statistics are memoised** (`stats.py`). `theil_sen_slope` and
`mann_kendall` are O(n²) in the trailing window and together were 81% of a
pass. Neither depends on the tolerance or residual-drop values being edited —
verified across 207 monitors at 0.1%/3 decades versus 0.05%/6 decades, every
statistic byte-identical — so that work was being repeated to produce the same
numbers. A pass went 1725 ms → 135 ms.

Three properties of that cache are deliberate:

- **It memoises pure functions, and lives with them rather than in the GUI.**
  Same input, same output, so there is nothing to invalidate and no way for it
  to go stale. A cache in the dialog keyed on sim paths would have needed
  invalidation logic and could have served a stale statistic after a reload.
- **The key is the array's exact bytes** — not its identity, because every
  pass rebuilds its arrays from the cached `SimResult` so identity would never
  hit; and not a hash digest, because a collision would attribute one
  monitor's trend to another.
- **The cap has headroom on purpose** (4096 entries against ~62 per data set,
  ~0.34 MB each). An LRU under a cyclic scan — and every pass walks the data
  sets in the same order — drops to *zero* hits the moment the working set
  exceeds the cap, rather than degrading gradually. Sizing it near the
  expected workspace would be worse than useless.

**The spin boxes debounce** (250 ms, `convergence_dialog.py`). Only the spin
boxes: a preset choice, a checkbox and a bulk button are each one deliberate
action with no burst to collapse, and a test pins that they stay immediate.
`_flush_pending_reassess` exists so tests can run the queued pass without an
event loop.

Still outstanding: opening the window cold is ~2.1 s with ten data sets — the
first, uncached pass. That is a one-time cost, not the per-edit lag that was
reported, which is why it was left (see §11.2).
