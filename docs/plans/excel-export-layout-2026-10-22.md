# Excel and Matplotlib export layout

## Requested behavior

- Match sheets put editable Reference inputs in the parameter tables, without a second Reference block beside Raw Data. Wafer/Group views link to those inputs by original source row, including missing/excluded observations.
- FM keeps its picture strip, then the prepared Wafer/Die Seq/parameter report, a gutter, and the literal source data.
- Excel retains worksheet-bound native editable charts and source-range selection outlines. Matplotlib redraws the same measurement values; it does not capture the screen widgets.
- Match headings, fitted equation/R² placement, PMISH/Reference legend labels and colors, circular markers, and Die Seq labels follow WKB semantics. Export dimensions, font family, and sizes remain unchanged.

## Verification

`tests.test_export_source_layout` first reproduced three failures (duplicate Ref, reversed FM report/source order, in-plot Matplotlib fit text), then passed after the change. Existing export tests were updated only where the requested template replaced their previous duplicate-Ref expectations; row mapping and missing-pair assertions remain.

Isolated command:

```
.venv\Scripts\python.exe -X utf8 run_tests.py tests.test_export_source_layout tests.test_export_template_layout tests.test_excel_export tests.test_excel_report_layout tests.test_source_plot_presentation -v
```

Result: **61 tests passed, 119.423 seconds**. Full-suite execution and publishing remain deferred at the user's request.

Private QA copies under `.cache/export-style-20261022/` were generated from the supplied export, with its source hash unchanged. A separate hidden Excel instance opened only the owned QA workbooks. Editing a parameter-table Reference updated Wafer values; editing Raw updated the Match numeric range; editing FM source updated its prepared report. Native charts retain local range-based SERIES formulas. Native and Matplotlib Match/Trend/Bias/FM images were visually inspected; dimensions and typography were retained. Two additional isolated QA tests passed in 8.016 seconds.

## UC investigation remains qualified

The supplied UC chart (`FullMap (WO Card)`, `xl/charts/chart34.xml`) has one series, identical line/marker data, and explicit `smooth=false`. It rendered with coincident points and lines after recalculation in the independent Excel instance. A separate-color native rendering of the new 83-point UC chart verified every marker against the actual connecting line (maximum 4 pixels to uncovered line pixels, within the 5-pixel marker tolerance). This does **not** establish the original screenshot's root cause. No measurement, regression, resampling, or interpolation change was made to mask it.

Real settings SHA-256 before and after checks: `B7453C2A2A8A36DF57341CD0DCF804CD11ED6D6F41EF14B29DA0FCBB5197238D`. No source workbook or application settings were overwritten.

## Follow-up: WKB hierarchy and native trendlines

The user's subsequent screenshots replaced the previous picture-strip and fitted-line requirements:

- FM visuals now start together on row 1, ordered **FM Trend / Wafer Map / Radius**. The existing whole-grid Copy PNG bytes are retained. Both PNG types are scaled to four times their previous physical dimensions, without stretching (caps 30 cm high / 72 cm wide instead of 7.5 / 18). Prepared FM data remains before the literal source table, to the right of the visuals.
- Native Excel Match charts now have one measurement series with an actual linear Excel trendline and dynamic equation/R². There are no synthetic Fit series or visible Fit line endpoints. Excel independently refits edited worksheet values; the WKB Card and derived PMISH/Card/Bias calculations still use the software coefficients. Matplotlib retains the software fit and renders it itself.
- All Dynamic parameter and summary charts are 18 cm wide in both renderers; height and font sizes are unchanged.
- Wafer and Group captions occupy distinct footer strips below Die Seq, with full-height solid boundaries. Every real boundary is retained even when caption text is sparse. Group plots include the Wafer layer for groups configured to show it in WKB. Internal Wafer dividers are fine gray, Group dividers heavier black. Matplotlib dividers are behind the data. Native Excel uses chart-owned DrawingML overlays; it does not rasterize the editable data series.
- Single-parameter FM Trends use the same Wafer footer and divider representation.

The four initial acceptance tests failed before implementation. Final related suite: **82 passed / 122.929 s**; after the last native label number-format adjustment, **20 focused checks passed / 18.811 s**. Owned integration QA generated both renderer exports from synthetic data, including real whole-grid Map and Radius PNGs (**1 passed / 14.508 s**). Independent hidden Excel verified actual column order/top alignment, image heights, local editable series, a native equation changing from `y = 2x + 1` after a Reference edit, correct sparse-pair fitting despite missing X/Y and an unpaired outlier, and 18 cm Dynamic charts. Native and Matplotlib Match, Wafer, Group, FM and Dynamic pictures were visually inspected. Settings hash stayed unchanged.

A suspected first-export PG cache issue was investigated but **not confirmed**: the `artists` property creates the export cache lazily. An initially invalid QA map had duplicate coordinates, correctly rejected by the existing renderer. A valid first-export regression passes without changing this path; no workaround weakened the coordinate validation.

Full suite, packaging and GitHub publication remain deferred. Existing unrelated user work was preserved.

## Latest follow-up: opening layout, selection and label demand

This section supersedes the earlier row-one/below-data picture placement, whole-grid Map scaling and fixed-width assumptions.

- Prepared Match tables remain horizontal from A1; all Match variants open their first chart row at A5, overlaying the editable data. The prepared FM Wafer / Die Seq / mapped-parameter report starts at A1; its literal source table remains to the right. FM Trend / Map / Radius start together on row five. RSQ also opens its charts at A5.
- Native category tick marks use the same interval as their visible labels, including RSQ. Neither renderer resamples observations. Original keeps original source rows; Group/Wafer views preserve their explicit projections and references back to Original.
- Trend width now measures visible Die Seq and footer text. Crowded neighboring captions can increase physical width; sparse captions no longer allocate one caption-width per measurement. Observation limits remain tight. Footer labels share non-overlapping placement, with leaders for displaced text and white backgrounds over structural lines. Dense Wafer footer short marks are sparse; the true internal Wafer dividers and Group boundaries are retained.
- Match uses 5 pt native markers; Trend/Bias use 4 pt native markers and 1.8 pt strokes. Matplotlib retains the corresponding original 25-area scatter marks / 4 pt line markers / 1.8 pt strokes. The user's last two screenshots superseded the intermediate density-based thinning experiment; large reports are not thinned automatically.
- Native Match equations are still genuine, editable Excel trendline labels. Their initial position measures the General-format text extent because Excel auto-sizes the text box instead of honoring its requested width. Titles and label paragraphs are centered. A separate caption-ID regression fixes duplicate DrawingML object IDs between footer levels.
- Each Wafer Map grid row is 8 cm high, keeping the whole Copy PNG grid intact and its aspect ratio. Captured row/column metadata travels with the detached report. This replaces the old whole-image four-times rule for Map only; Radius retains its existing scale. No Map is individually cropped or redrawn.
- Both GUI export routes paint the preparation dialog before reading GUI-backed snapshots; only detached data enters the existing writer thread/process. Cancel/failure preserves an existing destination. This fixes feedback timing, not a claim that total export computation became faster.
- The GUI then offers checkboxes for the actual output sheet names, defaulting to all. Empty acceptance is disabled; cancellation writes nothing. Unselected outputs are removed. Any unselected sheets transitively needed by selected formulas, chart ranges or captions are retained hidden, without their charts/images. The selected output becomes active. Programmatic exports still default to all sheets.
- Recent WKB capacity is 20, including the persistence-failure fallback. When either Head or Mark is enabled, the order chooser offers only Group and Original row order. A grouped legacy `wafers` setting migrates to `groups`; ungrouped Wafer order and original source rows remain available and unchanged.

### Verification for this follow-up

The opening-progress, prepared A1 report, recent-file capacity, legacy grouped order, dense point styling and duplicate caption IDs each had failing regressions before their corresponding fixes. Sheet-selection tests cover all/individual/empty/cancel choices, apostrophes in dependency names, hidden Original/Card sources and unchanged literal source strings. The existing parallel-versus-serial Matplotlib check retains byte-for-byte pixel equality using the new adaptive layout in both paths; it is not replaced by a weaker image assertion.

Owned QA lives under `.cache/export-opening-20261022/` and `.cache/export-selection-20261022/`. The supplied NOVA WKB was read only. Excel independently checked every one of the 7,731 original paired points for each of its three parameters. Subsequent selected-sheet QA confirmed one visible Group sheet with hidden editable dependencies, a native trendline refitting after a hidden Reference edit, the requested 5/4 pt markers and 1.8 pt line weights, and an adaptive real-case Group Trend width of 41.285 cm. Independent hidden Excel instances opened only owned QA files, and confirmed 8 cm Map row units and A5 alignment in both output modes. Source and settings files were not overwritten.

Full-suite execution, packaging and publication are still intentionally deferred.

Latest isolated regression result: **114 passed / 202.516 s** (`.cache/export-selection-verified.log`). After the final footer paint-order change, **28 focused checks passed / 35.631 s**; after adding owner-close cancellation for the sheet chooser, **25 focused checks passed / 18.745 s**. These are overlapping targeted runs, not a full-suite result. The large serial/parallel Matplotlib comparison still checks exact RGBA pixel equality.

Final owned NOVA/selection QA passed in **38.779 s**, followed by another hidden-Excel verification of actual marker/line properties, formula refitting, adaptive width, Map row dimensions and alignment. The chooser was rendered using the application's normal font bootstrap, and the final native/Mpl pictures were visually inspected. Real settings SHA-256 stayed `16FC6427B743DB5AD053389AA35B00F37413A4CA8821C4D98075E9756F9B7CA6`; the earlier hashes above describe historical verification phases only. No original workbook, user setting, branch, tag or Release was modified by this follow-up.
