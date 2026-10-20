# Responsiveness follow-up, 2026-10-20

## Baseline and boundaries

Continue from the previous local startup/large-table changes, not from Git
HEAD alone. The exact starting package is archived locally in
`.cache/performance-20261020-round2/before.zip` (SHA-256
`8e61a1aba5495c0f9cd018b853806f63716ad1eea53657b75f9159373dffc5bd`).
The checkout was not reset. User changes in AGENTS.md, .vscode/settings.json
and docs/todos/ remain outside this work.

No tag, release, remote branch or installed package is changed. Timing gates,
source measurement strings, row mappings, fit/interpolation rules, complete
curves and export resolution are unchanged. All probes and tests isolate the
user's settings and recovery files.

## Diagnosis and retained changes

1. Dirty checks spent most of their time JSON-encoding repeated classification
   records. A recursive Python equality experiment was slower and was removed.
   The retained path uses the same JSON encoder without the per-container cycle
   hash table; recursion falls back to the original checked encoder. Actual
   Save still uses the original checked default. Differential tests cover key
   order, bool/int/float distinctions, signed zero, tuple/list, NumPy scalars,
   invalid values, cycles and mutation of an accepted baseline. No mutable
   baseline serialization is cached.
2. Row identities now normalize columns then zip their values, rather than
   creating a Python generator for each row. A bounded 16,384-entry row-string
   cache reuses only exact (columns, values, occurrence) encodings. Occurrences
   are still recomputed for each source, including reordered/subset duplicate
   identities. Tests compare keys byte-for-byte with the original encoding.
3. Parameter qualification is existential: check a small prefix first and
   inspect the complete remainder if no finite value is found. No parameter is
   dropped because its only numeric value occurs late in the column. Plotting,
   fitting and export still consume all selected data, not this prefix.
4. Exact source snapshots replayed by Undo can reuse the prepared Group plan.
   Both complete DataFrames (including dtypes/order/literal values) and the
   complete saved Group state must agree. A fresh plan shell binds the current
   sources without mutating the previous result. Changed values, literal
   precision or flags use the normal rebuild path.
5. The matching card and Group Trend now consume the same already prepared
   derived DataFrame within a single synchronous draw. Raw/global Card choices
   still use the corresponding full curve values, including missing-data gaps.
   This eliminates repeated series construction, not observations or plots.
6. Dense literal loads build cells in bulk and prepare the equivalent analysis
   view when a nonblank first column proves every row survives. Blank rows,
   ambiguous headers and sparse clipboard data retain the general path.
   A private ownership transfer avoids copying a dictionary created solely by
   the loader; public restore/Undo still copy their snapshots, and subclasses
   keep their restore hooks. Tests include reentrant edits during loading.
7. String-only Group state containers use shallow container copies; nested
   mutable structures still copy recursively. Redundant identity refresh after
   mark_clean is omitted only when no recovery state changed afterward.

## Verification

The intermediate 45-test performance group passed 44 tests; only opening the
6,000-row x 33-column Wafer Map exceeded its original 400 ms gate (416.515 ms).

The final production source was tested with
`.venv/Scripts/python.exe -X utf8 run_tests.py`: **866 tests in 702.609 s,
865 passed, 1 failed, 0 errors**. The only failure was
`test_saved_correlation_restores_complete_grouped_plots_promptly`, which took
2.3079055 s against the unchanged 2.0 s gate. All five timing failures from the
previous full run passed in this run. This is not an entirely passing suite:
saved grouped-Correlation restoration still has an observed timing limitation.
No functional assertion failed. Full log:
`.cache/performance-20261020-round2/full-tests.log`.

After the full suite stopped, the same six existing performance tests ran in
three fresh processes against the archived starting source, then three fresh
processes against the current source, on the same machine. No heavy test run
ran concurrently. Each probe used isolated settings/recovery/reminder and
Matplotlib paths and retained the original assertions. The table gives the
median of the three existing test measurements, not end-to-end application
startup or an installed executable benchmark.

| Existing timed scenario | Before (ms) | After (ms) | Reduction |
| --- | ---: | ---: | ---: |
| Five equal-source row-identity snapshots | 92.807 | 46.167 | 50.3% |
| Saved wide Workbook dirty check (best of three checks per test) | 77.827 | 63.941 | 17.8% |
| Paste and five keyboard Undo refreshes | 741.841 | 649.362 | 12.5% |
| Correlation checkbox changes (slowest change per test) | 139.479 | 138.216 | 0.9% |
| Restore complete saved grouped Correlation plots | 1912.674 | 1744.300 | 8.8% |
| Open 6,000-row x 33-column Wafer Map with current Cards | 555.239 | 371.445 | 33.1% |

Before: each of three six-test processes had two timing failures (Undo and
Wafer Map), totaling 12 passed, 6 failed, 0 errors. After: 17 passed, 1 failed,
0 errors across the 18 test executions. The remaining isolated failure was
one Undo measurement at 655.841 ms against 650 ms; the next two were 649.362
and 644.539 ms. Wafer Map passed all three at 370.454, 371.445 and 372.126 ms.
Saved grouped-Correlation restoration passed all three isolated runs, but
its full-suite failure above remains reported. The 0.9% checkbox difference
is too small to claim a meaningful further improvement. Passing isolated
probes is not a substitute for the full-suite result.

Raw measurements and assertion logs: `before.jsonl`, `after.jsonl`,
`before-assertions.log`, `after-assertions.log` in the diagnostics directory.
The diagnostic helper prints failed assertions and per-run failure counts;
its process exit status alone is not a passing-test signal.

Local diagnostics: `.cache/performance-20261020-round2/`; these are not release
payloads. The discarded equality experiment is not part of production code.
