# Spectra Viewer interaction responsiveness

The changes address checkbox delays, fullscreen transitions, and internal boundary drags using the real JC1913 folder. AutoWeighting remains deferred. The source still contains 354 SME files: 198 readable files and 156 TSD envelopes. Each readable channel has 903 wavelength samples. All plot views are enabled for the comparison.

## Diagnosis

The preceding device-coordinate cache was fast only when plot geometry stayed unchanged. Checking a spectrum rebuilt the data items for the entire grid synchronously. Resizing/fullscreen invalidated curve caches and caused millions of thick line segments to be drawn on the GUI thread. The existing per-plot paint timer did not cover data preparation or window/layout repaints. A non-opaque splitter prevented continuous relayout during dragging, but releasing the handle still triggered expensive painting.

Actual checkbox clicks do not select and thicken the whole group: the recorded selection count is zero. The measured bottleneck is data/item preparation and full curve painting, not implicit selection.

## Implementation

- Reuse the existing detached curve renderer in `plotting/curve.py`, with an opt-in path for standalone solid curves. Two persistent worker processes paint complete finite-connected line segments into QImages using the same Qt pens and transforms as the native renderer. Widget/scene mutation, bounds, axes, selection and source arrays stay with the GUI owner. Small curves keep normal native painting.
- Prepare large curve changes one plot per event-loop turn. Coalesce resize repaint requests and update the grid one plot per turn rather than painting all charts in a single event. Dense native painting is suppressed before the first repaint, including synchronous repaint calls.
- Keep the previous correctly positioned image during a geometry change until the full-quality replacement arrives. Data/style revisions invalidate the previous image. Queued obsolete futures are cancelled, running jobs can only publish a matching revision/transform, and removal/closure cancels work. Floating plots receive the applied current source version.
- Retain original source samples, NaN gaps, finite bounds, tight X ranges, 1.8 px normal lines and 5 px highlights. No averaging, interpolation, peak selection or downsampling was added.
- Remove the redundant device-coordinate cache from the native curve. It also introduced fractional-DPI pixel differences when compared with direct painting. The worker cache matches direct native painting at the actual Windows 125% scale.

## Controlled Windows measurement

Both runs used the same Conda Python, light theme, native `windows` Qt platform, 125% system scale, 1800 × 1000 initial logical window, same folder and same operations. cProfile is enabled for each action in both runs. The before run loads the pre-change module snapshots from `.cache/spectra-interaction-baseline-20261101` without replacing the working files. JSON reports include platform, scale, synchronous submission, complete-update time, checked/selected counts and drag samples.

The table measures the **longest interval between 10 ms GUI heartbeat callbacks**, not total drawing time or a frame-rate guarantee:

| Interaction | Before | After |
| --- | ---: | ---: |
| Check the PAD containing all 198 readable spectra | 368 ms | 66 ms |
| Uncheck one of those spectra | 291 ms | 54 ms |
| Check that spectrum again | 351 ms | 51 ms |
| Enlarge the window | 1800 ms | 61 ms |
| Reduce the window size | 1312 ms | 28 ms |
| Enter fullscreen | 1730 ms | 54 ms |
| Leave fullscreen | 1303 ms | 37 ms |
| Drag the main plot boundary, including release | 387 ms | 35 ms |
| Drag a Mueller row boundary | 9 ms | 10 ms |

The final Mueller-row case was already fast; its difference is normal measurement variation. The large gains are in bulk checkbox changes and geometry-triggered full-grid redraws.

Complete updates remain distinct from input latency:

| Operation | Complete before | Complete after |
| --- | ---: | ---: |
| Check all via the actual PAD checkbox | 2.171 s | 1.270 s |
| Uncheck one | 1.928 s | 0.945 s |
| Enlarge the window | 3.618 s | 1.315 s |
| Enter fullscreen | 1.812 s | 1.407 s |
| Leave fullscreen | 2.243 s | 1.054 s |
| Drag the main plot boundary | 0.412 s | 0.380 s |

During those complete-update intervals the GUI can continue processing input; geometry changes retain an existing-image preview. These are local, instrumented measurements, not a claim of 60 FPS on every machine. The first worker use includes process startup.

Raw records:

- [Native Windows before](spectra-interaction-windows-before-2026-11-01.json)
- [Native Windows after and pixel comparison](spectra-interaction-windows-after-2026-11-01.json)
- [Offscreen before](spectra-interaction-before-2026-11-01.json) and [offscreen intermediate after](spectra-interaction-after-2026-11-01.json); the native comparison above is the final result.

Reproduce the current code from the repository root:

```powershell
$env:QT_QPA_PLATFORM = 'windows'
& 'C:\Users\Yuanhao Qin\.conda\envs\metrology-workspace\python.exe' scripts/benchmark_spectra_interaction.py 'C:\Users\Yuanhao Qin\OneDrive\Desktop\JC1913' docs/validation/spectra-interaction-windows-after-2026-11-01.json --verify-pixels
```

The probe isolates settings. Existing catalog, viewport and splitter probes also await background completion; input/submit timing is not presented as complete rendering time.

## Correctness and regression

On the actual Windows 125% scale, all 21 panels were compared against direct complete native Qt painting at full range, 520–540 nm and the 390–420 nm phase-discontinuity interval, with two spectra highlighted: **zero differing bytes in all 63 comparisons**, and zero background-cache failures. The source arrays and NaN gaps are retained. Separate dense-curve tests cover resize, narrow spikes, missing-value gaps, rapid check/uncheck replacement, floating-copy freshness and closing with queued work. A 200% scale resize/latest-data probe also passed.

`python run_tests.py tests.test_sme_spectra tests.test_spectra_viewer tests.test_spectra_map tests.test_performance_regressions.WorkbookPerformanceTests.test_dense_trend_screen_and_export_match_with_nan_gaps` — **65 passed**, final run 9.897 s. The shared dashed-curve screen/export test remains included because the renderer module is reused.

Broad regression uses `run_tests.py` with the same five-module AutoWeighting exclusion list as preceding turns. Exact module lists, logs and completion status are in [spectra-interaction-regression-2026-11-01.json](spectra-interaction-regression-2026-11-01.json). This is separate from the focused success above. Source SME files and user settings are not written by these probes.

The broad run completed **1295 tests** (654 + 641): **one failure and two errors**, all matching the preceding PAD/JC1913 runs. `FakeCorrelationWorkspace` still lacks `raw_model`; the literal-frame fixture still assigns into a read-only pandas destination. The Correlation pending-render timing assertion failed under the concurrent run and passed a serial retry (1 test, 0.370 s). No spectra tests failed. This is not a clean unfiltered full-suite pass, and unrelated code was left unchanged.

After broad regression, the current viewport probe passed all 63 full-data-versus-clipped pixel checks on the mixed 42-file/47-channel fixture. The catalog probe passed its 42 cached-versus-native panel comparisons on that fixture, and the splitter probe confirmed zero plot resize events during pointer movement before handle release. The final 200% dense resize/latest-data test run passed both tests (1.161 s).
