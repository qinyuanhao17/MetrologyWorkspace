# Legend context menu, wafer rectangle selection and BSL cancellation

The final controls follow the user's UI corrections:

- Show All is in each legend section's right-click menu, including the empty list area and section header. The four header buttons have been removed. The existing per-section channel restore operation and cached curves remain unchanged.
- Tree right-click Clear BSL is enabled whenever a baseline exists, including with no selected rows. It clears the identity label and bold baseline marker, preserves checked/selected source spectra, disables Residual and returns to Original if Residual was active. 3σ can remain active because it does not depend on BSL.
- Left-drag on a wafer map shows a native PyQtGraph rectangle and selects the contained point centers. All spectra at a coincident point are included. Normal drag replaces selection; Ctrl/Shift drag adds points. An unmodified empty rectangle clears selection. The same selection signals synchronize tree entries and spectral highlights. Wafer axis ranges, scale and outline remain unchanged.

The wafer behavior uses a ViewBox drag handler with PyQtGraph's existing rectangle item and view-to-data transformation; it does not intercept raw viewport coordinates or redraw wafer data during movement.

## Verification

`python run_tests.py tests.test_spectra_analysis tests.test_spectra_viewer tests.test_spectra_map tests.test_sme_spectra -v`: **88 passed**, 33.431 seconds. Checks exercise the actual popup event loop and Show All action, confirm no Show All QPushButtons remain, clear BSL with no row selected, and drive mouse press/move/release for normal, reversed, Ctrl, Shift and empty wafer rectangles. Real mouse waits allow PyQtGraph's movement rate limiting to deliver separate drag events.

```powershell
python scripts/verify_spectra_analysis.py "C:\Users\Yuanhao Qin\OneDrive\Desktop\JC1913" docs/validation/spectra-controls-grr10-2026-11-02.json --grr10
```

The ten-file GRR probe rechecked residuals/3σ against independent calculations, restored legend visibility through its menu, cleared BSL while keeping all checks, and drew a real wafer rectangle. All ten contributing spectra were selected in the map, tree and spectral panel, with no wafer range change. Source numeric hashes stayed unchanged. Updated images are `qa_spectra_residual_grr10.png`, `qa_spectra_3sigma_grr10.png` and `qa_spectra_map_box_grr10.png`.

Broad results are recorded in `spectra-controls-regression-2026-11-02.json`, excluding AutoWeighting-related modules at the user's request. The earlier numerical implementation and 594-file validation remain documented in `spectra-analysis-2026-11-02.md`; its initial button layout was superseded by this context-menu update.

The controls broad run completed **1,319 tests** (677 + 642), with two failures and two errors already seen in previous baseline runs: Correlation pagination's pending-state assertion, a fake Correlation workspace without `raw_model`, pandas read-only literal-frame assignment, and the separate Matching Wafer Map opening-time threshold. All Spectra tests passed. The subsequent menu-divider, caption-distance and Mueller-tick changes are verified in `spectra-presentation-2026-11-02.md`.
