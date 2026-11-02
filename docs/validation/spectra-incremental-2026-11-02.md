# Spectra check and legend incremental updates

The previous path discarded every base/highlight curve in `set_curves`, rebuilt them and called `_auto_range_all` on each check or legend change. This also discarded raster caches, scheduled background work for unrelated wafers and reset manual axes.

The panel now compares groups by wafer/channel, color and the identity/layout of their immutable source arrays. Only changed groups are replaced; unchanged curve objects, full source arrays and raster caches remain. Selected overlays use the same comparison. Legend state is separate from the checked-data signature: toggling a legend updates visibility of the existing curve and its sibling raster, and cancels hidden rendering work. It does not prepare curve data again. Hidden groups are excluded from picking, automatic bounds and exports. Floating panels follow the same rules. Stable z ordering prevents an updated wafer from unexpectedly covering another wafer.

Manual axes remain unchanged. Axes that still follow data update from visible data; automatic X remains tight. Full source samples and NaN separators are retained; there is no resampling or averaging.

## Repeatable measurements

Run from the repository with the metrology-workspace Python environment:

```powershell
python scripts/benchmark_spectra_incremental.py "C:\Users\Yuanhao Qin\OneDrive\Desktop\JC1913" docs/validation/spectra-incremental-after-2026-11-02.json
```

Fixture: 594 readable files, three wafer IDs (original 198 plus 30 nm red/blue shifts), six wafer/channel groups. Qt offscreen, device pixel ratio 1, 1800×1000 window. Each action repeats three times after initial rendering. Timings include GUI submission and completion of background rendering; the script also records 10 ms heartbeat gaps and curve creation counts. Both runs start with manually chosen axes. The old code resets those axes, while the new code preserves them, so completion times include that intentional behavior difference.

| Action | Before median | After median | Before factory calls | After factory calls |
| --- | ---: | ---: | ---: | ---: |
| Uncheck one spectrum | 4.986 s | 0.521 s | 126 | 21 |
| Recheck one spectrum | 4.926 s | 0.563 s | 126 | 42 |
| Hide one legend group | 4.150 s | 0.078 s | 105 | 0 |
| Restore that legend group | 5.094 s | 0.123 s | 126 | 0 |

The old factory handled base curves only; the new shared factory also creates selected overlays. Post-change recheck creates 21 base curves plus 21 selected overlays; the other five base groups per plot are retained. The counts therefore describe factory calls, not a total-curves comparison across versions. All 12 post-change actions preserved the manual axes. Raw results are in `spectra-incremental-before-2026-11-02.json` and `spectra-incremental-after-2026-11-02.json`. This demonstrates the scoped improvement, not a guarantee for arbitrary dataset sizes or native display configurations.

## Correctness checks

- `python run_tests.py tests.test_spectra_viewer tests.test_spectra_map tests.test_sme_spectra tests.test_performance_regressions.WorkbookPerformanceTests.test_dense_trend_screen_and_export_match_with_nan_gaps tests.test_performance_regressions.WorkbookPerformanceTests.test_grouped_trend_wheel_preserves_full_curves_promptly -v`: **77 passed**, 30.713 s (including the existing shared dashed-curve screen/export path).
- Public check workflow preserves unrelated wafer curve identities and both manual axes in main and floating panels.
- Dense legend toggles reuse original curve objects, emit no data-change signals, retain manual axes and match native rendering while hidden; uncheck/recheck restores identical pixels and overlap order.
- Enabled automatic axes follow visible data, including tight X bounds.
- Real 198-file JC1913 original batch: 21 panels at full range, 520–540 nm and 390–420 nm match native drawing exactly (63 image comparisons, zero differing bytes, zero raster failures). Command: `python scripts/benchmark_spectra_interaction.py "C:\Users\Yuanhao Qin\OneDrive\Desktop\JC1913\EP01_20260822_AI04283.05" docs/validation/spectra-incremental-pixels-2026-11-02.json --verify-pixels`.
- Regression results are recorded separately in `spectra-incremental-regression-2026-11-02.json`. AutoWeighting and the previously identified modules that exercise it remain excluded at the user's request.

Broad regression ran **1,306 tests** in two isolated `run_tests.py` shards (665 + 641). It is **not green**: two errors and two failures match the preceding wafer-color run. They concern `FakeCorrelationWorkspace.raw_model`, a read-only pandas literal frame, Correlation pagination's pending flag and the separate Matching Wafer Map opening threshold (0.408 s versus 0.400 s). No Spectra tests failed. A serial retry passed the pagination test; the Matching Wafer Map timing still failed at 0.520 s. These unrelated areas were not changed for this request. `git diff --check` and syntax parsing passed; `config/settings.yaml` remains unmodified.
