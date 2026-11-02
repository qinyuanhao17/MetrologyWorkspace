# Spectra View All selection fix — 2026-11-02

The real mouse click on PyQtGraph's lower-left A button also reached the
application's scene-click selection handler. PyQtGraph's ButtonItem emits its
clicked signal without accepting that scene event. The application's curve hit
test found no curve at the button position and cleared the linked selection.
This removed the thick selected-wafer overlay and exposed the other wafer colors;
the palette assignments themselves had not changed.

The panel now records an A-button hit on viewport mouse press, before auto-range
can hide the button, and excludes that click from spectrum selection. Accepted
scene events are also left to their existing handlers. Axis navigation preserves
selection and highlights; actual chart whitespace still clears selection.
No source data, color assignments, analysis calculations, or raster rendering
algorithms were changed.

## Verification

- Added an actual QTest mouse-click regression, rather than invoking the button's
  signal directly. It verifies full tight X range, unchanged color groups, linked
  tree selection and the same highlight items in summary, dual-axis, Mueller and
  floating plots. The original implementation failed this regression by clearing
  the selection.
- Spectra/parser/map plus the shared dense dashed-curve screen/export regression:
  **94 passed** in 39.111 s. Ordinary curve, Ctrl multi-selection and blank-space
  selection checks remain covered.
- At Qt scale factor 1.25, actual A-button and curve/blank-space mouse workflows:
  **2 passed**.
- JC1913 currently contains **1,161 readable spectra**, with no load issues.
  The real-file probe checked all spectra, selected a 21-spectrum wafer and
  clicked the actual A button in four plot variants. All 33 color groups,
  tree selections and highlight items were preserved while restoring the full
  wavelength range. This exercises the many-color batched rendering path too.
  See `spectra-view-all-real-2026-11-02.json`.

The complete regression excluding the five previously deferred AutoWeighting-
related modules ran **1,324 tests** (682 + 642) through isolated `run_tests.py`
shards. It is **not fully passing**: the same Correlation pending-state assertion,
FakeCorrelationWorkspace missing `raw_model`, and pandas read-only literal-frame
assignment remain. An additional existing 400 ms Wafer Map opening limit measured
0.400258 s in this parallel run; that test **passed on an isolated rerun** after
the shards finished. No Spectra tests failed. See
`spectra-view-all-regression-2026-11-02.json`; logs are recorded there, and the
isolated timing rerun is `.cache/spectra-view-all-window-timing-recheck.log`.

Settings were isolated through `run_tests.py` / `isolate_settings`; production
`config/settings.yaml` was not modified. AutoWeighting work remains deferred.
