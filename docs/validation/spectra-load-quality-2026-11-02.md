# JC1913 Spectra loading, input latency and curve quality — 2026-11-02

## Fixture and reproduction

JC1913 contains 1,890 readable SME files, matching the supplied six-lot CSV after
the requested cleanup. The S/Mueller plots contain 90 Wafer/Lot/PAD/channel color
groups. Measurements use offscreen Qt at DPR 1, 2000×1100, all views enabled,
10 ms heartbeat samples and cProfile. The same action sequence and source data
were used before and after; these are scoped local measurements, not latency
guarantees for other machines. Production settings are isolated through
`run_tests.isolate_settings`.

```powershell
python scripts/benchmark_spectra_load_quality.py "C:\Users\Yuanhao Qin\OneDrive\Desktop\JC1913" docs/validation/spectra-load-quality-final-2026-11-02.json --verify-pixels
```

The first run is `spectra-load-quality-before-2026-11-02.json`; the final run is
`spectra-load-quality-final-2026-11-02.json`. Per-action profiles and screenshots
use the same filename prefix. An intermediate implementation is recorded
separately as `spectra-load-quality-after-2026-11-02.json`.

## Diagnosis and change

File reading takes about two seconds in the existing loading thread. The larger
delays were plotting: above 32 color groups, all curves on an axis shared one
multicolor raster. Removing one file or hiding one legend rebuilt and rasterized
all 1,890 files on every visible axis. Geometry concatenation, repeated full-array
bounds scans and preparing all metric groups before yielding also blocked input.
Antialiasing was disabled, producing hard stair-step edges.

The viewer now keeps up to 16 contiguous, stable color batches per axis. A changed
file or legend invalidates its batch, retaining the other batches, color order,
manual ranges and screen images. Source polylines are copied into preallocated
NaN-separated arrays; X fitting reuses finite paired bounds. Metric preparation
and legend visibility updates run in the existing per-chart event sequence.
Catalog grouping sorts branch keys instead of re-sorting every source twice.

Spectra curves now use antialiasing. Dense multicolor screen requests exceeding
32,000 vertices use Matplotlib's existing compiled path simplifier at a **0.25
physical pixel tolerance**, in detached render workers. NaN gaps are separate
subpaths; no measured value is averaged, smoothed or interpolated. Geometry is
regenerated at each viewport scale, and small/zoomed paths draw directly. Source
arrays, analysis, hit testing and native/export geometry retain the original
samples. Other tools keep the renderer's default zero simplification tolerance.

## Before/after measurements

"Complete" includes the final background image. "Input gap" is the largest gap
between 10 ms GUI heartbeat samples; it is distinct from background completion.

| Action | Before complete | Final complete | Before input gap | Final input gap |
| --- | ---: | ---: | ---: | ---: |
| Load folder | 1.998 s | 1.956 s | 195 ms | 123 ms |
| Check all | 9.177 s | 5.238 s | 516 ms | 242 ms |
| Uncheck one | 8.876 s | 1.139 s | 511 ms | 73 ms |
| Recheck one | 8.932 s | 1.242 s | 494 ms | 81 ms |
| Hide legend | 10.204 s | 0.656 s | 2,108 ms | 44 ms |
| Restore legend | 10.463 s | 0.776 s | 2,169 ms | 42 ms |
| Resize larger | 10.345 s | 6.855 s | 198 ms | 212 ms |
| Restore size | 10.235 s | 5.683 s | 197 ms | 242 ms |
| M01 View All | 0.904 s | 0.223 s | 55 ms | 42 ms |

Whole-window resize still takes several seconds for all final background images;
its worst sampled input gap did **not** improve in this run. Single-file and
legend interactions improve substantially. File I/O remains approximately two
seconds. Full collection drawing is faster while using antialiasing, but it is
not instantaneous. Source numeric array hashes remained unchanged.

## Shape and quality checks

The final probe compares M01, M23 and dual-axis Psi/Delta with original all-sample
native antialiased drawing, at full range and at 390–430 nm. At full range, mean
RGBA byte errors are 0.19–0.26 out of 255, and 0.37–0.50% of bytes differ by more
than 16. Isolated overlapping color fringes can differ more (maximum 95–152), so
this display approximation is **not a pixel-identical** claim. Full-range screen
and native screenshots were inspected. At zoom, the maximum byte error is 2/255
from transparent batch compositing; full local geometry is restored.

The executable narrow-peak/NaN-gap test checks both directions of the colored
curve footprint against native drawing within one physical pixel, bounds the
mean pixel error, verifies full local pixels on zoom and verifies unchanged
source arrays. The same tests pass at DPR 1.25. Existing exact native screen/export
checks remain for the renderer's unsimplified paths, including dense dashed
curves used by the other tools.

Focused Spectra/parser/map plus the shared dense dashed-curve screen/export
regression: **97 passed** in 19.738 s. Three actual curve/navigation/quality tests
also passed at DPR 1.25. The original 42-file parser fixture is copied from its
four named sample subdirectories into a temporary fixture so later user additions
to the parent directory cannot change its expected content.

The final repository-wide regression ran **1,327 tests** (685 + 642) with the five
previously deferred AutoWeighting-related modules excluded. All Spectra tests
passed. The whole repository is **not fully green**: the existing Correlation
pending-state assertion, FakeCorrelationWorkspace missing `raw_model`, and
pandas read-only literal-frame assignment remain (one failure, two errors).
Results, exclusions and log paths are in
`spectra-load-quality-final-regression-2026-11-02.json`. The first full run is
retained separately as `spectra-load-quality-regression-2026-11-02.json`; its
additional Spectra assertion exposed a 3/255 transparent antialias-compositing
rounding difference. The final regression bounds that rounding difference and
also checks the mean error, rather than demanding pixel identity between
separately composited and directly painted antialiased layers.

AutoWeighting remains deferred. No production settings or source SME files were
modified by these probes or code changes.
