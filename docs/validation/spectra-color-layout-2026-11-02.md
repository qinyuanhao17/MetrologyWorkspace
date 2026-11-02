# Color By and fully resizable Spectra layout

## Behavior

- Color By has Wafer and SME Name. Wafer identity is the complete Wafer ID/Lot/PAD tuple, plus the channel. SME Name identity is the source file path, plus the channel; equal basenames in different directories are not merged. Legends identify the active group, with full details in tooltips. Channel colors remain distinct in both modes. Existing colors survive check/uncheck, tree regrouping and switching back to a previous mode. Filtering, BSL, source arrays and manual axis ranges are preserved.
- 3σ remains an aggregate per wafer/channel, using the full wafer identity. It is not split into one-file samples by a color choice. Color By displays Wafer and is disabled in 3σ; Original/Residual restore the preceding choice.
- The tree/plots splitter initially allocates approximately 25% to the tree. All nine splitters (main, legend, summary/Mueller, summary stack, Mueller stack and four Mueller rows) permit adjacent panes to shrink or collapse. Another pane occupies the released space. Double-click restores defaults: main 1:3, summary/Mueller 1:2, others equal. Dragging previews a boundary and repaints after release. The prior 150×120 Mueller and 480 px tree constraints were intentionally removed to implement this request.

## Many-color rendering

One Qt curve per file/channel produced 12,474 base curve objects for 594 files and 21 metric axes. The resulting native repaints and per-curve handlers were slow. Above 32 color groups, each axis now uses one multicolor scene curve and one optional highlight curve. Logical file/channel groups, original samples, NaN gaps, source selection and data bounds remain available. Detached arrays and serialized pens are drawn in the existing background processes. Export/reference painting delegates to native per-color PlotCurveItems. Obsolete requests retain the existing version/cancellation guards.

Legend membership is updated incrementally: removing one file preserves all unaffected QListWidgetItems and their icons/fonts. Source color keys and natural sorting keys are cached for the catalog revision. The first ten colors retain Tableau Category10; further RGB colors vary hue, saturation and brightness, with uniqueness checks rather than a finite fixed-saturation hue cycle. This is a uniqueness claim, not a guarantee that hundreds of overlapping colors are perceptually distinguishable.

## Repeatable evidence

```powershell
python scripts/benchmark_spectra_color_layout.py "C:\Users\Yuanhao Qin\OneDrive\Desktop\JC1913" docs/validation/spectra-color-layout-final-2026-11-02.json
```

Both timing runs use 594 readable files, 2000×1100 offscreen Qt at DPR 1 and the same interaction sequence. S has 6 wafer/channel colors or 594 file/channel colors. The native many-color baseline is `spectra-color-layout-first-2026-11-02.json`; the final run is `spectra-color-layout-final-2026-11-02.json`. Focused tests ran concurrently in both cases, so these are scoped measurements rather than hardware-independent latency guarantees.

| Action | Native baseline complete | Final complete | Baseline maximum 10 ms heartbeat gap | Final gap |
| --- | ---: | ---: | ---: | ---: |
| Switch to SME Name | 28.937 s | 5.797 s | 1.739 s | 0.564 s |
| Uncheck one file | 29.369 s | 5.610 s | 11.057 s | 0.571 s |
| Recheck one file | 19.190 s | 5.667 s | 1.224 s | 0.399 s |

The final main tree fraction was approximately 0.25; all nine splitters collapsed and restored. The 594 RGB colors were distinct and unchanged after uncheck/recheck. The first batching-only run (`spectra-color-layout-after-2026-11-02.json`) is retained separately; final timings also include incremental legend/key caching.

For pixel/source verification:

```powershell
$env:QT_SCALE_FACTOR = '1.25'
python scripts/benchmark_spectra_color_layout.py "C:\Users\Yuanhao Qin\OneDrive\Desktop\JC1913" docs/validation/spectra-color-layout-pixels-2026-11-02.json --limit 40 --verify-pixels
```

At **DPR 1.25**, 21 panels at full range, 520–540 nm and 390–420 nm matched native per-color drawing exactly: **63 comparisons, zero differing bytes**. Source numeric array hashes were unchanged. Both colors and selected 5 px overlays were exercised. The probe also checks all nine splitter restores. Wafer and individual-file screenshots were inspected (`qa_spectra_color_wafer.png`, `qa_spectra_color_sme.png`).

## Tests and scope

Focused Spectra/parser/map plus the shared dense dashed-curve screen/export check: **93 passed**, 33.426 s. This includes Color By state/color/legend retention, full wafer identity, 3σ choice restoration, actual main-bar dragging to collapse, double-click restoration of all nine splitters, and multicolor native pixel equivalence with NaN gaps at full/zoomed ranges.

The complete isolated `run_tests.py` regression, excluding the user-deferred AutoWeighting-related modules, ran **1,323 tests** (681 + 642). It has one failure and two errors already present in the preceding baseline: Correlation pagination's pending-state assertion, FakeCorrelationWorkspace missing raw_model, and pandas read-only literal-frame assignment. No Spectra failures occurred. Details are in `spectra-color-layout-regression-2026-11-02.json`. Unrelated working-tree changes and `config/settings.yaml` were preserved.
