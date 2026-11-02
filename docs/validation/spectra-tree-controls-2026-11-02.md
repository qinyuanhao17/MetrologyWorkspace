# Spectrum classification, statistics, deletion and native axis menus

## Delivered behavior

- The duplicate idle `Loaded … spectra · … channels` footer is removed. The tree summary remains the single completed-load statistics display. Loading/drawing progress, cancellation and failed-replacement messages retain the reserved footer space without resizing the plot grid.
- Channel count is the number of unique `(instrument, AOI, AZI)` combinations. If either angle is unavailable, `(instrument, Channel ID)` is used instead. Die/file repetitions and different channel IDs for the same known geometry do not multiply the count. Per-file channel records and raw metadata are preserved: the supplied 42-file fixture still has 47 channel records, while its angular-channel summary is 9.
- `Filter By` replaces the SPECTRA heading with Wafer ID, Lot, PAD Name and Die choices. Wafer mode retains Wafer → Lot → PAD; Lot mode uses Lot → Wafer → PAD; PAD mode uses PAD → Wafer → Lot; Die mode uses Die → Wafer → Lot → PAD. Spectrum rows are still created lazily at the terminal group. Die groups use numeric ordering. Classification changes retain original source identities, checked/selected spectra, current plot groups and zoom.
- `Delete Tree` follows the user's explicit choice: only selected spectrum rows or data branches are removed from the session, including folded branches. Nothing is removed from disk. Unselected records and participation remain. No-selection deletion is disabled, and deletion is disabled during a folder read to prevent an incoming load from restoring deleted data unexpectedly. Maps, summaries and plots are synchronized after removal.
- Main and floating spectral plots use native PyQtGraph ViewBox right-click menus: View All, X axis, Y axis and Mouse Mode. Range fields edit the actual view; View All restores the complete measured wavelength range with zero extra X padding. Plot-family choices remain under Options → Views. The wafer-point selection menu remains available separately.

## Focused verification

Tests were written against the observable catalog/UI behavior and failed before implementation. New checks cover deduplication with repeated records/different IDs/missing angles, single statistics display, all grouping choices with selection/zoom retained, folded-branch deletion with byte-for-byte source-file preservation, deletion disabled with no selection, and native menu range editing in both main and floating plots. Existing tree expansion, checkbox participation and linked-selection tests remain included.

The focused command was:

```powershell
python run_tests.py tests.test_sme_spectra tests.test_spectra_viewer tests.test_spectra_map tests.test_performance_regressions.WorkbookPerformanceTests.test_dense_trend_screen_and_export_match_with_nan_gaps
```

It completed **72 tests in 20.949 s: 71 passed, one external-fixture access error**. The error is the existing long Windows path under the added `JC1913/SME_two_wafers_minimal_edit` fixture, in the independent real-file header check. This change does not modify the parser or fixture files.

Five targeted checks then passed on native Windows Qt (**2.113 s**): channel summary/footer, classification with participation/selection/zoom retention, selected folded-branch deletion with disk-file preservation, main/floating axis-menu range editing, and blank-area linked deselection.

A native light-theme preview loaded the original real subfolder `JC1913/EP01_20260822_AI04283.05`: **198 spectra, 2 channels**. With Lot classification and two checked spectra, the same source selection was retained, the idle footer was empty, and the menu action list was exactly the native four entries above. Preview: `qa_spectra_tree_controls_2026_11_02.png` in the repository root. Source files and user settings were not written.

## Broad regression

The existing five-module AutoWeighting exclusion list was retained. `run_tests.py` completed **1302 tests** (661 + 641), with **two failures and three errors**. All new catalog/tree/menu tests passed. Results and exact module lists are in [spectra-tree-controls-2026-11-02.json](spectra-tree-controls-2026-11-02.json).

The errors are the preceding FakeCorrelationWorkspace `raw_model` error, the preceding read-only pandas destination error, and the long-path real-file fixture error above. The two failures were KLA linked-view refresh timing and Correlation pending-render timing; a serial retry of both passed (**2 tests, 4.049 s**). The broad run is not an unfiltered clean-suite pass. Unrelated source modules remain unchanged by this work, and AutoWeighting was not modified or tested.
