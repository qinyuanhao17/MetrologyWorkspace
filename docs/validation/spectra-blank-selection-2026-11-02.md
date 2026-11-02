# Clear spectrum selection from blank chart areas

Blank left-clicks in wafer maps, main Mueller/spectrum plots, floating plots and the surrounding chart/window margins now clear the linked tree selection, thick spectrum highlights and wafer-point rings. Checked participation and plot ranges remain unchanged.

The map previously handled scatter-point clicks only. It now handles unaccepted blank scene clicks, while accepted point clicks retain normal and Ctrl/Shift selection behavior. Main/map window background clicks use normal Qt event propagation; scroll-area/plot events are excluded from that background handler so point/curve clicks do not first erase an existing multi-selection. The existing main/floating plot scene hit-testing remains unchanged.

`SpectraViewerTreeTests.test_blank_map_and_main_plot_background_clear_the_linked_selection` failed before the change for map interiors, map margins and main-window margins. It now passes with actual mouse clicks across five areas, checks linked selection and rings, preserves checked spectra/ranges, and confirms a point click still selects. Existing point/curve Ctrl-selection tests also pass.

Four targeted selection tests passed on the native Windows Qt platform (2.120 s):

- `test_blank_map_and_main_plot_background_clear_the_linked_selection`
- `test_curve_and_blank_clicks_sync_selection_with_map_and_floating_plot`
- `test_map_ctrl_selection_across_wafers_and_context_check_actions_sync_tree`
- `test_ctrl_curve_clicks_add_and_remove_spectra_from_the_selection`

The focused SME/viewer/map/shared-renderer run completed 66 tests in 17.100 s: 65 passed, with one external-fixture error. `RealJC1913Tests.test_every_real_file_is_readable_or_identified_as_encrypted` encountered an added sample under `JC1913/synthetic_two_wafers_from_unencrypted_SE3` with a 282-character path. Read-only diagnosis confirmed that normal `Path.open` fails while Windows extended-path access can read its header. The parser and external source files were left unchanged by this click-selection fix.

Broad regression uses `run_tests.py` and the preceding five-module AutoWeighting exclusion list. Exact modules, logs and results are recorded in [spectra-blank-selection-2026-11-02.json](spectra-blank-selection-2026-11-02.json). The probes isolate user settings. AutoWeighting remains deferred.

Broad regression completed **1296 tests** (655 + 641), with **one failure and three errors**. The new click-selection test and all other map/viewer tests passed. The remaining results are the long-path fixture error described above, the preceding `FakeCorrelationWorkspace.raw_model` error, the preceding read-only pandas assignment error, and the preceding Correlation pending-render timing assertion. This is not a clean full-suite pass; unrelated source modules and fixture files were left unchanged.
