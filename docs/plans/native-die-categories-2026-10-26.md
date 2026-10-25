# Native Die Seq categories without changing report geometry (2026-10-26)

## Scope and progress

Entry: v4.3.1 `991431d`, after initialization diagnosis `b3fe61b`. The separate
P0 progress reconciliation is checkpoint `e0ad1da`. This follow-up changes only
Excel category binding and corresponding export tests/documentation. It does
not implement any other performance hotspot or modify ownership, Undo,
Recovery/WKB protocols, Card/Mapping/Group calculations or asynchronous publishing.
No push, tag, package or Release is performed.

## Category eligibility

Native Trend/Bias/Bias percent use the local parameter-block Die Seq range when:

- The actual Group expansion states are all false or all true; mixed combined
  Show Wafer reports always retain XY. Match Wafer itself ignores inherited
  Group checkbox mixing. Individual Group sheets already expand every Wafer.
- Current point centres, display edges and caption start/end/centre positions
  match equally spaced Excel category geometry after normalization. Comparison
  uses only 1e-12 normalized floating-point noise tolerance, zero relative
  tolerance. No point, width or caption is moved to make the check pass.

All-checked is not sufficient for every possible dataset: long labels or unequal
finite-pair proportions can produce different span point densities even without
mixed checkboxes. Those cases retain the exact existing numeric XY layout,
prioritizing the user's requirement to preserve the exported image.

Eligible charts bind `cat.strRef` directly to that parameter's own Die Seq
column and keep its string cache, including leading zeros and repeated values.
These are ordered categories, not numeric Die X values that would collapse
different wafers onto the same X coordinate. LineChart uses `crossBetween=between`
to preserve the half-category outer margins. Y values remain linked editable
cells; Match scatter/regression charts are unchanged.

Existing sparse DrawingML Die ticks/title and Wafer/Group footer drawings remain
unchanged, rather than introducing a second set of automatic ticks. Their
cell-linked text still refers to the original exported Die cells; interactive
rebinding of a series in Excel does not redesign these fixed footer drawings.
Both renderers retain identical source/helper tables. Matplotlib rendering,
physical sizes, font/marker/line styles, observation order and source strings are
unchanged. No sampling, interpolation or regression rule changes.

## Red/green and native Excel evidence

The initial public export tests reproduced XY charts where local Die categories
were requested. New tests cover Preview/Final, two parameters, all/no/mixed
expansion, native range/cache binding, single observations, long labels, missing
pairs and literal source preservation. A controlled previous-XY export compares
every identity DrawingML byte after fixing only test UUID generation; anchor,
inner layout and Y scaling also remain equal.

Native Excel QA used a separate `/x` instance and only synthetic owned files.
It exposed the actual Group NOVA series formula:

```
=SERIES('Match Group (WO Card)'!$F$2,'Match Group (WO Card)'!$C$3:$C$14,'Match Group (WO Card)'!$F$3:$F$14,2)
```

Dragging its purple category source outline changed the X range to `$D$2:$D$13`;
Ctrl+Z restored exactly `$C$3:$C$14`. The all-expanded report was visually checked
for point/footer alignment. The QA file was saved only after undoing the change,
then its dedicated instance was closed. The user's existing `match - Excel`
window remained open and was not controlled or modified.

## Environment and validation

This checkout lacks its old `.venv` and historical raw performance cache. Current
test runtime is Python 3.10.20 / Qt 6.11.0, not the audit's Python 3.11.16.
Repository-required lxml and pinned OCR dependencies were missing. They were
installed only into the owned QA dependency directory, not the original Conda
environment or project requirements. Unsandboxed reads are needed for those
temporary binary dependency ACLs; `run_tests.py` still forcibly isolates all
settings, recovery, reminders and Matplotlib paths before application imports.

The exact unchanged entry exporter (`git show 991431d:metrology_app/excel_export.py`)
also reproduced CR/LF and invalid-XML failures without lxml. They disappeared
with the required dependency available; no text-safety assertion or serializer
code was relaxed. One genuine development regression was fixed: helper cells
are still emitted in both renderers even when native charts no longer use them.

- Related final regression: 79/79 passed, 175.025 s.
- XML safety/cancellation/native additions: 10/10 passed, 32.315 s (overlapping
  checks, not ten extra unique suite cases).
- Full suite: 1095 tests, 1091 passed and 4 failed in 1062.839 s. All four
  tracebacks are elapsed-time assertions in unchanged performance checks;
  this is not an all-green result. The run does not establish whether those
  timings also fail on the entry revision in this runtime.

| Unmet existing check | Observed | Required |
| --- | ---: | ---: |
| Changed Wafer Map close | 0.263749 s | <0.25 s |
| Unchanged-control Dirty checks, minimum of three | 0.114736 s | <0.10 s |
| Wafer Map opening with current Card | 0.405700 s | <0.40 s |
| Plain Writer-cell encoding | 0.332087 s | <0.30 s |

No thresholds or performance tests were changed. The four tests stop at their
timing assertion, so this run alone does not prove their subsequent assertions.
Their implementations were not modified or optimized as part of this export
follow-up. The remaining performance hotspots stay outside this round's scope.
Machine-readable results and log hashes are in
[native-die-categories-2026-10-26.json](../validation/native-die-categories-2026-10-26.json).

Private logs and synthetic QA files are under the conversation-owned
`p0-die-axis-20261026` directory, not user workspace files. Current settings
SHA-256 stayed `cb419604ac0620206baa212ac3c527dee022d8d98c1ff1e23dd7db580683014f`.
No original WKB or user Excel file was read or overwritten for these changes.
All 154 application/test Python files matched the pre-full-suite hash manifest
after the run; the checkpoint contains exactly the tested source/test revision.

## Checkpoint

This export-only change is saved in a separate local Git checkpoint with the
validation above. Existing AGENTS.md, .vscode/settings.json and docs/todos changes
are excluded. The initialization issue is already complete; do not continue
the remaining performance hotspots automatically. No push is performed.
