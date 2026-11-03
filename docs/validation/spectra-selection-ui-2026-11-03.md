# Spectra selection and UI follow-up — 2026-11-03

Local work after source tag `v5-dev3` (`b50038a6806c4185c1691de19eddd943ceae6e02`).
These edits have not been committed, tagged or packaged.

## Completed behavior

- Export completion adds `Export Succeeded√` in bold green (`#15803d`) or
  `Export Failed×` in bold red (`#dc2626`), in both the dialog heading and log.
  Skipped originals, errors and cancellation do not report complete success.
  Retry/Skip details and no-overwrite/original-file copying remain intact.
- Die Map uses fixed white cards in three columns with scrolling, aligned page
  controls, per-card point/check/selection counts and larger 16px titles. Both
  X and Y axes show millimetres. The extra status legend and mouse instructions
  were removed as requested. A separator follows Check Unselected, before
  Uncheck Unselected. Check updates retain plots, sizes and coordinate ranges.
- Copy WKB Selection is a one-time Selection Script transfer for Spectra,
  Wafer Map, Correlation and Dynamic children. It copies check/uncheck, all filter
  conditions and AND/OR connectors, search, row display and Hide excluded rows.
  Other child types switch to Full data/local selection after copying. Their
  source tables are not replaced. Standalone windows have no WKB copy source.
- Participation matches Wafer ID, Lot ID, PAD Name and canonical Die only.
  File paths/names and row order do not determine transferred checkbox states.
  Unmatched target records retain their checkbox state. Conflicting duplicate
  identities are rejected before applying a partial result.
- Scripts carry string values for their referenced filter columns with the
  four-field identity. Missing target filter columns can therefore be shown as
  read-only selection context rather than silently removing the conditions.
  Existing target cells are preserved. Copied context is excluded from source
  identity resolution and survives `.spec`/local-view persistence. Reapplying
  a script refreshes the copied values rather than retaining stale context.
  When search is active, its source columns are included as well so a query
  matching Reference values also works in a target that originally lacked them.
- The existing version-2 JSON format remains supported. Clipboard application
  retains strict missing-identity validation; explicit WKB copying opts into
  matching a subset and retaining unmatched target states.
- Spectra children display their parent `.mwkb` filename after saving/Save As,
  with their accepted save baseline updated after successful durable save.
  A separately saved `.spec` shows its own filename and dirty state. Saving the
  parent does not falsely mark unsaved standalone `.spec` edits clean. Ctrl+S
  in a managed child still targets the Match Workbook.

## Focused verification

The final focused command passed **44 tests**:

```text
python run_tests.py tests.test_selection_script tests.test_spectra_workbook tests.test_spectra_map -v
```

Acceptance cases cover the actual child menu actions, visible Data selection
filter controls and script contents, check states, four-field matching after
reordering/renaming, missing filter data, repeated copying, `.spec` restoration,
source preservation, export success/failure formatting, fixed map dimensions,
Y labels, parent Save As and independent Spectra save titles.

Real `JC1913/matching-analysis.mwkb` validation used the original 1,890-row
tables and current selection. It matched 1,890 spectra; 1,869 Workbook checks
were copied and one unmatched checked spectrum was retained. The target
Data selection displayed the `AI01750.00-06` condition, Filtered rows and checked
Hide excluded rows. Its generated Selection Script contained the same filter.
Parent selection and hashes of 3,896 source files (including the WKB) were
unchanged. The 12 visible Die Map cards kept their identity, size and ranges
across check changes. Light and dark captures were inspected.

An original-file export check copied 1,870 selected SME files and verified every
output SHA-256 against its source. A separate real BBSE original was copied and
then deliberately exported to the same destination: success was green/bold,
overwrite refusal red/bold, with font weight 700 and unchanged source bytes.

All validation used scratch settings, recovery, reminders, Matplotlib and
temporary paths. `config/settings.yaml` was not changed. AutoWeighting remains
deferred and was not tested.

## Deferred regression

The user explicitly requested no further full regression until asked. Final
Selection Script and UI follow-ups above therefore have focused validation only.

An earlier scoped run, before this deferral and before the final script-copy
changes, ran 1,378 tests with four failures: the existing fake Correlation
workspace missing `raw_model`, Correlation pagination pending-state assertion,
literal-frame read-only assignment, and a scratch-settings replace permission
error in stage-specific literal-ID setup. Restricted-environment attempts also
encountered SQLite temporary-directory and hard-link permissions; that directory case and an
intermittent precision check passed focused retries. These results are not a
claim of full-suite success for the current working tree.

Machine-readable focused and real-file results are in the adjacent JSON file.
