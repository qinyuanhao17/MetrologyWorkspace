# v4-dev2 — Development source snapshot

Date: 2026-10-18. Git tag: `v4-dev2`. Application `VERSION`: `4.0.0-dev2`.
This snapshot follows `v4-dev1`; it is not a stable v4 release. Only the new
annotated tag is pushed. Remote `main`, existing tags and their contents remain
unchanged. No installer, portable application or standalone EXE is built or
published by this source synchronization.

## Changes since dev1

- Large XLSX reports batch validated scalar rows while retaining openpyxl's
  numeric serialization and ordinary handling of unusual cell types. Small
  reports and non-lxml environments retain the normal writer. Already-compressed
  PNGs are stored without a second ZIP compression pass; their pixels and DPI
  are unchanged. Worksheet and row checkpoints improve cooperative cancellation.
- The one-shot export owner avoids repeated cyclic-GC scans of live report
  cells. Bounded rendering queues keep the existing worker cap and output order.
  The GUI and rendering workers retain their normal GC policies.
- Both export modes open at the first Match plot rather than the deliberately
  chart-free Original sheet or thousands of raw rows above the plots. Raw Data
  remains at A1; Original-based row references and the Group/Wafer reports remain.
- Matplotlib Trend/Bias include real Die Seq ticks, once-per-span Wafer captions,
  separate Group captions and correctly transformed boundaries for compact
  expanded Wafer spacing. Wider margins keep decimal and signed ticks inside
  the canvas. Match remains 15 by 11 cm; Trend/Bias remain at least 25 by 11 cm.
- Native Excel merges contiguous Group captions and retains all outer identity
  captions when Excel redraws multilevel axes. Match scatter points and the
  software-fit endpoints now share local worksheet ranges so Excel can expose
  editable data-range outlines. No Excel regression replaces the software fit.
- On-screen Trend panels remain 320 logical pixels high for single plots,
  multiple plots and parameter filtering. Extra plots scroll; taller windows
  no longer stretch a single plot to fill the page. Export dimensions are
  independent of this screen-height change.

## Validation

- Final source suite: `python run_tests.py`, **753 tests passed in 339.299 s**.
  The focused export/layout suite passed 40 tests. Source startup self-test
  exited 0. No test budget was relaxed and no test was skipped.
- Both actual File-menu exports completed on an owned copy of the real NOVA
  multi-parameter WKB: 7,731 rows, three mapped parameters, five Groups, both
  Preview and Final. Source tables, participation/UI state and the original WKB
  hash were checked unchanged.
- Every one of the full Matplotlib report's **210 panels** passed the final
  axis/text canvas-bound checks. Parameter identity annotations also passed
  overlap checks. Parallel Match/Trend/Bias pixels match their serial renders.
- Actual Microsoft Excel 16 reopened both full reports at Match and the first
  plot. Native charts were activated/redrawn and visually inspected. Editing
  Match X/Y ranges changed its point count; editing a source cell changed its
  plotted value. Trend range edits were also verified. These checks used Excel's
  native object model; physical mouse dragging of colored handles was not
  automated. Verification workbooks were closed without saving those edits.
- Real menu cancellation passed during Native preparation, Matplotlib rendering,
  and worksheet writing in both modes. Existing reports stayed byte-identical;
  owned partial outputs were cleaned. Invalid-XML and publish-failure regressions
  also preserve an existing valid report.
- Final correctness-run export times were **23.007 s Native** and **43.054 s
  Matplotlib**, with other validation activity present. These are observations,
  not a controlled performance comparison or a universal timing guarantee.
  Earlier sequential before/after measurements and exact XLSX-part equivalence
  checks are recorded in the performance document below.
- Personal settings, original WKBs, generated Excel reports and ignored
  diagnostic caches are not part of the tag.

## Remaining limits

Matplotlib's complete large-report **30-second goal is not met**. No panels were
removed and no DPI was reduced to meet a timing target. Native Excel uses its
own category-axis rendering, so it is not pixel-identical to Matplotlib.

Asynchronous WKB opening/complete child restoration, version-owned background
analysis, formal background WKB Save, packaged-binary validation and native
Windows long-session validation remain separate unfinished work. Reminders
still have no cloud sync or system notifications while the app is closed.

Restart an already-running source application to load this snapshot's modules.

See [NOVA export measurements](../plans/nova-export-performance-2026-10-16.md),
[responsiveness status](../plans/control-responsiveness-results.md),
[executable export scenarios](../features/excel_export.feature) and
[dev1 notes](v4-dev1.md).
