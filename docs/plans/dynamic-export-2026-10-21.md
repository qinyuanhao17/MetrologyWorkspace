# Dynamic editor, comparisons and report layout

## Scope

- Float/dock the same Measurement table editor in Dynamic. Its native Tool
  window belongs only to Dynamic, without the global always-on-top flag used by
  the Workbook Raw editor. Editing and Undo are not copied.
- Single Die and All Dies comparisons use one independent Y axis per parameter.
  All dies of that parameter share its axis. All Dies comparison curves use a
  dashed stroke to distinguish them from the primary parameter's die curves.
- Apply the supplied horizontal-table example to **every** Match sheet:
  Original, Wafer, Group and each named group. Charts start below the tables.
  Literal measurements remain in Original's right-hand source area, and the
  other Match views keep links to the original source rows.
- Export saved Dynamic and successful Map/Radius choices even when their child
  windows are closed. Reconstruct detached export-only windows through their
  ordinary restore/draw pipeline, without registering them or accepting drafts.
- Native Dynamic Excel charts link through editable pivot cells to literal
  inputs. Comparison series have distinct support ranges and secondary axes.
  Excel has one secondary Y axis per ordinary chart; multiple compared
  parameters therefore produce adjacent primary/comparison chart pairs.
- Native Dynamic axes automatically refit edited inputs. Matplotlib exports
  keep editable data/formulas and static PNG charts, as that command promises.
- FM/FullMap retains Map and Radius PNGs in both export modes. Each is resized
  proportionally to at most 7.5 cm high and 18 cm wide. PNG bytes remain intact.

No source files, fitted Cards, interpolation, regression rules or measurement
strings are changed by the report layout. No package, Git commit, tag or remote
publication is part of this change.

## Feedback loops

The initial `tests.test_dynamic_compare_export` run was red at the real UI/export
seams: no floating controller, no secondary Y views in either mode, and only one
exported Dynamic trend curve instead of the four selected die/parameter curves.

The saved-closed-Dynamic scenario was separately red: the Workbook report had
zero Dynamic reports after save/reopen with the child closed. Source-fixture QA
also exposed legacy selection-only state being replaced by a new empty window's
grouping and map-box defaults. The export-only reconstruction now omits those
unsaved defaults and replays the actual saved draw choices.

Executable coverage is in `tests/test_dynamic_compare_export.py`,
`tests/test_export_template_layout.py`, `tests/test_requested_plot_controls.py`,
`tests/test_excel_export.py` and `tests/test_excel_report_layout.py`. Existing
position assertions were updated to the newly requested layout while retaining
formula, literal-string, row-provenance, style, image and atomic-save assertions.

## Verification

All Qt checks use `.venv/Scripts/python.exe -X utf8 run_tests.py` so application
settings, recent files and recovery are isolated from the real configuration.

- Final focused run: **46 tests passed in 25.083 s**, covering Dynamic, both
  comparison modes, saved reconstruction, all Match layouts, FM image limits,
  editable ranges, axes, persistence and existing requested controls.
- Read-only source-fixture QA used the user's `matching-analysis.wkb.bak`:
  native and Matplotlib exports completed; both stages' Dynamic sheets were
  present, and each FM sheet contained five Map and five Radius PNGs. The source
  SHA-256 was identical before and after. Final native-only repeat: 2 tests,
  48.959 s, passed.
- A separate **hidden Excel instance** opened only the generated QA workbook.
  Original input edits updated linked Match cells. Dynamic input edits updated
  the pivot and chart-bound 3 Sigma cell after a controlled source edit,
  with automatic Y bounds containing the new value. Ten FM
  pictures met the physical size caps. Test edits were discarded on close.
- Actual Excel chart PNGs and offscreen Dynamic UI/Matplotlib comparison views
  were inspected. Artifact Tool could not import this reference's chart drawing
  shapes, so it was not used to rewrite or flatten the user's template.
- First full run: **947 tests in 761.239 s**, with 5 failure records and no
  errors. Four records were stale layout/size assertions (including both native
  and Matplotlib subcases of one test). Those now locate the right-hand literal
  inputs and assert the requested 7.5 cm image height instead of the old 11 cm.
  The fifth was the pre-existing grouped Correlation restore time gate:
  **2.175898599991342 s**, required **<2.0 s**. Its source/fit/plot assertions
  preceding that gate passed. No timing threshold was changed.
- Updated export acceptance run: **12 tests in 9.333 s**, passed.
- Final full-suite result: **947 tests in 737.361 s: 945 passed, 2 timing-only
  failures, 0 errors**. No functional or data assertion failed. Log:
  `.cache/dynamic-export/full-tests-final.log`.
  - `test_saved_correlation_restores_complete_grouped_plots_promptly`:
    **2.1899781999818515 s**, required **<2.0 s**.
  - `test_wafer_window_opens_with_current_cards_and_uses_new_coefficients_after_edit`:
    **0.40488299998105504 s**, required **<0.4 s**. Current Cards, the exact input
    values, exclusions and updated coefficients passed before the time gate.
- Final UI smoke: **1 test in 1.489 s**, passed. Actual double-click events on
  the Measurement panel and floating dialog detached and docked the editor;
  owner and non-global-topmost flags were checked. Refreshed light-theme
  Single Die / All Dies and Matplotlib screenshots include the final line styles.
- Real settings SHA-256 before and after the final full run was unchanged:
  `F6098CB0D384370F5E743FFA12255929B5B25349A7724C1191D7678CEAEFDEFA`.
- `git diff --check` passed. User changes in `AGENTS.md`, `.vscode/settings.json`
  and `docs/todos/` were preserved and not staged. No commit, tag, packaging or
  GitHub operation was performed.

QA scripts and images live only in the ignored `.cache/dynamic-export/` folder.
