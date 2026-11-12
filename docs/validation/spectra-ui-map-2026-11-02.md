# Spectra Viewer appearance, map layout and legend visibility

The Match Workbook and standalone entry points now apply the same application
stylesheet when constructing Spectra Viewer. Both follow live light/dark theme
changes. The Workbook child's Ctrl+S / Ctrl+Shift+S still target its owning
Workbook; separate `.spec` menu saves remain available.

Long wafer titles previously imposed a minimum width on the PyQtGraph scene.
Small fixed map viewports then clipped the scene, hiding the right half of the
wafer. Titles now wrap in the surrounding tile, outside the graphics scene.
The map grid adapts its row/column count to the available window size, reuses
plots on resize and releases unused row/column space on the final page. Native
arrow icons replace font-dependent pagination glyphs. Plot backgrounds remain
white; coordinates, wafer scales, point selection and rectangle selection keep
their existing behavior.

The legend context menu now contains Show All and Hide All. These operate on
the channel/color groups listed in the clicked legend, consistently with the
existing per-group toggle. Hiding does not uncheck or deselect source spectra,
reset manual axes, or clear hidden keys absent from that legend. Both actions
are disabled when there is nothing for that action to change.

Applying the complete stylesheet also exposed two layout constraints. The
initial empty plot panel no longer squeezes the tree below its quarter-width
default. Footer space is reserved after controls inherit their final style, so
showing loading progress does not resize the plot viewports.

## Validation

The focused run passed **123 tests** using `python run_tests.py` with
`tests.test_spectra_workbook`, `tests.test_spectra_viewer`,
`tests.test_sme_spectra`, `tests.test_spectra_analysis`,
`tests.test_spectra_map` and `tests.test_named_analysis_windows`.
The three new acceptance scenarios in `docs/features/spectra_viewer.feature`
map to executable tests for entry-point/theme parity, full-wafer viewport
containment and the Hide All / Show All workflow.

Real-data validation loaded **1,890 SME files with zero issues** from JC1913
at Qt scale factor **1.25**. All outline cardinal points and measurement points
were inside their actual viewports at 1600 × 1000 and 960 × 650, and on the
six-wafer last page. There are 90 wafers over eight pages. Standalone and
Workbook viewers used identical stylesheets. The machine-readable result is
`spectra-ui-map-real-2026-11-02.json`; screenshots were visually inspected.

Repository-wide scoped regression results are recorded in
`spectra-ui-map-final-regression-2026-11-02.json`. The five previously deferred
AutoWeighting-related modules remain excluded. All probes and tests use
scratch settings, leaving the user's production settings untouched.

The final run executed **1,339 tests** across all 107 non-deferred modules:
**1,336 passed**, with the same three pre-existing issues recorded before
these changes (one assertion failure and two errors):

- `FakeCorrelationWorkspace` lacks `raw_model` in the Correlation button test.
- The Correlation pagination/filter/threshold test has a pending-page assertion.
- The literal-frame source test assigns into a read-only pandas array.

Spectra tests passed in both the focused run and this broader run. This is a
successful focused validation, not a fully green repository-wide regression.
`git diff --check` also passed.
