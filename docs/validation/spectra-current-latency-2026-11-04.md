# Current Spectra Viewer latency — 2026-11-04

Current release source: `v5.1.0`, commit `c630b4936703f137307b0fa8a1ecc142d0b7105b`.
Fixture: JC1913/matching-analysis.mwkb, **1,890 spectra / 90 wafers / one physical channel**,
409,559,040 bytes (409.56 MB decimal). Native Windows Qt at 125% display scale;
initial Spectra window 1500 x 900 logical pixels. Each repeat starts a fresh GUI
process and fresh raster workers. Three serial repeats; medians below. OS file
cache is not flushed; application/Match window creation is excluded. Spectra
child opening includes its own lazy initialization, decoding and first drawing.

This is source-runtime measurement in the metrology-workspace Conda environment,
not a packaged-executable cold-start measurement. All writes and normal .bak
creation use owned byte-identical scratch copies of the original Workbook.
All three source SHA-256 comparisons were unchanged; no warnings occurred.
Generated large copies were removed after timing. Production settings were isolated.

## Timing definitions

- **Action return**: elapsed wall time until the state/file API returns. Large
  file operations may pump Qt via their progress dialog during this interval.
- **Complete**: elapsed time until the native UI/render queue first becomes
  stably idle. A 150 ms confirmation interval is excluded from the result.
- **GUI gap**: longest gap in a 10 ms GUI timer during the operation. This is
  an approximate event-loop stall measure including OS scheduling/paint work,
  not a guarantee of physical mouse-to-screen latency.

Checkbox, channel and divider operations use the same existing state APIs as
UI callbacks; menu navigation and user cursor travel are excluded. Divider
figures measure a committed size change and new rendering, not a whole human drag.
Interactive tests use all 1,890 checks; WKB Selection copying then restores 1,869
checks for saves and the paths-mode comparison. All 1,890 sources remain stored.

## Results (milliseconds)

| Operation | Action return median | Complete median | Complete min–max | GUI gap median |
| --- | ---: | ---: | ---: | ---: |
| Open embedded WKB (Match window) | 2286.6 | 2328.5 | 2317.4–2344.6 | 543.3 |
| Open embedded Spectra child to first complete plot | 3670.0 | 7807.2 | 7768.4–7840.9 | 1539.0 |
| Uncheck one spectrum | 24.0 | 857.6 | 852.0–865.8 | 82.7 |
| Recheck one spectrum | 26.9 | 833.7 | 820.8–840.7 | 53.0 |
| Uncheck one 21-spectrum wafer | 23.9 | 825.3 | 817.0–830.5 | 70.8 |
| Recheck one 21-spectrum wafer | 26.5 | 831.2 | 814.9–838.4 | 55.9 |
| Hide physical channel across all wafers | 28.2 | 122.1 | 118.4–131.9 | 28.2 |
| Show physical channel across all wafers | 27.3 | 287.7 | 287.2–293.9 | 27.3 |
| Hide one wafer/channel legend entry | 22.4 | 527.8 | 519.4–530.4 | 52.0 |
| Show one wafer/channel legend entry | 24.9 | 556.2 | 555.1–557.2 | 43.7 |
| Select/highlight one spectrum | 20.6 | 158.4 | 133.7–165.1 | 20.6 |
| Clear selection | 11.2 | 68.8 | 63.5–83.6 | 40.1 |
| Resize to 1300 x 800 | 23.2 | 2580.7 | 2573.9–2621.1 | 202.1 |
| Maximize | 5.9 | 6818.7 | 6801.9–6900.7 | 315.4 |
| Restore normal window | 5.8 | 2569.9 | 2559.1–2591.3 | 320.4 |
| Move tree/plot divider | 36.3 | 2551.0 | 2524.6–2612.7 | 99.9 |
| Move NCS/Mueller divider | 26.3 | 2538.2 | 2480.0–2568.1 | 84.9 |
| Uncheck all spectra | 35.7 | 42.4 | 41.3–44.9 | 35.8 |
| Check all spectra | 34.4 | 3094.3 | 2914.1–3281.9 | 257.0 |
| Open Die Map first page (12 wafers) | 19.5 | 561.5 | 509.2–576.1 | 76.4 |
| Select spectrum with Die Map visible | 21.4 | 148.3 | 145.3–148.8 | 35.3 |
| Uncheck one spectrum with Die Map visible | 23.9 | 826.5 | 810.7–829.4 | 69.9 |
| Check one spectrum with Die Map visible | 28.8 | 863.1 | 856.5–869.7 | 58.2 |
| Open Spectra Info | 78.9 | 189.0 | 185.3–198.2 | 79.0 |
| Open Data selection | 85.9 | 177.8 | 140.7–180.8 | 85.9 |
| Copy WKB Selection (1890 matched, 1869 checked) | 107.0 | 825.6 | 823.6–872.6 | 107.0 |
| Overwrite embedded WKB, including existing-file checks/backup | 4033.3 | 4039.2 | 4024.6–4179.8 | 322.6 |
| Save embedded WKB As to fresh target | 1127.1 | 1132.6 | 1132.4–1179.1 | 79.5 |
| Save embedded standalone .spec | 1005.3 | 1087.8 | 1075.4–1211.6 | 55.8 |
| Convert existing embedded WKB to paths | 3098.2 | 3104.0 | 3103.6–3181.0 | 324.3 |
| Overwrite paths-only WKB | 182.9 | 188.7 | 178.6–197.1 | 182.9 |
| Save paths-only standalone .spec | 34.7 | 40.6 | 39.7–48.1 | 34.8 |
| Open paths-only WKB (Match window) | 261.9 | 298.0 | 296.5–301.5 | 261.9 |
| Read referenced SMEs and complete paths-only Spectra child | 4638.1 | 8279.7 | 8268.2–8378.5 | 1711.7 |

## File-size and end-to-end context

| Saved document | Bytes |
| --- | ---: |
| embedded_wkb | 409,554,944 |
| paths_wkb | 2,863,104 |
| embedded_spec | 407,891,968 |
| paths_spec | 1,200,128 |

Opening embedded WKB then opening its Spectra child to a fully drawn view:
**10.152 s** median.
Paths-only WKB plus referenced SME reading and drawing: **8.581 s** median.
Human delay between those two actions is excluded. A fast paths-only container
open is not the same as loading and plotting its 1,890 referenced SME files.

The largest measured completion waits remain initial Spectra restoration,
maximized-size image generation and durable overwrite of an embedded WKB.
State changes are substantially shorter than background drawing. Initial
Spectra opening still has roughly 1.5–1.7 s GUI heartbeat gaps; embedded WKB
opening has approximately 0.54 s and embedded overwrite approximately 0.32 s.
These are current observations, not a claim that all responsiveness targets are met.

Reproducible probe: `.cache/measure_current_spectra_latency.py --trial N`.
Raw trials and action metrics are in the adjacent JSON. No application code
was changed and no release was republished for this measurement.
