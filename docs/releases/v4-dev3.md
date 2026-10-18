# v4-dev3 — Export styling and durable reminders

Date: 2026-10-18. Git tag: `v4-dev3`. Application `VERSION`: `4.0.0-dev3`.
This development source snapshot follows `v4-dev2`; it is not a stable v4
release. Publication is limited to the new annotated tag: no branch is pushed,
and remote `main` and existing tags are unchanged. No installer, portable
application or standalone EXE is built by this source synchronization.

## Changes since dev2

- Continuous numeric X axes use small data-derived margins without rounding
  their outer bounds to distant ticks. Only finite plotted X/Y pairs determine
  this extent; unmatched source values remain in the exported tables. Ordinal
  Die Seq, Group and expanded Wafer layouts retain their identity mappings.
- Paired Reference Trends (TEM, KLA and NOVA) use solid orange strokes above
  Raw Data in both export modes, including detached child-window Trends.
  All Trend keeps its distinct Group colours while drawing Reference curves
  above Raw curves. Only drawing order changes, not source-table order.
- Plot strokes are 1.8 pt, Trend markers 4 pt, and Match markers approximately
  5 pt. Matplotlib spines and native Excel axes/plot-area frames are 1.2 pt.
  Native charts retain their square-cornered Excel style and now show all four
  plot borders. Decimal native tick labels preserve fixed-minimum offsets
  instead of displaying rounded labels at different actual coordinates.
- Native Match retains editable local X/Y ranges and the fixed software-fit
  series. Select the scatter points, not just the outer multi-series chart,
  to reveal and drag Excel's coloured X/Y source-range outlines. The separate
  fit is intentionally not replaced by an Excel-calculated regression.
- Reminders use a blue action palette, stable centred icons, clearer dropdowns
  and complete calendar navigation. Only the reminder list scrolls; its title,
  filters, search and footer stay above Log. The Workspace heading is removed.
- Reminders save automatically to the independent user file
  `%LOCALAPPDATA%\MetrologyWorkspace\reminders.sqlite3`. Updated source and
  portable versions under the same Windows user share it. The first use imports
  a compatible installation-local reminder file without changing that original;
  subsequent starts do not reimport stale copies or resurrect deleted tasks.
  Explicit `METROLOGY_REMINDERS_PATH` paths bypass migration. WKB, WMAP and other
  Tool documents keep their existing storage and save behaviour.

Raw measurement strings, source-row identities, calculation results, Card and
X/Y semantics are preserved. Original stays chart-free; Group/Wafer tables keep
their Original-based references. Match remains 15 by 11 cm and Trend/Bias at
least 25 by 11 cm. Generated labels remain English with Times New Roman.

## Validation

- `python run_tests.py`: **769 tests passed in 398.240 s**. No threshold was
  relaxed and no test was skipped. Source startup self-test with the dev3
  version exited 0 using isolated settings.
- Both actual File-menu exports completed on an owned copy of the real NOVA
  multi-parameter WKB (7,731 rows, three mapped parameters, five Groups,
  Preview and Final). The native XLSX contains **210 native charts**; the
  Matplotlib XLSX contains **210 valid embedded PNGs**, not separate image files.
  Both XLSX ZIP integrity checks pass. Every native chart has the four-sided
  frame and square corners.
- All **210 Matplotlib panels** pass axis/text canvas-bound checks. Representative
  Match/Trend panels were visually inspected. The original WKB hash, source
  frames and participation/UI states remain identical after both exports.
- Actual mouse interaction in Microsoft Excel verified dragging the native
  Match scatter series' Y range to an adjacent column, and separately dragging
  its X range. The series formula and plotted points changed accordingly;
  both changes were undone without saving the verification workbook. The final
  native frame, marker/stroke sizes and decimal labels were visually inspected.
- This correctness run observed **24.331 s Native** and **49.902 s Matplotlib**.
  These are machine-specific observations, not a controlled before/after speed
  claim or a universal timing guarantee.
- Regression coverage includes compact finite-pair X bounds, Reference colour
  and solid-stroke layering, Group-colour preservation, native source formulas,
  atomic export failure/cancellation, reminder migration, concurrent stores,
  calendar controls and body-only scrolling. User settings and original data
  files, generated reports and ignored diagnostic caches are not included in
  the tag.

## Remaining limits

The full large-report Matplotlib **30-second goal is not met**; panels, DPI and
physical sizes were not reduced to meet a timing target. Native Excel has its
own axis/tick rendering and is not pixel-identical to Matplotlib. Whole-chart
selection in a multi-series Match chart does not expose a single combined
range outline; select the measurement series as described above.

Asynchronous WKB opening/complete child restoration, version-owned background
analysis, formal background WKB Save, packaged-binary validation and native
Windows long-session validation remain separate unfinished work. Reminders
have no cloud sync or notifications while the application is closed. Older
software versions still using installation-local reminders do not share later
updates made by dev3; close them before the first migration.

Restart an already-running source application to load this snapshot's modules.
See [dev2 notes](v4-dev2.md), [export scenarios](../features/excel_export.feature)
and [reminder scenarios](../features/application_reminders.feature).

## Development reference

The Matplotlib and scientific-visualization skills informed the plotting and
verification workflow. Their source reference is: Kassis, T., Agarwal, V.,
He, Y., Patel, D., and Brueckner, A. M. (2026). *Scientific Agent Skills: A
Library of Procedural Knowledge for Research Agents*, arXiv:2609.00065v2.
[Current record](https://arxiv.org/abs/2609.00065),
[DOI](https://doi.org/10.48550/arXiv.2609.00065).
