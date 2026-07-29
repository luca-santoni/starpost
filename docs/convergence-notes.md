# Convergence tool — handoff notes

Working notes for anyone picking up the Convergence tool. Covers what exists,
what is known broken, which design decisions are load-bearing, and the traps
that have already cost time.

Current as of branch `feat/convergence-bulk-primary`, which adds the Monitors
list's bulk primary-selection buttons on top of `feat/convergence-tool` (merged
to `main` in d2cb6fa). Full suite green (`python scripts/run_tests.py`, 40
files); `ruff check .` clean.

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
K-Omega SST, 40 monitors each). This is the current state:

| sim | state | conf | index | binding |
|---|---|---|---|---|
| 2500Iter_Bodywork | CONVERGED | Medium | 2.383 | Drag ALL: window adequacy |
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

### 5.1 `precision` is never captured on a real install — `PRECISION_UNKNOWN` is permanent

The macro's probe `invokeQuiet(sim, "isDoublePrecision")` returns empty against
real STAR-CCM+ 2506 — that accessor does not exist on `Simulation`. Confirmed
on all ten exports. `auto_norm_sample_count` is likewise empty.

Consequence: `PRECISION_UNKNOWN` on every data set, the machine-precision
verdict (`CONVERGED_MACHINE`) is permanently suppressed, and confidence is
capped at Medium by the missing-metadata rule.

The degradation is working as designed — no wrong answer, just a suppressed
one. **Fix is one line in `propsConvergence` once the correct 2506 accessor is
identified.** Needs the local Simcenter help; it could not be checked from
here. Everything in that macro section is marked `[V]` for the same reason.

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

## 10. Environment notes (user's machine)

- No system pip/venv; the venv is at `.venv/` and pip was bootstrapped via
  `get-pip.py`. Use `.venv/bin/python` explicitly.
- STAR-CCM+ is installed under `/opt/Siemens` and is **not on PATH**.
- `/tmp` is a 16 GB tmpfs. It has been filled by Chrome temp files
  (a single 15 GB `.com.google.Chrome.*` file), which breaks command output
  redirection. Symptom: `ENOSPC` errors from tool calls. Workaround: redirect
  command output to a file under `$HOME` and read it. Real fix: restart Chrome.
- No GitHub push credentials — the branch is local only.
