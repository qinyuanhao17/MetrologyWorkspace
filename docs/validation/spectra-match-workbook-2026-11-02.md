# Match Workbook Spectra integration — 2026-11-02

## Publication boundary

Before changing integration code, the current application was committed as
`021a8a4f267f6a4d47ac39096e2ef96af1b564c0` and pushed as annotated tag `v5.0.0`.
Remote dereference was checked against that commit; remote main remained
`aa5281dd38bbe58688a51b27e86c70635aef7a77`. No branch or binary assets were pushed.
Local Excel files were excluded. The integration below is subsequent local work,
not part of that immutable tag.

## Behavior and storage

Open Spectra Viewer is a workbook-wide named child entry, available without
matching input tables. It uses the existing New/Open checked/Rename/Delete menu
and a dedicated child registry, avoiding accidental participation in Card or
linked Raw Data refresh. Closing a child retains its draft in the parent; parent
save and unsaved-change decisions include live Spectra children. Loading another
Workbook or closing the parent closes its Spectra children. Save Match Workbook
and Ctrl+S in the child delegate to the owning Workbook.

Each embedded spectrum retains its original key/path, identity, metadata,
coordinates, all channel matrices and wavelength arrays. Arrays use numeric-only
NPZ, zlib level 1 and base64 in an ordinary typed WKB frame, with pickle loading
disabled. No source-path re-read is needed to restore spectra. Encoded records
are cached by source-object identity; managed folder loads prepare them in the
loading thread with per-file cancellation. Checkbox and legend changes reuse
those records. No source SME is modified.

The child stores checked/selected sources, BSL, Original/Residual/3-Sigma,
Filter By and Color By, assigned colors, hidden groups, available views, expanded
tree branches, manual primary/secondary axes and the nine splitter sizes.
Automatic axes are recalculated, not saved as size-dependent bounds, avoiding a
false dirty marker on reopen. Old WKBs without Spectra entries remain valid;
Spectra-bearing WKBs require this integration build. Standalone Spectra Viewer
remains available.

## Validation

The focused Spectra, parser, map, named-child and integration run passed **115
tests**. A subsequent four-test integration run also passes, including manual
Delta-axis restoration. The mixed-instrument test loads the original 42-file,
47-channel fixture through the managed worker, saves WKB, removes only temporary
SME copies, and verifies every restored channel array and source identity. Tests
also cover closed-child reopening, dirty state after edits, clean state after
save/reopen, and deletion without changing another Spectra child or Dynamic
selection. Settings are isolated through `run_tests.py`.

Repository-wide results are recorded in
`spectra-match-workbook-final-regression-2026-11-02.json`; the explicitly deferred
AutoWeighting-related test modules remain excluded.

The final complete scoped run executed **1,331 tests** (689 + 642). All Spectra
and integration checks passed. The repository remains not fully green because
of the same three baseline issues: Correlation's pending-render assertion,
FakeCorrelationWorkspace lacking `raw_model`, and the pandas read-only literal
frame assignment (one failure, two errors). No installer/build claim is made.
