# Die Map fixed tiles and original-SME export recovery

## Observable changes

- `Check Unselected` / `Uncheck Unselected` apply only to unselected points in
  the wafer where the menu was opened. Other wafers and selected points retain
  their checks. Menu tooltips state the scope; no wafer context disables them.
- Die Maps use three fixed columns, 400 × 400 pixel plots, fixed title space
  and a scrollable page. Loading, checks and window resizing do not rescale the
  maps. Pagination, rectangle selection, gray unchecked points, double-click
  checks, similar-wafer transfer and blank-space deselection remain available.
- `Export Checked Spectra…` opens a nonmodal child with progress, Retry, Skip
  and Cancel. It copies original bytes with their folder hierarchy. Unavailable
  originals are handled individually; the completed report lists all unresolved
  source paths and error messages without a ten-file truncation.
- Retrying reopens the original path, so a restored file can be copied. Skipping
  retains other successful copies. Cancellation, closing or Esc interrupts a
  waiting decision and rolls back only files created by that export. Existing
  destination files are not overwritten, and SME content is never generated.

## Root causes and fixes

The map layout redistributed available space while maps were added one at a
time. Each tile's resize handler then resized its PlotWidget, causing another
layout calculation. A real 252-spectrum/12-wafer page produced fourteen visible
plot resize notifications while opening (316 pixels down to roughly 216), and
another change when the window narrowed. The same probe after fixed sizing
recorded zero visible plot resize notifications, with plots set to 400 × 400
before display. Small windows expose both scrollbars instead of shrinking maps.

The exporter previously rejected the complete batch if any original was absent.
Also, retaining folder hierarchy in a batch can make a target exceed Windows'
traditional 260-character limit even when a single-file export stays below it.
The executable regression reproduced single-file success followed by batch
`FileNotFoundError` / `WinError 206` (reported as Errno 2). Native extended paths
are now used for filesystem access in both copying and SME scanning/reading;
normal source identities and displayed folder names stay unchanged.

Filesystem copying remains separate from the Qt worker and recovery dialog.
The worker waits on a condition for GUI decisions and checks cancellation while
waiting. Qt widgets are changed only on the GUI thread.

## Validation

The relevant failing cases were reproduced before their fixes. The final SME,
Viewer, Die Map, calculation, Workbook, Selection Script and export suite passed
**130 tests**. The scoped repository regression ran **1,365 tests**, with 1,362
passing and the same three existing Correlation/pandas failures as the v5-dev
baseline; no new failures. Five explicitly deferred AutoWeighting-related
modules were excluded. All settings paths were scratch files.

Actual JC1913 validation copied **1,891 existing SME files**, compared every
source/target SHA-256 and verified the sources were unchanged. All 1,891 exported
files were read back successfully, including a 265-character target path.
Separate native UI checks exercised Retry, Skip, final missing-file reporting,
Esc cancellation and the fixed-map scrollbars. Screenshots remain under
`.cache/die-map-export-ui/`; copied measurement fixtures are under the ignored
`.cache/checked-sme-export-*/` directory. No published package or tag was updated.

Details: [structured results](die-map-export-2026-11-03.json).
