# Convergence tool (phase 1: steady runs) — design

## Goal

Wire up the currently inert **Tools → Convergence** menu entry so it opens a
window that assesses whether a solved simulation has converged, and — when it
has not — lists the reasons why, each with the numbers behind it and a suggested
action.

The reference for the mathematics is the theory specification
`convergence_assessment_theory_spec` revision 2 (supplied by the user; not
checked into this repo). Section numbers of the form "§3.3" in this document
refer to **that** specification, not to this one. Its `[S]` / `[D]` / `[V]`
evidence tags are carried through into the implementation: every threshold
records where it came from, so a user asking "why this number?" gets an answer.

**Phase 1 is the steady-run slice.** The theory spec decomposes "is it
converged?" into five questions; phase 1 answers three of them and is explicit
about the two it does not:

| # | Question | Phase 1 |
|---|---|---|
| 1 | Is the solve healthy (not diverging, not stalled)? | **Yes** — §3 residual diagnostics |
| 2 | Has the iteration stopped changing the solution? | **Yes** — §4 iterative-error estimation |
| 3 | Have the engineering QoIs stopped changing? | **Yes** — §5 steady QoI gates |
| 4 | Unsteady: statistically stationary, mean known to tolerance? | **No** — detected and refused |
| 5 | Is the solution physically consistent (global conservation)? | **No** — always `INCOMPLETE_EVIDENCE` |

Question 4 is refused rather than approximated: applying steady gates to a
URANS/DES record produces a confident wrong answer, which is worse than no
answer. Question 5 is declared missing rather than skipped silently, so the
verdict never claims completeness it does not have.

## Context (what already exists)

- **Menu entry** — "Convergence (coming soon)" exists in the Tools dropdown,
  disabled, no slot wired (`src/starpost/gui/main_window.py:549`). Wiring it up
  means dropping the `(coming soon)` suffix and the `setDisabled` call for that
  one entry; "Correlation" stays a placeholder.
- **Per-iteration histories already exist and are cached.** `MonitorPlot`
  (`src/starpost/data/models.py:50`) holds `PlotSeries` objects, each with `x`
  (iteration) and `y` lists. This is the only source of history in StarPost:
  `Report` objects are final scalars with no time series, so **the QoI layer
  necessarily runs on monitor plots, not on reports.**
- **Monitors are already classified.** `MonitorPlot.kind` is `PlotKind.RESIDUAL`
  / `FORCE` / `OTHER`, assigned by keyword heuristics from settings
  (`residual_keywords`, `force_keywords` in `config/default_settings.yaml:97`).
- **Sim metadata is already extracted and cached.** `SimResult.properties`
  (`SimProperties`, a list of `PropertyGroup`) carries `solution` (iteration,
  time_level, physical_time), `mesh` (cell_count), `continuum` (the enabled
  **models** list, which distinguishes Steady from Implicit Unsteady and
  Segregated from Coupled), `solver` names, and `criterion` names.
- **Separate windows** follow the non-modal `QDialog` pattern —
  `PartSearchDialog` (`src/starpost/gui/views/part_search_dialog.py`) is the
  closest precedent, including the "keep a reference, raise and refresh on
  re-trigger" behaviour.
- **Ticked data sets** drive comparison mode across the app; the Convergence
  window follows the same idiom.
- **No STAR-CCM+ re-run.** The assessment reads cached data only, consistent
  with the central invariant.

## Dependencies

**None added.** Everything phase 1 needs — ordinary least squares,
autocorrelation, Mann–Kendall, Theil–Sen, and the inverse Student-$t$ CDF — is
numpy plus a local incomplete-beta implementation (~40 lines in
`core/convergence/stats.py`). Adding scipy for four functions would cost roughly
60 MB in the PyInstaller bundle. Phase 2's Welch PSD is `numpy.fft`; the
optional formal stationarity tests (KPSS/ADF) are the only part of the theory
spec that would genuinely want statsmodels, and the spec itself says never to
gate a verdict on them.

Per CLAUDE.md's startup-latency convention, `core.convergence` must not be
imported at module top level anywhere on the startup path — the main window
imports it lazily inside the menu slot.

---

## Architecture

### New package: `src/starpost/core/convergence/`

Entirely Qt-free and STAR-CCM+-free. Every module takes arrays plus a config
object and returns a dataclass; nothing reaches back into the GUI or the store.
This makes the whole validation suite runnable headless.

```
core/convergence/
  __init__.py     assess(result, config) -> ConvergenceAssessment   ← only public entry
  models.py       dataclasses mirroring the theory spec's §11 output schema
  config.py       ConvergenceConfig / MonitorConfig; the §9.3 threshold table as data
  metadata.py     SimProperties -> RunMetadata, with per-field provenance
  signals.py      §2.3 preconditioning; monitor classification; trailing-window selection
  stats.py        OLS, D_N autocorrelation, Mann-Kendall, Theil-Sen, inverse-t
  residuals.py    §3.2 decades dropped, §3.3 log-slope and the state ladder
  iterative.py    §4.2 geometric-progression U_iter with standard-deviation inflation
  steady.py       §4.4 reference-scale ladder; §5.1-5.4 drift / band / two-halves gates
  verdict.py      §9.1 state ladder, advisory flags, §9.2 roll-up, recommendations
```

`verdict.py` is the only module that sees all layers at once. Every other module
is independently testable and small enough to hold in context.

### New GUI: `src/starpost/gui/views/convergence_dialog.py`

Non-modal `QDialog`, three panes (detailed below).

### Modified: `src/starpost/macros/extract_all.java.j2`

A new `convergence` properties section (detailed below).

---

## Metadata (theory spec §2.2)

The theory spec is emphatic that convergence conclusions are invalid without
certain metadata, and that it must be captured rather than guessed. Three fields
it treats as mandatory are not extracted today.

### Macro extension

`extract_all.java.j2` gains `propsConvergence`, emitting a `convergence` section
in the existing `section,name,key,value` properties CSV. It follows the file's
established defensive style: every read wrapped, `invokeQuiet` for accessors
whose exact name varies by release, an empty value for "not applicable" and an
absent row for "read failed".

| Key | Why (theory spec) |
|---|---|
| `precision` | §1 — sets the machine-precision floor. Without it `MACHINE_PRECISION` is unusable and a single-precision run is permanently misclassified `STALLED` (§10.15) |
| `residual_normalization` (per solver) | §3.1 — determines whether absolute or only relative residual statements are possible |
| `auto_norm_sample_count` | §3.1 — the auto-normalization reference window, STAR-CCM+ default 5 |
| `solver_regime` | §2.2 — selects the whole analysis branch |
| `solver_type` | §2.2 — segregated and coupled residuals behave differently |
| `time_step` | §2.2 — needed by phase 2 |
| `inner_iterations_per_timestep` | §3.4 — needed by phase 2 to de-interleave the sawtooth |
| `courant_number` | §3.4 — iterative error grows with Courant number at fixed criterion |

The STAR-CCM+ API surface for these is marked `[V]` in the theory spec and must
be checked against the local 2506 help during implementation. The last three are
extracted in phase 1 even though only phase 2 consumes them, so that data sets
extracted from now on are already usable when phase 2 lands.

### Degradation, not guessing

`metadata.py` produces a `RunMetadata` in which **every field carries its
provenance**: `extracted` (from the new macro section), `derived` (inferred from
data already present), or `absent`.

- `solver_regime` and `solver_type` are `derived` when not extracted, from the
  continuum **models** list — it names "Steady" or "Implicit Unsteady", and
  "Segregated Flow" or "Coupled Flow". This is reliable enough to branch on.
- `precision` absent → advisory flag `PRECISION_UNKNOWN`, and the
  `MACHINE_PRECISION` / `CONVERGED_MACHINE` verdict is **suppressed**, not
  guessed (§1).
- `residual_normalization` absent → advisory flag `NORMALIZATION_UNKNOWN`.
  Residual output is downgraded to *decades dropped* only; no absolute residual
  threshold is applied and no cross-run residual comparison is offered (§10.5).

Consequence to state plainly in the UI: data sets extracted before this change,
and data sets imported from portable CSVs, will assess at **Medium or Low
confidence** until re-extracted. That is the correct outcome, not a defect.

---

## Signal preparation (theory spec §2.3)

Applied in order, and recorded in the output.

1. **Integrity.** Any non-finite value, duplicated index, or zero-length series
   is caught. A non-finite value at iteration *n* is a hard `DIVERGED` at *n*
   (§2.3.1); a malformed or empty series is `INTEGRITY_FAIL`.
2. **Restart segmentation (§2.3.2, §10.7).** The sim gives us no
   `restart_boundaries`. What the *data* shows is a non-monotonic or duplicated
   iteration index, which is a reliable restart signature — we segment there and
   analyse only the final contiguous segment, retaining earlier segments for
   display. A large single-iteration residual jump **without** an index reset
   raises the advisory flag `RESTART_SUSPECTED` and nothing more. **We never fit
   across a detected boundary.** This is a knowing departure: the theory spec
   assumes restart indices are supplied, and our heuristic will miss a restart
   that continued the iteration count monotonically.
3. **Spike removal.** Off by default, exactly as the theory spec specifies
   (§2.3.3). Not implemented in phase 1; the robustified band and Theil–Sen
   slope already provide spike resistance where it matters.
4. **Resampling.** Not needed in phase 1 — steady runs are indexed by iteration,
   which is uniform by construction. Phase 2 needs it for adaptive time steps.
5. **No smoothing of residuals** (§2.3.5). Slope estimation is regression in log
   space, which is already a smoother; pre-filtering biases the decay rate.

### Monitor classification

- `MonitorPlot.kind == PlotKind.RESIDUAL` → the residual layer. Each
  `PlotSeries` within it is one equation *k*.
- Every other monitor → the QoI layer.

Equation class is assigned by keyword: **primary** (continuity, momentum in x/y/z,
energy) versus **turbulence** (Tke, Tdr, Sdr). This distinction is required by
§3.1.4 — turbulence residuals routinely stall one to two orders above the
momentum residuals without harming the QoIs. They get a lower threshold
(`D_min_turb = 2`), are warning-only, and **can never alone force a
`NOT_CONVERGED`**. Unrecognised equation names default to the primary class,
which is the conservative direction.

### Trailing window

`W = max(200, 0.2N)` iterations (§9.3), subject to the §5.4 gate 5 requirement
`N_W >= max(200, 20 * D_N)`. When the record cannot supply that, the window is
whatever exists and `WINDOW_TOO_SHORT` is raised — gate 5 fails and confidence
drops. Gate 5 is what prevents the classic false positive of a short flat
stretch inside a long slow oscillation (§5.4).

---

## Layer 1 — residual diagnostics (theory spec §3)

Per equation *k* of the final segment:

- **Reference level** `R_ref` = max over the first `N_0` iterations of the final
  segment, matching the solver's own auto-normalization where applicable (§3.2).
  `N_0` comes from `auto_norm_sample_count`, defaulting to 5.
- **Decades dropped** `D_k = log10(R_ref / R_terminal)`, with `R_terminal` the
  **median** over the trailing window, not the last value.
- **Log-space OLS** over the trailing window gives slope `s_k`, decay factor
  `rho_k = 10^s_k`, `r^2`, and the fit standard deviation.
- **Iterations to target**, reported only when `s_k < 0` and `r^2` is adequate,
  always with an explicit "extrapolation, assumes the current rate persists"
  caveat.

**State ladder, evaluated strictly in order, first match wins** (§3.3 — the
ordering is load-bearing, since several conditions can hold at once):

| Order | Condition | State |
|---|---|---|
| 1 | any non-finite value in W | `DIVERGING` |
| 2 | `R_terminal > kappa_div * R_ref` | `DIVERGING` |
| 3 | `s_k > s_div` sustained over >= 50 iterations | `DIVERGING` |
| 4 | `R_terminal / R_ref <= eps_prec` **and precision known** | `MACHINE_PRECISION` |
| 5 | `abs(s_k) < s_flat` and `D_k < D_min` | `STALLED` |
| 6 | `abs(s_k) < s_flat` and `D_k >= D_min` | `PLATEAU_LOW` |
| 7 | `s_k < -s_flat` | `CONVERGING` |

Rung 4 is skipped entirely when precision is unknown, so a single-precision run
falls through to rung 6 (`PLATEAU_LOW`) rather than rung 5 (`STALLED`).

Distinguishing `STALLED` from `PLATEAU_LOW` is the single most useful
residual-derived output (§3.3). Because the monitor is an RMS over cells, a
stall is almost always a *setup* problem — a handful of bad cells — not a "run
it longer" problem, so the recommendation for `STALLED` points the user at the
per-cell residual field function to localise the offending cells, **not** at
more iterations.

Residuals are a health monitor and a necessary condition, never the verdict
(§3.1, and Siemens' own stated position). The verdict lives in layer 3.

---

## Layer 2 — iterative error (theory spec §4)

**Applied to the per-QoI change series** `L_j = abs(phi_j[n] - phi_j[n-1])`,
giving `U_iter,j` in the QoI's own units, directly comparable to a tolerance
(§4.3 point 1).

Fit `log10 L = c + s*n` by OLS over the trailing window, then

```
eps_iter = 10^(c + s*n0) / (1 - 10^s)          valid only for s < 0
U_iter   = F_s * eps_iter,  F_s = 1.25
U_iter  <- U_iter * 10^delta_f                 inflation by the fit std dev
```

Three things the output must say, because the theory spec insists on each:

- The `1/(1-rho)` summation convention is used (the conservative one), stated
  explicitly so a user comparing against a hand calculation is not confused by a
  factor of `rho` (§4.2).
- The inflation form used, plus `delta_f` and `r^2`, so the user can see how
  trustworthy the extrapolation is. Including the standard deviation of the fit
  is the reference procedure's central finding — the estimator without it was
  not the one that performed best (§4.2).
- **This is a scalar analogue of the validated `L_inf` field estimator, not the
  estimator itself** (§4.3). The validated one needs field data we do not have.

Guards (§4.2): `s >= 0` → `NO_ESTIMATE`; fewer than 20 points → `INSUFFICIENT_DATA`;
`rho > 0.999` → advisory flag `ASYMPTOTICALLY_STAGNANT`, meaning more iterations
at this rate will not help.

Residual-derived `eps_iter` is **never** converted into physical units (§4.3
point 2): STAR-CCM+ residuals are an RMS over cells, i.e. exactly the `L_2`-type
norm the source says to avoid for this purpose.

### Reference scale (theory spec §4.4)

Chosen per monitor, in this order, with the choice recorded as `scale_source`:

1. User-supplied physical scale.
2. `abs(mean)` over the trailing window, **only if** `abs(mean) > gamma * sigma`
   with `gamma = 5`.
3. Robustified full-record range, `Q95 - Q5`.

Never `abs(mean)` unconditionally. QoIs that legitimately hover near zero — lift
at zero incidence, net moment, side force on a symmetric body — otherwise
produce infinite relative errors and spurious `NOT_CONVERGED` verdicts. The
theory spec calls this the most common practical failure of automated
convergence checks (§4.4, §10.4).

---

## Layer 3 — steady QoI gates (theory spec §5)

**Units convention, stated once and applied everywhere.** The user sets a
tolerance as a *fraction* (0.1% or 0.05%); the gates compare against an
*absolute* `eps_j = fraction * S_j`, in the monitor's own physical units, with
`S_j` the reference scale from §4.4 above. Every gate below, and every margin
`m_j`, is in absolute units. The UI shows both.

A monitor passes iff **all five** hold (§5.4):

1. **Drift**: `N_W * abs(beta) <= eps_j`, `beta` the OLS slope over W.
2. **Band**: `Q97.5 - Q2.5 <= eps_j`. The raw max-minus-min is reported
   alongside but does not gate, so a single spike cannot veto convergence.
3. **Two halves**: `abs(mean(W2) - mean(W1)) <= eps_j / 2`.
4. **Iterative error**: `U_iter,j <= eps_j`.
5. **Window adequacy**: `N_W >= max(200, 20 * D_N)`.

Both parametric (OLS) and robust (Theil–Sen) slopes are computed and reported.
Disagreement between them raises `TREND_ESTIMATE_UNSTABLE` — the theory spec
treats the disagreement itself as a useful signal (§5.1). Mann–Kendall `Z` and
its `p` are reported as supporting evidence.

Every gate carries **both** a statistical result and an absolute effect size in
physical units, per §10.12: with a long record a physically irrelevant
difference becomes statistically significant, and with a short one a large
difference is not.

`D_N` (the decorrelation factor, §6.4) is needed here for gate 5 even though the
rest of §6 is phase 2:

```
D_N = 1 + 2 * sum(rho_tau for tau = 1..tau_0),   tau_0 = first zero crossing
N_eff = N_W / D_N
```

When `tau_0 / N > 0.05` the estimator's validity assumption fails and a warning
is raised (§6.4).

### Limit cycles — reduced (theory spec §5.5)

Full `CONVERGED_OSCILLATORY` detection is phase 2, because it needs a
periodogram peak-to-broadband ratio. Phase 1 implements the cheap half: when
gates 1 and 3 pass (no drift) and gate 2 fails (band too wide), the reasons list
says so explicitly — "the mean is not drifting but the band is wide; this is the
signature of a limit cycle, which a steady solver models questionably" — and the
advisory flag `OSCILLATORY_SUSPECTED` is raised. The verdict is still not
`CONVERGED`. This does not fully close §10.9's named failure mode, but it stops
the tool from actively misleading the user about it.

---

## Verdict, confidence, and reasons (theory spec §9)

### Terminal states — first match wins

```
INTEGRITY_FAIL         non-finite / malformed / empty input
DIVERGED               residual divergence or non-finite value
STALLED                residual plateau with insufficient drop
UNSTEADY_UNSUPPORTED   solver_regime is unsteady; phase 1 declines to assess
SLOW_DRIFT             drift gate failed
CONVERGING             healthy, gates not yet met; emit an iteration projection
CONVERGED              all gates met at the requested tolerance
CONVERGED_MACHINE      residuals at the precision floor, all gates met
```

`UNSTEADY_UNSUPPORTED` is this tool's own state, not one of the theory spec's.
`NONPHYSICAL` (§7.3) needs user-supplied sentinel bounds and is deferred, as is
`TRANSIENT` (§6).

### Advisory flags — attach to any state, including `CONVERGED`

```
TREND_ESTIMATE_UNSTABLE     parametric and robust slopes disagree      (§5.1)
ASYMPTOTICALLY_STAGNANT     rho > 0.999                                (§4.2)
INCOMPLETE_EVIDENCE         required monitors absent                   (§5.6, §7.2)
PRECISION_UNKNOWN           machine-precision verdict suppressed       (§1)
NORMALIZATION_UNKNOWN       residual statements limited to decades     (§3.1)
WINDOW_TOO_SHORT            gate 5 not satisfiable from this record    (§5.4)
RESTART_SUSPECTED           residual jump with no index reset          (§10.7)
OSCILLATORY_SUSPECTED       no drift, wide band                        (§5.5)
```

`INCOMPLETE_EVIDENCE` is raised unconditionally in phase 1, since the
conservation check (§5.6) is not implemented, and additionally by the §7.2
monitor-coverage audit when no primary QoI is declared.

### Roll-up (theory spec §9.2)

Each monitor carries a **margin** `m_j = eps_j / u_j`, where `u_j` is the
binding uncertainty — the maximum of `U_iter,j`, the projected drift, half the
band, and the two-halves delta. `m_j >= 1` passes.

- **How the two layers combine into one state.** The residual layer contributes
  run-level states (`INTEGRITY_FAIL`, `DIVERGED`, `STALLED`) by aggregating its
  per-equation ladder: `DIVERGING` on any equation ⇒ run `DIVERGED`; `STALLED`
  on any **primary-class** equation ⇒ run `STALLED` (turbulence equations can
  never trigger this, per §3.1.4). The QoI layer contributes the remaining
  states (`SLOW_DRIFT`, `CONVERGING`, `CONVERGED`) from the primary monitors.
  The two candidate states are then resolved through the single terminal ladder,
  first match wins — so a residual `DIVERGED` outranks a QoI `CONVERGED`.
  `CONVERGED_MACHINE` requires both: every primary QoI passing **and** every
  primary-class equation at `MACHINE_PRECISION`.
- Overall state = the worst terminal state over monitors marked `is_primary`.
  Non-primary monitors contribute warnings only.
- **Convergence index** `C = min over primary monitors of m_j`.
- **Binding constraint** — one string naming the monitor and the gate, e.g.
  "Drag: two-halves consistency". The theory spec calls this the most actionable
  output the tool can produce.

**Never a bare boolean** (§9.2). Every verdict carries state, active advisory
flags, per-monitor margins, the binding constraint, the evidence-completeness
flag, and the estimated additional iterations to reach tolerance.

### Confidence

Deterministic, and the tool states the rule it applied:

| Level | Condition |
|---|---|
| **High** | `solver_regime`, `residual_normalization` and `precision` all known; at least one primary QoI declared; `N_eff >= 30`; every gate margin outside 0.5–2.0 |
| **Medium** | any metadata field absent, or `N_eff` in [10, 30), or any gate margin inside 0.5–2.0 |
| **Low** | `N_eff < 10`, or no primary QoI declared, or `N_W < 200`, or residual normalization unknown |

Worst level wins — so `residual_normalization` absent lands on Low, not Medium,
even though it is also "a metadata field absent".

`INCOMPLETE_EVIDENCE` deliberately does **not** appear in this table. It is
raised unconditionally in phase 1 (the conservation check is not implemented),
so letting it cap confidence would make High unreachable and the level
meaningless. The flag is shown to the user regardless; it says "this assessment
did not check global conservation", which is a statement about coverage, not
about the reliability of what *was* checked. When the §7.2 coverage audit raises
`INCOMPLETE_EVIDENCE` for the *other* reason — no primary QoI declared — that
condition already caps confidence at Low on its own row above.

No percentage score is emitted: a "% likely converged" number
would be a fabricated statistic, and the theory spec's whole argument is that a
convergence tool's value lies in the binding constraint and the remaining cost,
not in a scalar.

### Reasons

One entry per failed gate, and per gate that passed only marginally
(`0.5 < m_j < 2`). Each carries:

- `severity` in {info, warning, error}
- `target` — the monitor or equation it concerns
- `message` — what failed, with the numbers behind it in physical units
- `suggested_action` — the theory spec's own guidance for that gate. `STALLED`
  points at the per-cell residual field function, not at more iterations.
  A near-zero-mean scale fallback tells the user to supply a physical scale.
- `estimated_extra_iterations` where the residual slope or the drift rate
  supports a projection, always with the "assumes the current rate persists"
  caveat.

Reasons are sorted by severity, then by how badly the gate missed. Passing
monitors also produce an info-severity summary line, so the user can see what
*was* checked — a verdict from an inadequate monitor set is worse than no
verdict, because it manufactures false confidence (§7.2).

---

## Configuration (`config.py`)

`ConvergenceConfig` holds the §9.3 threshold table as data, every entry carrying
its `[S]` / `[D]` provenance so the UI can show it. Defaults:

| Symbol | Meaning | Default |
|---|---|---|
| `D_min` | required decades, continuity/momentum/energy | 3 `[S]`, advisory 4 `[D]` |
| `D_min_turb` | required decades, Tke/Tdr/Sdr | 2, warning only |
| `s_flat` | abs log-slope below which residuals count as flat | 1e-4 decades/iteration |
| `s_div` | log-slope above which divergence is declared | +1e-3 sustained over 50 iterations |
| `kappa_div` | residual growth factor vs reference ⇒ diverged | 10 |
| `eps_prec` | relative residual floor ⇒ machine precision | 1e-13 double / 1e-6 single; suppressed if unknown |
| `F_s` | safety factor on iterative error | 1.25 `[S]` |
| `eps_j` | per-QoI tolerance relative to `S_j` | 0.1% screening / 0.05% production |
| `W` | trailing window | `max(200, 0.2N)`, and `>= 20 * D_N` |
| `gamma` | mean/sigma separation to use `abs(mean)` as scale | 5 |
| `lambda_ind` | independent samples required in a steady window | 20 |
| `N_eff_min` | minimum effective samples for a statistical verdict | 30 (hard floor 10, flagged) |
| `tau0_over_N` | warn above this ratio | 0.05 |

Thresholds are overridable and the assessment records which values were used.

`MonitorConfig` is per monitor: `is_primary`, `tolerance`, `reference_scale`
(auto or manual), `expected_sign`.

---

## GUI: `ConvergenceDialog`

Non-modal `QDialog` opened from Tools → Convergence, parented to the main
window, following `PartSearchDialog`: the main window keeps a reference so the
window is not garbage-collected, and re-triggering the menu entry raises and
refreshes the existing window rather than spawning a duplicate.

### Layout

**Left pane — input and configuration**

- Data-set picker listing the **ticked** data sets (StarPost's comparison
  idiom). Each is assessed independently.
- Tolerance preset: *Screening (0.1%)* / *Production (0.05%)* / *Custom*,
  applied to all monitors as a starting point.
- Per-monitor configuration table, one row per non-residual monitor:
  **primary** (checkbox), **tolerance**, **reference scale** (Auto — showing the
  §4.4 rung that was selected — or a manual value). Monitors classified
  `PlotKind.FORCE` are auto-ticked as primary.
- Configuration persists per data set for the session, so re-opening the window
  does not lose the setup.

**Top-right — verdict card**

State, confidence, convergence index `C`, and the binding constraint, plus the
active advisory flags as chips. Theme-aware colouring via `theme.py`.

**Bottom-right — reasons list**

One row per reason, severity-coloured, showing message and suggested action;
expandable to the numbers behind it. This is the answer to "list the reasons why
it may or may not be converged".

**Detail tab**

Two tables: residuals (per equation — `R_ref`, terminal median, decades dropped,
slope, `rho`, `r^2`, state, iterations to target) and QoI gates (per monitor —
mean, band, both slopes, projected drift, two-halves delta, `U_iter`, `D_N`,
`N_eff`, margin, per-gate pass/fail).

**Multi-data-set summary**

When more than one data set is ticked, a summary row per data set: name, state,
confidence, `C`, binding constraint. Selecting a row drives the detail panes.

### Deferred to phase 2

Export of the assessment (markdown/JSON), the evidence plot with the trailing
window shaded and the tolerance band overlaid, the conservation check, and the
full unsteady/statistical layer.

---

## Testing

Test-driven, against the theory spec's §12 validation suite. Each case has an
analytically known answer, which is the point of the suite. Phase 1 implements
the steady-relevant cases:

| Case | Signal | Expected |
|---|---|---|
| V1 | `R = R0 * rho^n + eta`, `rho = 0.97`, floor 1e-12 | decay factor recovered to <1%; `eps_iter` brackets the true remaining error; `CONVERGED` |
| V2 | `phi = phi_inf * (1 - exp(-n/lambda))` plus small noise | drift gate passes at the right iteration; iteration projection accurate within a factor of 2 |
| V5 (reduced) | stationary AR(1) plus a linear drift of magnitude `2 * eps` | must fail with `SLOW_DRIFT` via the §5.1 projected-drift gate |
| V7 | residual growing exponentially | `DIVERGED`, detected within 50 iterations of onset |
| V8 | residual plateau at 1e-2 after 1.5 decades | `STALLED`, not `CONVERGED` |
| V9 | stationary record with mean exactly zero | no divide-by-zero; scale falls back per §4.4; sensible verdict |
| V10 | two segments with a restart discontinuity | no fit across the boundary; analysis on the final segment only |
| V15 | single-precision residual flooring at ~1e-7 relative, paired with a passing QoI series | per-equation `MACHINE_PRECISION` and run `CONVERGED_MACHINE` when precision is single; **not** `STALLED`. With precision unknown, `PRECISION_UNKNOWN`, per-equation `PLATEAU_LOW`, and no machine verdict |

V3, V4, V6, V11–V14 and V16 belong to phase 2 (limit cycles, transient
detection, CI coverage, periodic content, inner iterations, non-uniform
sampling, slow drift in a local monitor).

`stats.py` is tested directly against known values: the inverse Student-$t$
against published quantiles, and `D_N` against a synthetic AR(1) process where
`D_N = (1 + phi) / (1 - phi)` exactly.

All of the above is Qt-free and runs under the existing `scripts/run_tests.py`.
The dialog gets a thin GUI test in the established `test_main_window.py` style,
plus a real-display check per the repo's `verify` skill, since the configuration
table involves editable cells and checkboxes.

---

## Knowing departures from the theory spec

Recorded here so they are visible rather than buried:

1. **Restart detection is heuristic.** The theory spec assumes
   `restart_boundaries` are supplied. We detect index resets and duplication
   reliably, and flag suspicious residual jumps advisorily, but a restart that
   continued the iteration count monotonically will be missed.
2. **Limit-cycle handling is reduced.** Signature detection and an advisory flag,
   not the `CONVERGED_OSCILLATORY` state with spectral confirmation. §10.9's
   named failure mode is mitigated, not closed.
3. **Layers 4 and 5 are absent**, by scope. Unsteady runs are refused rather than
   approximated; the conservation check is declared missing via
   `INCOMPLETE_EVIDENCE` rather than skipped silently.
4. **No `NONPHYSICAL` sentinels**, since they need user-supplied physical bounds.
5. **The iterative-error estimator is the scalar analogue**, not the validated
   `L_inf` field estimator — the theory spec's §4.3 point 3 notes that emitting a
   field-max change per iteration from the macro would unlock the validated form,
   and calls it the single highest-value extension. Worth considering as a later
   phase, since StarPost already owns the macro path.

---

## Changelog and conventions

Per CLAUDE.md: commit after every change; log the user-facing change in
`CHANGELOG.md` in its existing style. No new keyboard shortcut is proposed, so
`shortcuts.py` and `docs/starpost_hotkeys.txt` are untouched. Tests that touch
config or cache reuse the existing `autouse` `platformdirs` fixture.
