# Repeated OCD case editing: fixes and verification

All reproductions use synthetic data. No confidential case files are required.
Executable workflow scenarios are in `docs/features/case_switching.feature`;
regression tests are in `tests/test_case_switching.py` and the existing suites.

## Causes and boundaries

- A whole-table paste at B2 could add a tail row which remained after cutting
  that exact pasted rectangle. The cut now retracts only the receipt's added
  rows. Original blank records remain; Undo/Redo restores extent and values.
  This does not globally trim blank records or alter hidden-row mappings.
- Ordinary Ctrl+V is still an overlay, not a silent whole-table replacement.
  Existing mismatch choices and protection against overwriting hidden rows
  remain. Cells outside the pasted rectangle are not deleted.
- Map derivation used to replace a mapped Raw column with its Match alias and
  coerce its literal values. Uncarded linked tables now retain all original Raw
  columns and strings, adding only noncolliding aliases. A uniquely mapped Raw
  column receives its own fitted Card when the plotting option is enabled.
  Calibrated stage derivation reads original inputs even when aliases overlap.
- Combined header/value paste could leave mapping controls pointing at an
  absent old Raw name. Only an unambiguous existing Reference-name equivalent
  is recovered; no fuzzy or positional guess is made for a new case.
- Ref identity initialization could leave newly recognized measurements
  unchecked, or override manual grouping during an unrecognized intermediate
  state. New identity detection and explicit grouping choices are now distinct.
- A user column named `Source`, or duplicate headers in one source, could block
  otherwise valid source plots. Internal source labels avoid user names, and
  invalid sources do not invalidate their valid peer. The original tables and
  duplicate-header warning remain editable and intact.
- Independently identified Ref plots are not gated by equal Ref/Raw lengths.
  Cross-source Correlation still requires row-aligned source tables: this fix
  does not invent pairs or change regression rules.
- A failed linked child refresh is no longer cached as a successful update.
- The floating Raw tool no longer has a native Workbook transient owner. Its
  editor, Undo history, theme and Workbook-close lifecycle remain shared.
- Match equation and R-squared labels support selection and native copying.

## Same-environment interaction measurement

Workload: 1,200 rows, 35 Raw columns, 30 wafers, one mapped parameter; Map and
Correlation/Trend windows open, with both Correlation and Trend drawn. Map
plots are not drawn in this benchmark. Each repetition overlays changed Ref
and Raw at A1 and waits for analysis, linked updates and debounce timers to
settle. These are warm editing wall times, not cold startup or CPU-only times.

| Measurement | Three unprofiled repetitions (ms) | Median (ms) |
| --- | --- | --- |
| Before this fix | 964.268, 917.554, 920.815 | 920.815 |
| Final verification | 914.198, 819.565, 837.250 | 837.250 |

The median decreased about 9.1% for this workload. Two earlier after-fix batches
had medians 852.517 and 837.117 ms; this is not a claim about all app operations.
Single-column text without any candidate delimiter no longer invokes the CSV
delimiter sniffer. Comma/semicolon inference and quoted-field parsing retain
their existing paths. Recognition publishes a combined source plan rather than
an intermediate inconsistent one.

The clearly marked local debug harness is
`.cache/debug-case-switching/test_benchmark.py`. Reproduce through settings
isolation, never by running an application script against the real settings:

```powershell
.venv\Scripts\python.exe -X utf8 run_tests.py discover -s .cache/debug-case-switching -p test_benchmark.py -v
.venv\Scripts\python.exe -X utf8 run_tests.py tests.test_case_switching tests.test_correlation_source_identity -v
.venv\Scripts\python.exe -X utf8 run_tests.py
```

Before/after logs are `before.log` and `after-verified.log` in that debug folder.
Source-frame equality, Card coefficients, alias-overlap calculations and source
plot workflows are verified by tests; no interpolation, color scale, units or
regression model was changed for speed.

## Final verification

- Environment: Windows, repository `.venv`, Python 3.10.20; offscreen Qt with
  the runner's isolated settings, recovery and reminders locations.
- Final source-focused run: 44 tests passed in 33.620 seconds (case switching,
  source identity and Workbook copy/lock/save/reopen workflows).
- The broader Ref/Raw/Correlation/visibility run passed 121 tests in 59.618
  seconds before the source-string expectation was strengthened.
- Final full command: `.venv\Scripts\python.exe -X utf8 run_tests.py`.
- Final full result: **931 tests, 731.855 seconds; 930 passed, 1 timing failure,
  0 errors**. Log: `.cache/debug-case-switching/full-tests-final.log`.
- Remaining failure:
  `WorkbookPerformanceTests.test_saved_correlation_restores_complete_grouped_plots_promptly`.
  Restore elapsed **2.1795414999942295 seconds**, required **<2.0 seconds**.
  Both pages, selections, all six fits and coefficients, all 12,000 Trend
  positions and the exact Raw source frame passed their assertions before the
  elapsed-time check. This is not an all-green full suite.
- An earlier full run also found an obsolete expectation that copied `9.100`
  should become `9.1`. The test now requires the exact original string and
  additionally compares all unlocked source columns; coordinate-lock and
  save/reopen assertions are unchanged and pass. No performance thresholds were
  changed or tests deleted.
- Floating-window verification checks the actual native Qt transient owner,
  topmost flag, shared editor and close lifecycle. No live desktop activation
  screenshot test was performed.
- Real `config/settings.yaml` SHA-256 stayed
  `71B4F4C7748749ED3AAC253DAE7740B80395742B32A9CC392ED2DC8C05BDC39D`.
- `git diff --check` passed. No package, commit, tag or GitHub write was made.
  The 17-byte Setup mentioned in test output is an installer test fixture, not
  a distribution artifact.
