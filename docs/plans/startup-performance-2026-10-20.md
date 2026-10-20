# Startup and large-table responsiveness, 2026-10-20

## Scope

Local follow-up to v4.0.1 (`948d2d51185ad14338b626297a17f8869636e9d4`).
No existing tag, release, installation or remote branch is changed. Do not
interpret source/offscreen measurements as frozen Windows cold-start timings.

Preserve measurement strings, original row mappings, source-qualified REF/RAW
choices, missing-data rules, Undo, document validation and export semantics.
No timing thresholds or numerical/rendering precision were relaxed.

## Diagnosis and changes

- Fresh shell import profiling attributed approximately 480 ms to Pandas via
  `workspace_store`. Its metadata/constants need no data-analysis dependency.
  Pandas now loads inside the actual validation/read/write operations. A fresh
  subprocess regression checks the fully shown shell for premature analysis,
  Pandas/NumPy, Matplotlib, SciPy or ONNX Runtime imports.
- First Ctrl+A on an 8,000 x 33 reordered sheet traversed all 264,000 cells.
  Dense sheets now search inward from their visible edges; sparse sheets keep
  the sparse scan. Randomized literal-cell comparisons, filtered/reordered
  rows, empty boundaries, edits and Undo verify the exact rectangle.
- Correlation sidebar changes rebuilt unchanged selection-box items and
  repeatedly computed the same Group-span ownership. Unchanged items are kept;
  flag variants and immutable per-plan row partitions are reused. Cache reuse
  requires the same GroupPlan, source split and complete source-row groups,
  not merely the same number of observations or parameter name.
- Sheet loads expose their already converted literal document and known extent
  before change observers read them, avoiding redundant reconstruction. A
  reentrant edit/unknown change still invalidates the prepared state.
- A table replacement batches its intermediate plan publications with the
  existing input-update context. A validated Workbook participation read no
  longer copies and normalizes its complete classification state again.
- GroupPlan parses repeated flags and constructs repeated labels once per
  plan. Flag cache keys retain value types: numeric NaN is blank but the text
  `nan` must still fail validation.

## Repeatable startup baseline

Run sequentially, outside the full test suite, using the same virtual
environment. Each sample is a fresh process with scratch settings, reminders,
recovery and Matplotlib cache. The original checkout is not reset: a Git archive
of the v4.0.1 package supplies the baseline `--code-root`.

```
.venv/Scripts/python.exe -X utf8 -m benchmarks.benchmark_startup --code-root .cache/performance-20261020/before
.venv/Scripts/python.exe -X utf8 -m benchmarks.benchmark_startup
```

| First responsive shell, ms | v4.0.1 source | Candidate source |
| --- | ---: | ---: |
| Sample 1 | 791.849 | 292.012 |
| Sample 2 | 782.383 | 290.286 |
| Sample 3 | 757.172 | 289.241 |
| Sample 4 | 742.061 | 293.125 |
| Sample 5 | 739.255 | 293.146 |
| Median | 757.172 | 292.012 |

Median reduction: approximately 61.4%. The baseline loads Pandas and NumPy;
the candidate loads neither. Both leave analysis tools unopened. This does
not establish the first Workbook-open time, antivirus/OS cache behavior or the
startup time of an already published EXE; that EXE has not been rebuilt here.

After the full suite exited, three fresh-process public-seam probes per version
used the unchanged performance tests and retained all their assertions. Each
row reports the median of the test's maximum UI latency, not a per-cell average.
The Correlation fixture has 6,000 rows, 600 wafers and three columns per source;
the selection fixture has 8,000 x 33 cells in reversed row order.

| Independent interaction probe, ms | v4.0.1 source | Candidate source |
| --- | ---: | ---: |
| Correlation checkbox, median maximum | 270.584 | 138.507 |
| Reordered sheet select/click, median maximum | 160.599 | 24.722 |

Candidate samples all passed these two probes. Nevertheless, Correlation
exceeded its 150 ms budget once in the full suite; the issue remains open.

## Verification

Targeted startup, literal-sheet bounds, source identity, Trend row fallback,
selector updates and clipboard/paste regression tests passed during development.

Final isolated command: `.venv/Scripts/python.exe -X utf8 run_tests.py`.
857 tests in 709.826 s: 852 passed, 5 failures, 0 errors. All five failures are
the existing elapsed-time assertions below; no functional assertion failed.
The original timing budgets are unchanged. Passing individually is not treated
as resolving an item that still failed in the full run.

| Remaining full-run timing failure | Actual | Original limit |
| --- | ---: | ---: |
| Correlation checkbox, maximum of four changes | 155.189 ms | <150 ms |
| Five equal-identity numeric snapshots | 103.268 ms | <100 ms |
| Five keyboard Undo actions and current result | 700.529 ms | <650 ms |
| Wide saved Workbook dirty checks, minimum of three | 104.790 ms | <100 ms |
| Open a 6,000-row x 33-column Wafer Map with current Cards | 595.814 ms | <400 ms |

Large filtered/reordered Ctrl+A, clear/Undo and complete grouped Correlation
restoration passed their original gates in the full run. These remaining timing
issues are not claimed fixed by the startup improvement.

The user's `config/settings.yaml` SHA-256 stayed
`780edd52717da4ed1906708647775b37032a5b7c411c51353776632ffe135f10`.

Diagnostic evidence is under `.cache/performance-20261020/`: startup/interaction
JSONL, import profile, interaction profiler and the full-suite log. These are local
diagnostics, not release payloads.
