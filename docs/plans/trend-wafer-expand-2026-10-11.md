# Readable wafer identities and linked Group state

## Confirmed behavior

The user confirmed the third screenshot is a scrollbar reference, not a new statistical plot.
Add an `Expand Wafers` checkbox to the Workbook results tabs and the Correlation and Trend options (renamed at the user's request).
Expanded Trend/Bias plots reserve enough horizontal space for every enabled caption, with native horizontal scrolling.
Disabling expansion restores compact layout. The Workbook and each named Trend keep independent saved choices; older WKB files default to compact.

Only on-screen ordinal spacing and width change: source strings, real Die Seq labels, observations, numerical calculations, participation and row identities remain intact.
Existing Export PNG dimensions/pixel caps and Copy PNG's full-grid/pixel-cap behavior remain in use.
Match size, curves, comparison controls, zoom and existing docking are retained.

## Implementation boundaries

- `WaferSpacing` allocates each ordinal span its own caption allowance using real font metrics, separate from calculation/data code. A one-point wafer no longer sets the scale of the whole curve.
- Display positions are normalized to the same complete ordinal extent. Curves, comparison axes, boundaries and actual Die Seq labels share the spacing; cancelling restores the exact source ordinals. Source tables and static PNG export calculations are untouched.
- `ParameterPlotArea` preserves its plot widgets and compact splitter sizes; each card has a horizontal-only scroll container.
- `SequencePage` updates existing panel widths and curve display positions without drawing/fitting again, including parameter-filter/column/caption changes.
- Workbook expansion is saved in `match_ui.expand_wafer_ids`; per-Trend expansion uses the existing page-control snapshot. Restore of old controls explicitly defaults to false.
- Root Workspace orchestration delegates linked-context restore to CorrelationWindow. Independent/manual windows retain their own contexts.

## Group bug and compatibility boundaries

The actual Desktop `matching-analysis.wkb` saved both parent classification checkboxes off, but its linked named child retained `mark_enabled: true` and displayed `Old`.
Linked analyses now restore the current Workbook classification, not a stale accepted child copy.
Source measurement keys reconcile saved Draw boxes across classification changes in either direction; a second Save/reopen retains valid boxes.

Additional guards preserve the existing Data selection/Full data contract:

- Source-restricted child tables receive the exact corresponding TestFlags, including accepted/editing-state copies; flags are not shifted to other records.
- Full data retains classification but removes only the parent participation restriction in the derived child plan; parent state is unchanged.
- Ownership binding preserves the pre-restored Full data scope.
- Local sidebar choices remain local; selecting a newly available wafer is still explicit.
- Synthetic unrestricted participation uses stable source keys when no parent record ID exists, avoiding random identity churn.

## Verification evidence

- Three initial failing examples: old `Old` captions after parent classification was disabled; missing child checkbox; missing Workbook checkbox. Each passed after its targeted change.
- The reverse Group transition exposed missing Draw boxes and now passes, including another Save/reopen.
- The 12-row Head A/Head B example exposed unprojected flags and ownership rebinding of Full data; its strict source-count/identity/parent-participation checks now pass.
- 25 focused tests passed together: new workflows, existing Workbook data-scope choices and independent named windows. Earlier plot-caption and docking-focused checks also passed.
- First native Qt acceptance passed all seven Desktop WKB isolated copies. The real 7,731-row fixture had readable captions and actual curves at both horizontal endpoints; first/last screenshots were inspected. The child grid was 66,724 pixels wide and the Workbook card 2,109,573 pixels wide. Values, source tables, grouping and Save/reopen were verified.
- All original Desktop WKB and `config/settings.yaml` hashes remained unchanged.

- Final `python run_tests.py`: **661 tests passed in 272.955 seconds**; see `.cache/trend-expand-20261011/full-final.txt`. Source precision/identity, participation, viewport, undo, atomic persistence/recovery and performance checks remain enabled.
- Final-source native Qt acceptance passed all seven Desktop WKB isolated copies again, now also checking expansion cancellation and retained plot objects. First/last endpoint images were inspected; saved parent/child choices restored correctly. Original Desktop WKB and formal settings hashes remained unchanged; see `.cache/trend-expand-20261011/desktop-final.txt`.
- The first 661-test run found one collapse-layout failure after earlier Qt display settings. Geometry tracing showed a cached 9,984-pixel minimum hint despite cleared minimum-width constraints; a later Qt event eventually reduced it to 544 pixels. Existing layouts/splitters are now refreshed synchronously before shrinking the existing grid. All 51 performance/workflow tests then passed together in 40.293 seconds; assertions and timing thresholds are unchanged.
Executable BDD examples: `docs/features/trend_wafer_labels.feature`; tests: `tests/test_trend_wafer_labels.py`.
Logs and repeatable native helper: `.cache/trend-expand-20261011/`.
Native copy/image directory: `C:/Users/Yuanhao Qin/AppData/Local/Temp/metrology-expand-20261011/acceptance/`.

## Compact expansion follow-up

The first expansion used a global scale derived from the narrowest span. A 211-row example with one single-point wafer required 93,211 pixels for one plot. Local caption allowances now avoid this global inflation; the regression covers unequal wafer sizes, original strings and Y values, every caption, real horizontal overflow, cancellation and compact docking.

Additional regressions cover Card changes in both Workbook and Group plots, and a comparison on a second Y axis. Neither source values nor Group classification are changed. Both controls are named `Expand Wafers`; the persisted `expand_wafer_ids` field and object name remain compatible with existing WKB.

Latest evidence is combined with Reference-source verification in `reference-and-compact-expansion-2026-10-11.md`. Earlier test counts and widths above describe the earlier implementation, not this compact follow-up.

## Expanded panels collect Wafer identities (user correction)

The user reported that an expanded Workbook Trend still drew the source row
order, so the same Wafer identity repeated across the axis. Interleaved Wafer /
Lot / PAD rows are exactly the case compact spacing cannot fix: repeated captions
point at scattered observations.

`Expand Wafers` now collects each Wafer, Lot and PAD identity into one
continuous range on the Workbook Trend, Bias and Bias % panels, in
first-appearance order, keeping the source rows inside each identity. This is a
display rule only:

- The saved Trend order (`original`, `wafers`, `groups`) is untouched, so
  collapsing restores the chosen order exactly; classification scopes keep
  their Group order and are unaffected.
- Match points, fits, participation, source strings and the Raw/Reference tables
  are unchanged, and the drawn Trend/Bias curve objects are reused instead of
  recreated (`refresh="sequence"`).
- Captions follow the drawn ranges: 6,958 real-fixture rows went from 1,647
  row-run captions (407,933 px wide, one caption per row run) to 255 identity
  captions (63,255 px) on the Desktop NOVA workbook, with the same observations.
- Toggling costs 0.41 s to expand and 0.30 s to collapse on that 6,958-row
  fixture; the compact drawing path is unchanged.

Executable example: `docs/features/trend_wafer_labels.feature` scenario
`Expand interleaved Wafer identities`; regression
`tests/test_trend_wafer_labels.py::test_expand_collects_interleaved_wafer_identities_without_touching_sources`.
`tests/test_performance_regressions.py::test_warm_stage_switch_and_group_apply_keep_current_results_promptly`
now selects the Trend order by value instead of by combo index, and
`tests/test_matching_window.py` expects the renamed `Single-Wafer metrics` tab.

Verification for this follow-up:

- `python run_tests.py`: **693 tests, 1 error** — the error is the known
  sandbox-only `os.link` refusal in
  `test_storage_v2.test_copy_cannot_overwrite_owner_or_samefile_alias`; the same
  test passes when run outside the sandbox. The two stale expectations from the
  interrupted run (tab title, Trend-order combo index) are updated, and the new
  regression passes inside the full suite.
- `main.py --self-test` exits 0; `git diff --check` is clean for every file this
  follow-up touches. The only whitespace warning in the working tree is the
  user's own edit in `docs/plans/resumed-ui-2026-10-09.md`, left untouched.
- Isolated-copy acceptance over all seven Desktop WKB files passed: unclassified
  workbooks collect identities (`matching-analysis_nova_multi_param.wkb`
  1,964 → 255 captions, `matching-analysis_nova_testfilter1.wkb` 1,647 → 255),
  grouped workbooks (`matching-analysis_nova1.wkb`,
  `matching-analysis_nova_testfilter.wkb`) keep their Group order and curves,
  every observation is retained, collapsing restores the exact row arrays and
  captions, and the originals' SHA256 values are unchanged. Script:
  `.cache/expand-acceptance/expand_acceptance.py` (scratch; not part of the repo).
