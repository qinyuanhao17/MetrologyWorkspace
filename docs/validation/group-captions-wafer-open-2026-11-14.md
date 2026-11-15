# Group captions and Wafer window opening

Date: 2026-11-14. Continuation of the two outstanding checks in
`group-script-menus-colors-2026-11-13.md`. Earlier uncommitted workspace changes
are included in the regression runs.

## Behavior

- Group captions carry structured Group/Wafer/Lot/PAD fields alongside the
  existing display string. Map and Radius screen renderers and Matplotlib
  exports use those fields to apply their independent PAD/Lot switches.
  Literal names containing `PAD:`, `LOT:` or middle-dot separators are retained.
  Legacy typed captions remain supported. Caption updates retain surfaces,
  selected boxes and measured values; repeated unchanged input reuses exports.
- Group context copying uses the existing container-copy helper. Metadata
  captions read only identity columns, without repeatedly slicing wide tables.
  Wafer classification context retains flags, Marks and source identities;
  actual Workbook participation is carried separately, including exclusions.
- Initial Wafer data, Card options, selections, participation and Groups are
  committed through one existing input transaction before accepting the clean
  baseline. Saved/recovered child drafts are restored after that acceptance.
- Dense literal sheet loads reuse the existing immutable table version and
  copy-on-write cell view. Sparse data, clipboard replacement, subclass restore
  hooks and unsupported/cyclic metadata retain the general storage path.
  Already-literal object strings avoid redundant string conversion.
- Wafer dirty comparisons consume read-only snapshots. Accepted baselines
  remain detached using the existing snapshot-freezing function, retaining
  snapshot warnings. Public snapshots remain independently editable.
- The test runner resolves the default temporary directory before creating
  fixtures. This makes native Windows 8.3 TEMP aliases consistent with resolved
  saved paths, preserving fault-injection, cancellation and path assertions.

## Measured opening latency

The existing public workflow regression uses 300 wafers x 20 dies, 6,000 rows
and 33 columns. It asserts current Card coefficients, 5,999 participating rows,
and a correct immediate reopen after source edits before queued analysis runs.
The existing **0.4-second** opening limit is retained.

Before: **0.804399 s**, reproduced at the start of this continuation.
Final repeated native-process measurements: **0.201918, 0.360004, 0.366982 s**;
median **0.360004 s**. All three opening checks passed in one process.
These are method-level opening measurements for this fixture, not a claim
about every dataset or first-paint latency.

Evidence: `.cache/group-followup-before-20261114.log`,
`.cache/wafer-open-before-20261114.prof`, and
`.cache/wafer-open-after-20261114.json`.
Repeat probe: `.cache/measure_wafer_open_20261114.py` (isolated test settings).

## Verification

Interpreter: `C:/Users/Yuanhao Qin/.conda/envs/metrology-workspace/python.exe`.
Tests use `run_tests.py` with scratch settings, recovery and reminder paths.
Native execution is used for Windows hardlink and long-path checks.

- The original label-switch and opening tests reproduced their failures before
  the changes. New acceptance coverage checks independent Map/Radius switches,
  literal metadata-like names, exported snapshot ownership and general sheet
  metadata fallback. An unchanged-input export-reuse check and cyclic metadata
  fallback check also demonstrated failure before their corrections.
- Sheet/version/ownership/metadata-lock verification: **55 tests passed**.
  The later cyclic-metadata fallback check also passed.
- Caption/Group/sheet acceptance: **19 tests passed**.
- A broader focused run passed its 118 selected valid cases; its sole loader
  error was a reference to the nonexistent `tests.test_sheet` module. The
  corrected sheet modules are covered by the 55-test run above.
- Recovery publication/cancellation, recent-path behavior and test-environment
  isolation: **7 tests passed** after temporary-directory normalization.
- The product-complete full run executed **1,539 tests in 986.873 seconds**;
  the original opening-budget check passed. Its sole failure checked for a
  completed initial 24-map render after a fixed 600 ms. The view-preservation
  test now uses the existing bounded rendering-completion helper (8 seconds),
  preserving all zoom, scroll and page assertions. It then passed three times
  consecutively; the combined caption/Group/view recheck passed **18 tests**.
- Final full suite: **1,539 tests passed in 988.953 seconds**, exit code 0.
  This run includes the earlier workspace changes and the final rendering-wait
  correction. The original opening-budget check passed in the full run.

Logs: `.cache/group-followup-sheet-check-20261114.log`,
`.cache/group-followup-final-acceptance-20261114.log`,
`.cache/group-followup-final-focused-20261114.log`, and
`.cache/group-followup-final-full-20261114.log`, and
`.cache/group-followup-verified-full-20261114.log`.

The exploratory native full run completed 1,538 tests before the final loader
optimization and runner correction. Its short-path fixture comparisons and
opening-budget failure drove the final checks; it is not the final result.

Final `git diff --check` passed. The real `config/settings.yaml` was unchanged
through the final full run (SHA-256):
`DBC30E7CA71B7E8375C7511F264E0B24DB568FFF965CEC4D635CC0997073C01C`.
