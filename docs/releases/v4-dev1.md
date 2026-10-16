# v4-dev1 — Development source snapshot

Date: 2026-10-16. The requested short Git tag is `v4-dev1`; `VERSION` is
`4.0.0-dev1`. This tag captures the current work following the v3.2.0 source
baseline. It is a development snapshot, not a completed stable v4 release.
Only the new annotated tag is pushed; remote `main` and existing tags remain
unchanged. No Windows installer, portable application or standalone EXE is built
or published by this source synchronization.

## Included changes

- Home-screen Reminders replace Current Session. Add/edit reminders, optional
  due dates and times, notes and flags; complete/restore, delete, search and
  filter them. A separate local SQLite store survives restarts independently
  of Tools and WKB documents. Personal reminder databases are ignored by Git.
- Parameter mapping removes the minus button. Right-click Delete acts on the
  clicked row, including embedded editors, independently of Use checkboxes.
  Other mappings and source measurements remain intact, and deletion persists
  after WKB save/reopen.
- Large Excel/Matplotlib menu exports prepare owned candidates in a separate
  process, report progress, support cooperative cancellation and publish only
  complete files. Failure or cancellation preserves an existing export.
- Exports reuse exact Wafer layouts and resolved cell styles, avoid generating
  discarded merged-caption interiors, and use lxml XML serialization. Detached
  Agg work is bounded to at most six renderers on hosts with at least 12 logical
  CPUs, with the prior four-renderer cap on smaller hosts.
- Data strings, source-row formulas, calculations, native chart editability,
  all selected plots, physical sizes, resolution and chart styling are retained.

## Verification

- Most recent repeatable complete NOVA report: 7,731 rows, five Groups, three
  parameters, Preview and Final; 25 sheets, 2,555,474 cells and 210 PNGs.
- Same-round frozen-package repeat: Native Excel 92.502 s, Matplotlib 107.201 s.
  Adopted snapshot repeat: 70.568 s and 90.717 s. Independent samples confirm
  the gain. Timings are machine-specific; this round's unchanged baseline is
  slower than earlier sessions and must not be compared directly across them.
- All 296 uncompressed report parts except creation/modified timestamps are
  byte-identical in each mode, including cells, formulas, styles, merge ranges,
  chart/drawing definitions and PNGs. No clarity reduction or data omission.
- Public export/layout checks: 32 passed. Isolated source startup smoke test:
  `python main.py --self-test`, exit code 0.
- Full `python run_tests.py`: **743 tests, 738 passed, five timing failures**
  in 612.228 seconds. This is not an all-green suite. The five failures concern
  Correlation checkbox latency, paste/Undo refreshes, saved Correlation restore,
  accepted-state dirty checks and Wafer-window opening. Fresh frozen-package
  and modified-package repeats both fail the paste/Undo and Wafer-opening
  budgets; the other three pass in both fresh repeats. No budgets are relaxed
  and no tests are skipped.
- Real menu cancellation preserves the old report and cleans owned partial
  files. Latest observed cancellation latency: 0.250 s during preparation,
  2.468 s during rendering, 40.219 s during final XLSX serialization.
- User settings and the original NOVA WKB remain unchanged.

## Known limits and remaining work

- Final XLSX serialization cancellation still waits for the library writer to
  finish safely. It is not immediate cancellation.
- Non-blocking WKB opening, complete child-window restoration, version-owned
  background analysis and formal background WKB Save remain pending.
- Native Windows long-session and packaged-binary validation remain pending.
- Reminders have no cloud sync or system notifications while the app is closed.

Details: [NOVA export measurements](../plans/nova-export-performance-2026-10-16.md),
[reminders and mapping checks](../plans/reminders-nova-export-2026-10-16.md),
[overall responsiveness status](../plans/control-responsiveness-results.md).
