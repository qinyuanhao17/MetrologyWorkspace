# Independent .spec documents — 2026-11-02

Spectra Viewer now supports typed `.spec` files using the existing atomic SQLite
workspace store and WkbDocument save/revision/recovery handling. The document
embeds the same original numeric arrays, channel/source identity and UI choices
used by the Match Workbook integration. Original SME paths need not exist when
opening a saved file. Previously decoded records are retained in the encoding
cache instead of immediately recompressing the same sources.

File has Open Spectra File, Save Spectra and Save Spectra As. The application
shell routes `.spec`, including its ordinary open/recent/drag-drop entry points,
to Spectra Viewer. Existing typed-file suffix and revision protections apply.
Unsupported settings and inconsistent source identities are checked before
replacing live spectra. Opening an empty viewer does not create false unsaved
changes: initial layout is accepted only when source/control choices are
unchanged, and axis numbers are serialized with consistent numeric types.

In a Match Workbook child, Ctrl+S saves the owning Workbook and Ctrl+Shift+S
opens its Save As flow. Independent `.spec` saves remain explicit menu actions
without those shortcuts. In a standalone viewer the shortcuts target `.spec`.
Saving a `.spec` neither writes nor accepts the owning Workbook's pending data.
The published `v5.0.0` tag is unchanged by this local work.

Validation uses public file APIs and actual keyboard events. Coverage includes
portable round trips, BSL/check states, shell routing, competing-window revision
conflicts, Cancel on close, invalid-file data retention, first-show dirty state,
and managed versus standalone shortcut dispatch. The first broad focused run
passed 155 checks. The latest shortcut-specific integration run passes nine
checks. The full scoped run is recorded in
`spectra-spec-shortcuts-regression-2026-11-02.json`; the previously deferred
AutoWeighting-related modules remain excluded. All runs use scratch settings.

The final scoped repository run executed **1,336 tests** (694 + 642). Spectra,
file persistence and shortcut tests all passed. The whole repository still has
the same three pre-existing issues: Correlation pending-state assertion,
FakeCorrelationWorkspace missing `raw_model`, and pandas read-only literal-frame
assignment (one failure, two errors). The nine integration checks also pass at
Qt scale factor 1.25. No production settings or the published source tag changed.
