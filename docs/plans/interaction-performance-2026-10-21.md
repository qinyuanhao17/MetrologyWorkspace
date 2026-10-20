# Interaction preparation, 2026-10-21

Continue from the complete local v4.1.0 feature candidate, not Git HEAD alone.
The pre-optimization package is retained separately; final distribution must be
rebuilt from the optimized source. User edits to AGENTS.md, .vscode/settings.json
and docs/todos/ are not part of the release commit.

## Diagnosis and retained changes

The two existing 6,000-row Correlation workflows were measured in three fresh
processes before changes. Profiling identified native selection-grid rebuilding,
repeated selected-index enumeration, and per-Wafer Pandas label conversions.
The numerical fit was not the main cost. No observations or columns are removed.

- MapSelector batches cell flag/tooltip notifications into one native model
  notification, retains exact native box selection, and reuses the exact set it
  just installed. Native user selections and later model edits still invalidate
  that cache. Unchanged header text is not reinstalled on parameter checks.
- Trend prepares Wafer strings once for its shared source and uses the existing
  batch identity-caption helper for all footer spans. Literal source strings,
  original positional row mappings, first-nonblank/fallback identities and the
  order of LOT/PAD captions remain unchanged.
- Coordinate text is derived once per draw-owned Group and reused by parameter
  panels and the export mirror. A new draw creates new Groups; no stale source
  values, regression result, precision choice or physical-unit rule is cached.

Executable regressions in `tests/test_render_preparation.py` first failed on the
unmodified source: 80 native cell notifications for one parameter change and
120 Wafer conversions for 60 Wafers. They now verify bounded preparation, exact
native and reported selections, unchanged text/flags, all curve points and an
unchanged source DataFrame. Existing timing budgets were not changed.

The first batching experiment made re-checking a parameter slower, despite
fewer notifications. It was not accepted as a performance result: retaining the
just-installed exact native selection removed the repeated QModelIndex scan.
The measurements below are from the final retained source, not that experiment.

## Repeatable before/after measurements

Same machine, fixture and original assertions; no full suite/build ran alongside
these measurements. Values are milliseconds, three independent Python processes
per side. Each checkbox sample is the maximum of four changes. These are source
offscreen timings, not installed executable benchmarks or OS-reboot cold starts.

| Workflow | Before samples | After samples | Median change |
| --- | --- | --- | --- |
| Correlation checkbox | 142.003, 140.830, 145.456 | 109.934, 114.115, 109.816 | 142.003 → 109.934 (22.6% less) |
| Restore saved grouped Correlation | 1695.211, 1672.749, 1686.059 | 1523.633, 1540.161, 1517.145 | 1686.059 → 1523.633 (9.6% less) |
| First 6,000-row Workbook fully visible | 3573.477, 3464.951, 3486.219 | 3473.767, 3451.869, 3463.767 | 3486.219 → 3463.767; no meaningful improvement claimed |

The Workbook fixture is 6,000 rows × 33 Raw columns, 300 Wafers and two fitted
parameters. Its SHA-256 remained
`5f6f08bd8e76477203107f4603dde97610ab5e11c56ef92371920e3477708c5e`.
The shell still loads none of Pandas/NumPy/Matplotlib/SciPy/ONNX before a tool is
opened. Its first-visible samples in the Workbook probe were 342.536/308.467/
303.169 ms before and 303.371/298.731/299.923 ms after; this small change is not
treated as a further shell-startup optimization.

## Verification boundaries

The focused label/row-order/hover/visibility/Card/floating-editor checks passed
50 tests. The subsequent 111-test performance and Correlation group passed 110;
only the old keyboard Undo elapsed-time assertion exceeded 650 ms (655.823 ms),
with its data assertions passing. Six final independent checkbox/restore test
executions passed, but these do not substitute for the final full suite.
Final true full-suite and distribution results are recorded in
`docs/releases/v4.1.0.md`, including any timing failures. Do not infer an all-green
full run from isolated probes. The real settings file is never a test target.

The final optimized full run completed 906 tests in 720.701 s: 905 passed,
one timing-only failure, zero errors. Grouped Correlation restoration took
2.183294 s against the unchanged 2 s gate. Checkbox and keyboard Undo timing
checks passed. No functional/data assertion failed. Native selector renders
before/after were pixel-identical with identical input and Qt style.
Raw measurements are retained locally in
`.cache/v4.1.0-optimized-release/performance/`, with the full-suite log one level
above. These diagnostics are not distribution payloads.
