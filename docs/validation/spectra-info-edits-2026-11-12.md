# Spectra Info report columns, flags and undo

Date: 2026-11-12. Local development, no publication. Full-suite testing remains
deferred by the user; AutoWeighting was not run.

## Delivered behavior

- All three Info tabs share the same source pairing and row sequence: actual
  original Raw Data order when available, otherwise natural Wafer/Lot/PAD/Die/Time
  order with a stable source-path tie break.
- Header and table context menus offer Delete Column, or Delete Columns for
  selected whole columns. Deletion removes that tab's report columns and shifts
  following columns left. Copy Table, selected-cell copy and CSV see the projected
  frame. Other tabs and source SME/Raw/Reference data remain intact.
- Deleted-column preferences are stored in the existing child draft UI payload,
  so both WKB child capture and .spec persistence retain them. Old documents
  default to no removed columns and malformed settings are rejected before restore.
- With Test Flag supports direct integer editing. Each displayed row carries its
  exact spectrum key from the pairing result; it never uses a catalogue row
  position to choose the spectrum. Invalid nonintegers leave state unchanged.
- Flags share the existing Viewer state used by Die Map. 1 is green, -1 red and 0
  absent. Both map context-menu assignments and report edits refresh the report
  and map. Map widgets, scatter items, view ranges and spectrum check states are
  retained; flag edits do not invoke spectrum-curve rebuilding.
- Viewer, Info and its Die Map install window-local Ctrl+Z / Ctrl+Shift+Z actions
  backed by one QUndoStack for flag assignments and report-column deletion. Commands
  retain small deltas rather than copying spectral arrays. Loading a replacement
  document clears history. Undo history itself is not persisted.

## Verification

Red/green tests first failed on the absent context-menu entry point, read-only
Test Flag cells and missing report-projection persistence. The completed command:

```powershell
& 'C:\Users\Yuanhao Qin\.conda\envs\metrology-workspace\python.exe' run_tests.py tests.test_spectra_info_edits tests.test_spectra_info_xy tests.test_spectra_info tests.test_spectra_workbook tests.test_spectra_map tests.test_selection_script -v
```

**73 tests passed in 20.230 seconds**, using scratch settings. The four new tests
cover projection/copy/export/source preservation, exact row-to-Die flag identity,
integer validation, incremental map state, actual keyboard shortcuts in Info and
Die Map, .spec persistence, all-tab row order and flag reset. Existing WKB capture,
restore, clipboard, flags, maps and selection-script tests also passed.

The real-file probe reads Raw/Reference from
`JC1913/matching-analysis.mwkb` (1,890 Raw rows) using native SQLite fetches and
loads three actual original SME files. It verifies:

- Shared original Raw row order across all tabs.
- Deleted Lot ID omitted from that tab's report CSV, without source mutation.
- Editing two Info flags produces a green and red marker on the matching Dies;
  zero has no marker. Undo and Redo restore the shared values.
- Existing map object and coordinate ranges, and spectrum checks, remain unchanged.
- The standard WKB/.spec child draft restores report projection and flags.
- Workbook SHA-256 and all three original SME hashes remain unchanged.

The generated map image was inspected; the green and red flags are visible beside
their corresponding blue points. Source measurements were never overwritten.

Evidence: [spectra-info-edits-2026-11-12.json](spectra-info-edits-2026-11-12.json).
Local probe: `.cache/validate_spectra_info_edits.py`; outputs and screenshot are in
`.cache/spectra-info-edits-validation/`.

BDD scenarios in `docs/features/spectra_viewer.feature` map to the executable
tests in `tests/test_spectra_info_edits.py`. This is focused validation, not a full
regression run. Production `config/settings.yaml` has no worktree modification.
