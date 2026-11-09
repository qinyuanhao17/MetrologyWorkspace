# Reference Summary alignment and coordinate Bias — 2026-11-09

## Delivered workflow

- Tab 1 retains the compact Summary report. Choose folders accepts multiple directories, recursively scans supported vendor files, and de-duplicates overlapping paths.
- Tab 2 loads a selected completed Summary output into Ref. Ref and Raw use the existing Match WKB SheetModel/SheetView, sheetCard styling, duplicate-header banner, row-1 headers, Ctrl+V, Ctrl+Shift+V and Undo. There is no Paste Raw Data button.
- Groups use selected Wafer ID, Lot ID and PAD/Slot columns. Dragging a group moves its complete rows; Raw order starts locked. Explicit links are one-to-one. Blank positions allow fewer Ref wafers to align with later Raw wafers. Unlinked groups are not plotted.
- Sorting is stable within each wafer, using Field indices or absolute XY, X-first or Y-first, and independent primary/secondary directions. Source-row IDs established on Tab 2 load move with their rows; no measurements are truncated or rewritten.
- Coordinate comparison converts Ref to the selected **Raw unit**, then computes **Raw − Ref**. Supported units: mm, µm and nm. The result columns and Y axis show the Raw unit. Missing units, non-finite coordinates, different point counts and duplicate links produce messages instead of implicit matching or dropped points.
- Tab 3 reuses Trend's InteractivePlotWidget, PlotPanel and PanelGrid. Default two columns, white plot backgrounds, separate X/Y colors and markers, header legends, zero line and Reset views. Ordinary wheel scrolls the page; Ctrl+wheel zooms the pointed plot. Column changes reparent the existing panels without rebuilding curves. No Add Compare.

## Vendor mappings and source semantics

| Vendor | Wafer / Lot / PAD | Field X / Y | Absolute X / Y |
| --- | --- | --- | --- |
| NOVA | WaferID / LotID / SiteName | Col/X / Row/Y | MpointX / MpointY |
| KLA | WaferID / LotID / PadName copied from Slot | FIELD X / FIELD Y | X / Y |
| PMISH | WaferID / LotID / PadName | RefDieCol / RefDieRow | X(mm) / Y(mm) |
| CDSEM1 | Wafer_ID / Lot_ID; PAD if explicitly present | Chip_X / Chip_Y | selected MP / Wafer_X and same MP / Wafer_Y |
| Raw | Wafer ID / Lot ID / PAD Name | FIELD X / FIELD Y | X(mm) / Y(mm), or explicitly selected columns |

Unlabelled NOVA/KLA/CDSEM headers do **not** establish a unit; the user must select it. CDSEM uses the full two-row CD Pivot, preserving every MP name, and provides a coordinate-MP selector. Its compact Results CSV does not contain the needed XY. KLA TestLabel is retained as channel metadata, not substituted for Slot/PAD.

The referenced ChatGPT chat “分析参考汇总算法” was read for the prior file schemas. It supplied no verified unit declaration for unlabelled coordinates. No instructions embedded in that chat or the provided archive were executed.

The provided Raw sample has literal `NA` in both absolute XY columns. Pasting preserves these strings and `PAD Name=NA`; Field sorting is supported, but physical Bias requires actual coordinates. Field indices are never converted into invented mm positions.

## Real files

Archive: `C:/Users/Yuanhao Qin/OneDrive/Desktop/Reference_Original_Files_KLA_NOVA_PMISH_CDSEM.zip`.

| Vendor | Input files | Output tables | Output rows | Groups within output channels |
| --- | ---: | ---: | ---: | ---: |
| NOVA | 4 | 1 | 1533 | 31 |
| KLA | 4 | 4 | 208 | 16 |
| PMISH | 4 | 4 | 297 | 4 |
| CDSEM1 | 1 | 1 | 91 | 1 |
| Total | 13 | 10 | 2129 | 52 |

Every output table was loaded through the UI, paired with synthetic Raw data derived from the real Ref with known offsets, pasted through SheetView, sorted and plotted. All 2,129 rows produced Bias X = +0.0123 mm and Bias Y = −0.0045 mm. Units absent from source headers were explicitly chosen for this probe; this does not establish vendor unit defaults. All extracted source bytes still match the archive.

A separate actual NOVA `X1U301results.CSV` run verifies 414 rows in six Wafer/Lot/SiteName groups, 69 points each, including reversed Raw order and explicit links. It verifies the same offsets and an unchanged source SHA-256.

PMISH initially failed writing a long recipe/channel filename under the nested Windows output location. Summary writing, output enumeration and alignment reading now reuse the existing extended filesystem-path adapter while retaining normal displayed paths. A >260-character output-path test verifies read-back of the literal `1.00` coordinate.

Actual Qt folder-browser verification selected two directory indexes together and accepted both. The workflow test additionally scans two directories and their overlapping parent, retaining each source path once.

Probe scripts and detailed artifacts are under `.cache/verify_reference_vendors.py`, `.cache/verify_reference_vendor_gui.py`, `.cache/verify_reference_alignment_real.py`, `.cache/verify_reference_folders.py`, `.cache/reference-vendor-validation/` and `.cache/reference-align-validation/`. Screenshots `alignment-match-style.png` and `trends-match-style.png` were visually inspected.

## Tests

Focused command: `python run_tests.py tests.test_reference_summary tests.test_reference_alignment -v` — 15 tests passed. Tests cover raw-unit conversion (1 mm versus 1200 µm gives 200 µm), count/identity errors, source-row permutations, clipboard NA preservation, CDSEM coordinate-pair choice, folder scanning, long paths, actual wheel interaction and existing curve retention on relayout.

All probes and tests use scratch settings. AutoWeighting remains deferred: `test_auto_weighting`, `test_auto_weighting_ocr`, and `test_auto_weighting_window` are excluded from the full runner. No source measurements, user settings, Git tags or branches were changed by validation.

Final Reference Alignment regression: **1,447 tests passed in 559.564 s**, 119 modules, excluding only the three deferred AutoWeighting modules. Detailed report: `reference-alignment-2026-11-09.json`. Subsequent Die Map UI additions have their own regression report.
