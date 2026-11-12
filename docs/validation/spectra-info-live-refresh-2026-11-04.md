# Spectra Info live source refresh — 2026-11-04

## Cause and change

An already open Spectra Info report listened to the Spectra Viewer's own
state changes, but not its owning Workbook's editable source tables. Editing
a Reference value or column name left the visible report stale until Refresh,
reopening, or a separate Viewer state change. Copy/export explicitly rebuilt
the report, so they could disagree with what was still displayed.

The Workbook child now queues the same coalesced report refresh when Reference,
Preview Raw Data, Final Raw Data or the active Preview/Final mode changes.
Binding a replacement report source also queues an update. This notification
does not emit a Spectra state change, rebuild spectral curves, change spectrum
checks or alter source measurements. Existing metadata matching, timestamp
verification, original-row ordering and source-field precedence are unchanged.

Both report tabs use the current source values. Invalid pairings immediately
show their issues and disable copying/export; correcting or undoing the source
edit restores availability. Reimported spectrum metadata, local Test Flags and
checked-spectrum changes use the existing Viewer state notification.

## Validation

- Reproduced the stale Reference value in a failing executable GUI regression
  before the production change.
- All 33 Spectra Info and Spectra Workbook focused tests passed in 13.537 s.
  Three added workflows exercise live Reference value/header edits, Raw Data
  pairing errors and undo, active-mode changes, reloaded SME metadata, check
  changes, both tabs, clipboard and CSV. They inspect the already open table
  before invoking any explicit report refresh/copy/export action.
- A native Windows probe loaded the supplied
  `JC1913/matching-analysis.mwkb` and its embedded spectra. All 1,890 report
  rows were available. Live Reference edits, a renamed Reference column,
  reloaded Tool SN metadata and Test Flag changes appeared in both tabs;
  copied/exported rows contained the current values. Unchecking one spectrum
  automatically reduced both tabs to 1,889 rows.
- Source WKB SHA-256 stayed
  `a4f62dc43f469855ad4d74ce763fa728d47a22d15217582dc4223d1ce689ad74`.
  The production settings file's SHA-256 also stayed unchanged. Probe edits
  were in memory and were discarded, not written to the source WKB or SME.
- The full non-deferred repository regression ran 1,424 tests in 533.704 s
  through `run_tests.py` with isolated settings: 1,422 passed and two had
  environmental setup errors. The long-path export fixture could not create
  its source file beneath the excessively long workspace temporary directory;
  the storage alias fixture was denied permission to create a hard link in
  the sandbox. Neither error occurred in the Spectra Info update path.
- Both failed tests were rerun unchanged outside the sandbox, using the normal
  Windows temporary directory and the same isolated settings runner. Both
  passed (2 tests, 0.249 s). There was no second complete-suite run; these
  results distinguish the initial full run from the successful focused
  environment recheck. No test or application workaround was added for these
  environment limits.
- The three AutoWeighting modules (`test_auto_weighting`,
  `test_auto_weighting_ocr`, `test_auto_weighting_window`) remain excluded
  at the user's explicit request. `git diff --check` passed.

Subsequently, after the requested Mueller label and SME export-root updates,
the entire non-deferred suite was rerun in the normal Windows temporary
directory: **1,424 tests passed in 530.586 s**, with no failures/errors/skips.
This includes all live-refresh checks above. See
`spectra-labels-export-root-2026-11-04.md` for the later complete-run evidence.

BDD examples are in `docs/features/spectra_viewer.feature`; executable workflows
are in `tests/test_spectra_info.py`. Probe scripts, focused/full logs and the
real-file JSON are under `.cache/info-refresh-tests` and
`.cache/verify_spectra_info_refresh_real.py`.
