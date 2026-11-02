# PAD mouse expansion

The PAD node stored its spectrum collection but had no child rows until expansion. Qt's default child-indicator policy hid the expansion arrow on that childless node, so a mouse click could not start lazy loading. Earlier tests called `setExpanded(True)` directly and missed this user-visible failure.

The fix explicitly shows the expansion indicator for PAD nodes. Spectrum rows are still created only when opened. Wafer, Lot, data identity, checkbox participation, plotting, and AutoWeighting behavior are unchanged.

`SpectraViewerTreeTests.test_pad_arrow_opens_lazy_spectra_with_a_mouse_click` failed before the fix and passed after it. The test uses actual mouse clicks to open, close, and reopen the PAD, checks numeric Die order, and verifies that reopening does not create extra rows. The existing lazy-creation test also passes. All 61 focused SME/viewer/map tests passed in 9.314 s via `run_tests.py`.

A separate isolated-settings probe loaded the real JC1913 folder with the light theme and used a mouse click to open the screenshot's `AI04283.00-25 / AI04283.05 / 2026-8-21-10-53-55` PAD successfully. Source files were read only. The screenshot is `qa_spectra_pad_expansion.png` in the repository root.

Broad regression results and the existing five-module AutoWeighting exclusion list are recorded in [spectra-pad-expansion-2026-11-01.json](spectra-pad-expansion-2026-11-01.json). Tests isolate persisted settings; `config/settings.yaml` remains unchanged.

The two shards completed 1292 tests (651 + 641). They reproduced the preceding run's two non-spectra errors (`FakeCorrelationWorkspace.raw_model`, read-only pandas assignment) and one Correlation pending-render timing failure. No spectra tests failed. This is not a clean broad-regression pass; unrelated code was left unchanged. AutoWeighting was not run.
