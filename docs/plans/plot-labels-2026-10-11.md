# Plot label display controls

## Confirmed scope

- Groups → Plot labels provides PAD and Lot ID checkboxes for Trend, Wafer Map and Radius.
- These are wafer-caption controls, not identity-column/grouping/Data selection controls.
- Original table order uses the chosen wafer fields. Group names retain their original text; Group Show wafer uses the same display preferences for its wafer captions only.
- New preferences default to the previous full captions and are saved in Match WKB `match_ui.plot_labels`. Old WKB files remain compatible. Invalid settings are rejected before replacing the open document.
- Match titles use Parameter mapping's Parameter, not the mapped Raw column. All Trend primary Y labels match their titles. Explicit mixed-unit comparison warnings remain in both title and Y label; secondary-axis semantics remain unchanged.

## Implementation

Display preferences are separate from grouping state, source frames and numerical results.
Existing curves, interpolated surfaces, scatter observations and viewport ranges are retained when switching captions.
Map caption preferences are re-applied after a colorbar layout change, without recomputing interpolation.
The shared formatter removes only typed PAD/Lot metadata lines; primary identities, custom classification fields and run labels remain intact.

## Verification

- TDD evidence: source-column Match title failed against mapped Parameter `Depth`, then passed. Missing display controls failed, then passed. Colorbar rebuild initially restored hidden labels; its regression now passes.
- 11 plot-caption/style/Match-title focused tests passed; 8 final compatibility tests passed, retaining numerical and source-mapping assertions.
- Updated prior tests requiring a Raw-column title or empty Trend Y label to the user's new caption rule; the equal-valued source-remapping regression still verifies the newly chosen column and unchanged fit.
- Fixed an existing storage-test callback that attempted to confirm a startup dialog for an empty draft, which intentionally has no startup dialog. This was also logged in the prior 650-test run; production startup behavior is unchanged.
- All seven current desktop WKB files were copied to isolated native TEMP: title/label settings, unchanged source tables and Group state, Save/reopen passed.
- The 7,731-row NOVA testfilter1 copy passed Trend/Map/Radius checks: unchanged spans, curves, interpolation objects and radius observations. PNGs and light/dark menu screenshots were inspected.
- SHA256 of all original desktop WKB files and `config/settings.yaml` remained unchanged.
- Final `python run_tests.py`: **655 tests passed in 266.341 seconds**; numerical, participation, undo, atomic save/recovery and existing performance regressions remain enabled. The expected missing-file/lock-cleanup tests log their deliberate errors; no unexpected Qt callback exception remains.
- Final-source desktop acceptance also passed again; see `.cache/plot-labels-20261011/desktop-final.txt`. Formal settings SHA256 remained `45C9A69A560C7ABD9EC7BA42486FD71EB7E1D9620ACE039E44128F50748EBCE6`.

Executable BDD examples: `docs/features/plot_labels.feature`; tests: `tests/test_plot_labels.py`.
Logs and reproducible acceptance script: `.cache/plot-labels-20261011/`.
Native export/menu images: `C:/Users/Yuanhao Qin/AppData/Local/Temp/metrology-plot-labels-20261011/acceptance/`.

## Follow-up: explicit PAD/LOT prefixes

- Displayed wafer metadata now uses `PAD: ARRAY` and `LOT: AH06593.05` in Trend, Wafer Map, Radius and exported figures. Original table order and Group Show wafer are covered; Group names, source strings, identity keys, filters and calculations remain unchanged.
- Legacy `Lot:` scene captions are normalized to `LOT:` for display. The primary identity and custom/run lines remain untouched; existing display checkboxes and WKB persistence retain their behavior.
- Prefix assertions failed before the formatter changes, then passed in the original-order and Group Show wafer paths. The 19 focused caption/measurement/style tests passed, including export, independent identities and Save/reopen.
- The first full run found five obsolete no-prefix expectations. These were updated without removing identity, source immutability, no-overlap or performance checks. In the three-plot zoom test, the enlarged view is now 2,200 pixels: native font metrics require 416 pixels for the prefixed long PAD caption, while the old 1,900-pixel window left only 382–400 pixels per plot. The narrow/dense test and non-overlap assertions are unchanged. All five affected tests then passed together.
- Seven current desktop WKB isolated copies passed again, including the real 7,731-row fixture and inspected prefixed PNG exports. Original WKB and formal settings hashes remained unchanged; see `.cache/plot-labels-20261011/prefix-desktop.txt`. The user's current formal settings SHA256 is `BD2397E03AC2A2ED0F316AA5B45BEBB038CB38160662C8555058907C91CD43D9`; it was not restored to the older value above.
- Final-source `python run_tests.py`: **655 tests passed in 265.325 seconds**. Numerical, source identity, participation, viewport, undo, save/recovery and performance guards remain enabled; see `.cache/plot-labels-20261011/prefix-full-final.txt`.
