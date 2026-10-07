# Responsiveness review — 2026-10-06

## Request and acceptance scope

Improve startup and runtime responsiveness on the user's Desktop WKB files,
especially repeated Raw Data updates. Assess GitHub references and GPU suitability.
Validate WKB open/save, Raw Data paste/update/Undo and plots/exports with real
fixtures and independent known-formula checks. Review module ownership and project
layout, preserving scientific calculations, source strings and row identities.

The user confirmed this observable test scope. The frozen baseline is local HEAD
`cfb6b93ee8be8f7fcf377398b15bf74620c6197b`, also `v3.0.0-dev2`; it was clean.
No release, commit, push, new dependencies or original-file modification is requested.

## Verification tools

- `benchmarks/benchmark_workbook_interaction.py`: isolated offscreen Qt timings,
  cell or full-table replacement plus Undo, dirty-title refresh, optional cProfile
  and a configurable failing latency budget. It never saves the source WKB.
- `benchmarks/benchmark_startup.py`: fresh-process shell startup measurement,
  including verification that analysis windows remain lazily imported.
- `benchmarks/validate_workbook_fixtures.py`: all Desktop WKB source tables and
  state round trips in a temporary directory, independent centered least-squares
  formulas, CSV import, before/after SHA-256 checks.
- `tests/test_performance_regressions.py`: bounded interleaved identity-footer
  preparation; repeated table replacement retains Marks, excluded records,
  original row count and correct calibration after Undo.
- Existing tests cover keyboard paste, map/correlation/dynamic output, PNG/Excel
  export, parent/child saving, failure, recovery and late edits during atomic writes.

Timings include imports separately, construction, open, edit and Undo. These are
offscreen CPU/event-loop measurements, not interactive monitor FPS. Profiled runs
are attribution probes, not comparable to unprofiled acceptance measurements.
An edit changes one Raw Data value; bulk mode replaces all cells while changing
one value. Unchanged-result reuse is deliberately retained.

## First-pass changes

- Batch identity footer normalization across all spans, without per-span pandas
  frames or changed observations/labels.
- Compare ordinary document snapshots without two defensive complete deep copies;
  retain managed Correlation's local/shared-axis normalization and save freezing.
- Normalize pending and applied Group states separately instead of copying the
  applied participation lists twice.
- Memoize font widths only within one axis-label fit call; resize, zoom and font
  changes cannot retain stale measurements.
- Build each Mark membership set once during identity remapping, not once per row.
- Prepare each Group scope once within a render, shared across parameters; discard
  render-local preparation on the next update instead of retaining a stale cache.
- Fix narrow Trend caption/legend overlap; reserve separate vertical space and
  retain it after Card toggles while aligning primary chart frames.
- Fix selection-only cleared-row alignment and exclusion loss after Undo. Preserve
  source rows for applied/pending participation even when Head/Mark are disabled.
- Track logical source-row extent inside the sheet model, including blank tails;
  CellEdit Undo restores extent, while explicit replacement can shorten a table.
  The existing three-field in-memory snapshots encode empty final rows without
  requiring a WKB format change.
- Preserve distinct participation IDs for simultaneous blank identities: cell
  edits preserve positions; explicit replacement retains key-first matching,
  reserves surviving IDs, and never assigns the same ID twice. Order ignores
  empty tail markers when determining its paired-row extent.
- Cancel deferred map centering when an explicit view restoration supersedes
  it; the settling resize pass keeps the restored zoom and scrollbar positions.
  A deterministic canvas-size-transition regression reproduces the old jump.
- Add a domain glossary in root `CONTEXT.md`; retain existing calculation,
  presentation and SQLite seams. No mechanical directory relocation.

## Architecture decision still pending

The review report in OS temporary storage presents four directions: input-update
preparation, once-per-Group scope preparation, document persistence, and a deep
Parameter plot module. Recommended first: input and scope preparation. Major
interface migration and background persistence require the user's selection;
background saving also revises the synchronous-persistence decision in ADR 0002.
The scope duplication and one-pass grouped input materialization have now been
addressed locally through existing interfaces; a full scheduling/plot-module
migration has not been performed.

## External references and GPU assessment

- [PyQtGraph PlotSpeedTest](https://github.com/pyqtgraph/pyqtgraph/blob/master/pyqtgraph/examples/PlotSpeedTest.py)
  demonstrates benchmarking line plotting options with the existing backend.
- [PlotDataItem](https://pyqtgraph.readthedocs.io/en/latest/api_reference/graphicsItems/plotdataitem.html)
  documents view clipping and downsampling. Presentation sampling must not enter
  regression, filtering, source storage or export calculations.
- [Qt item-model thread safety](https://doc.qt.io/qt-6/qabstractitemmodel.html):
  workers cannot directly call GUI model interfaces; results must return to the
  owning thread. Any future worker needs frozen inputs and generation checks.
- [CuPy performance guidance](https://docs.cupy.dev/en/stable/user_guide/performance.html)
  requires CUDA-aware timing and warm-up; context initialization and compilation
  add startup overhead. This machine reports RTX 4070 SUPER, 12,282 MiB via
  `nvidia-smi`, but the measured hotspots are Python copies, labels and Qt updates,
  not dense matrix kernels. GPU conversion is not the first-pass remedy.

Scientific-visualization and Matplotlib skills guide preservation of data, labels
and screen/export semantics; their procedural reference is
[Scientific Agent Skills](https://arxiv.org/abs/2609.00065).

## Measurements and final checks

Earlier unprofiled three-iteration development measurements (not final figures):

| Fixture / workflow | dev2 baseline | First-pass result |
| --- | ---: | ---: |
| 7,731 rows, 33 columns, 2 active parameters: open | 5.77 s | 3.18 s |
| Same fixture: one-cell edit median | 2.73 s | 1.52 s before the final row-alignment fix |
| Same fixture: whole-table replacement median | 2.77 s | 1.61 s |
| 7,731 rows, 3 parameters, 6 Groups: replacement median | 3.00 s | 2.64 s |
| Source shell startup, fresh process | not separately captured | 0.347 s |

The grouped baseline overlapped a visual-validation process, so that run is
development-only evidence, not a strict before/after claim. Bulk mode changes
one value in a whole-table replacement; it does not simulate every parameter
changing simultaneously.

Final paired rerun after the source-row correctness fixes, same file/script,
frozen dev2 immediately followed by the modified source (unprofiled, three edits):

| 7,731 rows, 33 columns, 2 active parameters | Frozen dev2 | Modified source |
| --- | ---: | ---: |
| WKB open including initial analysis/plots | 9.194 s | 3.731 s |
| Whole-table update median | 5.612 s | 3.170 s |
| Largest event-loop gap during edits/Undo | 4.918 s | 2.152 s |

This pair shows about 59% lower open latency and 44% lower bulk-update latency.
The original version also slowed relative to the earlier runs; no specific
external cause is asserted. Use the paired figures rather than combining the
fast historical result with the slower later baseline. The subsequent map-only
view race fix is outside this MatchingWindow benchmark path.

The real-file audit covers seven Desktop WKBs (TEM/KLA/NOVA), three sample CSVs,
full snapshot round trips, source-derived pairing/calibration/Bias/participation,
global and Group fits, combined-Group row deduplication, excluded-row retention
and unchanged source SHA-256 hashes. The fixture oracle explicitly rejects
unsupported legacy analysis filters rather than claiming untested coverage.

Remaining multi-second update latency is visibly blocking, not a completed
fluency goal. Next architecture milestone: frozen input revisions, coalesced preparation,
worker computation with generation checks, changed/visible plot updates, then
frozen-snapshot background recovery writing preserving ADR 0002/0003 safeguards.
Qt model/control access stays on the GUI thread. GPU remains a later, separately
benchmarked dense-numerical option rather than a remedy for these Python/Qt costs.
The existing `SurfaceJob` in `plot_page.py` already isolates map computation;
reuse its immutable-input/latest-result pattern before adding another framework.

Passing functional tests does not prove absence of all bugs.

## Final verification

- `python run_tests.py`: **486 tests, 183.580 s, OK**, after the final map-view fix.
- `main.py --self-test`: exit 0 with scratch settings and recovery paths.
- `git diff --check`: exit 0; only Windows line-ending notices, no whitespace errors.
- Seven original WKB files and three sample CSV imports verified; temporary
  round trips preserve complete frames/states and originals retain SHA-256 hashes.
- Light/dark Group images inspected, including narrow wafer labels and corrected
  caption/legend separation. Existing suite covers PNG and temporary Excel exports;
  there are no supplied Excel files in the current `sample_data` directory.

## Standards

Final independent review: **0 unresolved findings**. Earlier participation-ID
collision findings are fixed. Source rows and scientific algorithms are preserved;
the centering timer is QObject-owned, coalesced and cancelled by explicit restore.

## Spec

Final independent review: **0 unresolved known findings in the reviewed changes**.
The approved open/save, update/Undo and plot/export validation scope is exercised.
Remaining multi-second latency and unimplemented major architecture work are
explicit limitations, not a claim that the fluency goal is complete.

Summary: Standards 0 unresolved; Spec 0 unresolved known findings. No commit,
tag, GPU dependency installation, packaging or GitHub publication was performed.

## Follow-up: grouped multi-parameter window responsiveness (2026-10-06)

The engineer reported long opens and slower buttons after loading
`matching-analysis_nova_multi_param.wkb`. This follow-up builds on the first-pass
local changes above, not on a fresh dev2 checkout. The fixture has 7,731 rows,
33 Raw Data columns, three mapped parameters and six plot Groups.

The new read-only `benchmark_workbook_windows` probe times opening, idle event
delivery, Group/Analysis dialogs, Group Apply, dirty-title checks and real linked
Correlation/Map windows. Settings, Matplotlib configuration and recovery are
temporary. No input fixture is saved. Each stage includes a 600 ms event-processing
observation; idle stages use 2.2 seconds. `direct_ms` excludes that fixed wait;
`settled_ms` also exposes queued work after the action returns. `--profile` is for
attribution only and adds substantial instrumentation overhead.

Initial unprofiled run versus final unprofiled run, same file, script and window
size, with no other validation workload running during these measurements:

| Action | Start of this follow-up | Modified source |
| --- | ---: | ---: |
| Open WKB and construct/show initial plots | 18.355 s | 4.538 s |
| Group Apply, unchanged settings | 2.037 s | 0.626 s |
| Open Correlation child | 17.032 s | 4.811 s |
| Open Preview Wafer Map child | 1.996 s | 1.049 s |
| Correlation including queued work and fixed 600 ms wait | 22.855 s | 5.412 s |
| Group settings action itself | 8.48 ms | 3.54 ms |
| Analysis metric dialog (includes scheduled 20 ms dismissal) | 36.07 ms | 23.22 ms |
| Parent dirty-title check | 245.02 ms | 161.74 ms |

The preceding final-code-path run measured WKB open 4.530 s, Group Apply 0.618 s,
Correlation 4.606 s, and Map 1.000 s (before cancelling the redundant Correlation
post-load refresh). These are development samples, not statistical confidence
intervals. Initial and final runs are sequential measurements during this session;
they are not a three-run paired release benchmark. Fresh-source/EXE startup,
display FPS and GPU acceleration are not measured by this probe.

Idle heartbeat gaps were approximately 11–19 ms with no sustained computation.
Group-dialog exposure can still cause about a 100 ms repaint of dense underlying
plots. Opening the settings dialog is not itself re-running the analysis. The
multi-second first-open operations still block the GUI thread; this is a substantial
reduction, **not** a completed non-blocking fluency goal.

Profiling identified:

- About 153,000 pandas row-index operations while drawing the initial grouped
  plots, mainly fetching one Die Seq value by materializing entire heterogeneous
  Raw Data rows in each Trend/Bias panel.
- Repeated full-frame wafer slices solely to prepare per-measurement Die Seq
  ordering, multiplied across parameters and Group scopes.
- About 28,560 individual Qt `setSelected` calls during Correlation initialization,
  progressively merging a growing selection, as well as repeated plan rebuilds.
- Managed Correlation dirty checks deep-copying source frames and classification
  state twice even though comparison is read-only.
- A queued Correlation recognition after synchronous source initialization,
  plus a queued dirty-title check, making the already-open window stall again.

Implemented focused changes:

1. Read Die Seq as a column array for labels instead of constructing whole rows.
2. Convert the Die Seq ordering column once per `trend_spans` call; keep stable
   ordering and missing-value handling. No cross-edit cache is introduced.
3. Apply Qt selections in compact rectangles in one operation; share this path
   between initial array construction and exact selection restoration. Disabled
   boxes, selection defaults and explicit Draw semantics remain intact. This uses
   the existing selector interface and
   [Qt's range-based selection interface](https://doc.qt.io/qt-6/qitemselectionmodel.html).
4. Compare managed child snapshots read-only, copying only UI state to remove
   parent-owned axis settings. Save/recovery snapshots and accepted baselines are
   still frozen separately; Undo and child/parent ownership remain unchanged.
5. Finish Correlation source recognition and title refresh before returning from
   initialization, cancelling only the already-covered debounce. Later source
   edits still schedule ordinary recognition and refresh plots.

Five new public-seam regression probes were observed failing before their
corresponding changes, then passing:

- 9,000-row/33-column grouped Trend: 2.318 s before; under the same 1.5 s budget
  afterward, with all curve values and Die Seq labels checked.
- 16,000 selector boxes, including disabled and restored exact selections:
  3.893 s before; under the same 0.75 s budget afterward.
- Three managed Correlation dirty checks on 6,000 rows: 0.369 s before; under
  the same 0.35 s budget afterward, with unchanged baseline and edit/Undo checks.
- 2,000 measurement spans: 0.350 s before; under the same 0.15 s budget afterward,
  with fixed expected first/last row orders and labels.
- Loaded Correlation event delivery: a 0.728 s post-load gap before; under the
  same 0.1 s budget afterward; a later actual Raw Data edit still reaches Trend.

The diagnostic/performance skills required measured hotspots and repeatable
probes; TDD kept each optimization tied to a failing observable workflow.
Scientific-visualization guidance kept all source rows, plot values, exclusions,
labels, stable order, fitted coefficients and export semantics in scope.
No new dependencies, persistent caches, GPU code, file format changes or directory
moves were needed. Broader background analysis/recovery architecture is still pending.

Follow-up verification:

- `python run_tests.py`: **491 tests, 188.650 s, OK**, including the five new
  performance probes; the suite used scratch settings/recovery. Diagnostic traces
  from deliberate save-failure tests are expected and those tests passed.
- All seven Desktop WKB files and three sample CSV files passed the independent
  formula/participation and snapshot round-trip audit; source SHA-256 hashes are
  unchanged from the first-pass audit.
- Light/dark UI/export checker passed; the narrow Group plots image was inspected
  for unchanged curve order, separate legend/title and readable Die Seq/Group labels.
- `main.py --self-test`: exit 0 with isolated settings/recovery.
- `git diff --check`: exit 0 (only line-ending notices).
- Separate final three-iteration whole-table replacement/Undo probe on the same
  grouped multi-parameter WKB: replacement median **2.068 s**, Undo **1.920–1.946 s**,
  largest heartbeat gap **1.522 s**, open **4.778 s**. Each replacement changes one
  numeric value while replacing the complete source matrix; no linked child
  windows are open in this probe. This remains blocking and is not evidence that
  replacing every parameter at once, or editing with all children open, is fluent.
- Source-only changes: no EXE packaging, Git commit/tag/push, GPU dependency
  installation or original fixture modification.

Procedural visualization reference (current arXiv record verified 2026-10-06):
Kassis, T., Agarwal, V., He, Y., Patel, D., & Brueckner, A. M. (2026).
[Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents](https://doi.org/10.48550/arXiv.2609.00065).

## Continued optimization: source updates and Correlation checkboxes

This iteration keeps the existing algorithms, source strings, Draw semantics,
Group defaults, Undo, save/recovery ownership and exports. It does not replace
the plotting backend or introduce a worker framework or GPU dependency.

Measured hotspots and focused changes:

- Cache the sheet's two detached source representations and occupied extent until
  an edit/replacement/Undo. Every returned frame is still a copy; caches are not
  serialized. Both direct model mutations and subclass `changed` signals
  invalidate the representations.
- Share measurement identity detection within one analysis result. A new result
  or Group scope owns a new cache; returned wafer source slices remain detached.
- Prepare same-sized unprojected post-run inputs once in the queued analysis,
  instead of rebuilding their Group projection before and during that analysis.
  Invalid inputs, pending Group edits and projected tables retain the eager path.
- Coalesce updates to hidden, already-built Group plots and single-wafer metrics.
  Current analysis is immediate; showing the page or exporting refreshes the latest
  data. First builds and changes of Group keys, parameters, instrument or stage
  remain eager. Every Group is retained; no new pagination or sampling is added.
- Index selected source-row owners once for grouped Correlation choices, avoiding
  the nested span-by-wafer-by-parameter scan. Reuse unchanged selector items for
  small wafer additions/removals and enabled-cell changes; larger/reordered or
  relabelled changes fall back to a complete rebuild.
- Restore source tables and Group keys before applying saved Correlation UI once.
  Skip provisional selection drawing when the full accepted child document will
  be restored. Previously, a real saved child drew Trend four times and
  Correlation three times during opening. Pending Draw choices, boxes, overlays,
  source-specific selection, controls, active tab and page index still restore.
- Convert Trend Die Seq and numeric columns once per drawn result; preserve stable
  ordering, missing data, values and export arrays. Duplicate-index inputs use the
  previous per-slice numeric path where necessary.
- Recompute current results before an immediate Excel/PNG export after editing;
  otherwise fresh source cells could be exported beside old fitted coefficients.
  Cancel only the queued auto-analysis already covered by that explicit run.
- Recreate a reused Group plot when the match instrument changes, so its Match
  axis and Trend legend change together. Stop pending layout-identity and
  auto-analysis work only after the parent actually accepts closing.
- Give native Plot/ViewBox menus a QWidget owner, including secondary axes.
  Their Qt signal connections otherwise leave live menus after plot deletion.
  The native right-click options and popup flags remain unchanged.

The new executable workflow probes cover detached frame reads and Undo, analysis
metadata isolation, consecutive full-column replacements/Undo/hidden-page export,
independent Correlation checkbox choices, saved grouped plot restoration with
known source-fit formulas, immediate export consistency, and changed instrument
axes. Each performance probe was observed failing before its corresponding
optimization, with unchanged acceptance budgets afterward. BDD scenarios are
linked to those tests. The diagnostic/performance skills guided measured hotspot
selection; TDD, BDD and scientific-visualization guardrails kept behavior and
numerical equivalence in scope. Codebase-design kept the restoration seam small.

Unprofiled observations on the current Desktop
`matching-analysis_nova_multi_param.wkb` (7,731 rows, 33 Raw Data columns, three
mapped parameters):

| Workflow | Earlier observation | Current observation |
| --- | ---: | ---: |
| Whole-table replacement median, three iterations | previous follow-up: 2.068 s | 1.332 s |
| Undo, same replacement probe | previous follow-up: 1.920–1.946 s | 1.248–1.253 s |
| Largest edit/Undo heartbeat gap | previous follow-up: 1.522 s | 1.087 s |
| Parent WKB open, window probe | previous follow-up: 4.538 s | 3.240 s |
| Open child and restore saved Correlation/Trend plots | this iteration before restore coalescing: 13.846 s | 5.122 s |
| Raw/Reference wafer checkbox, off/on | not separately recorded on this real fixture | 25.69–30.35 ms |
| Raw/Reference parameter checkbox, off/on | not separately recorded on this real fixture | 86.34–129.12 ms |
| Unchanged Group Apply | previous follow-up: 0.626 s | 0.466 s |
| Group settings dialog action | previous follow-up: 3.54 ms | 2.66 ms |

The synthetic 6,000-row, 600-wafer, three-parameter grouped checkbox probe
originally stalled for 1.46–1.53 s per toggle; it now passes its original 150 ms
budget while checking exact surviving Ref/Raw row counts and explicit Draw behavior.
The saved grouped child restoration probe originally took 3.190 s and now passes
its original 2 s budget, retaining 12,000 Ref/Raw points and independently known
fit coefficients.

The real-fixture window measurements before/after restoration coalescing are
sequential samples within this iteration, with no other validation workload
running. The comparisons to the previous follow-up are separate development
observations, not a frozen paired release benchmark or confidence intervals.
The current file contains saved child drawings: its child-open timing includes
restoring them, not merely creating an empty child. Every window-probe settled
time includes a fixed 600 ms wait and must not be quoted as direct callback latency.
Final measurements above were repeated after the menu-ownership fix. Current
idle gaps are approximately 12–13 ms, and Group dialog exposure peaked at 20 ms.
Bulk mode still changes one numeric value while replacing the entire
matrix, without linked children open. The synthetic hidden-page probe separately
changes every value of one mapped column.

These improvements do not make the remaining 1.1 s edit heartbeat gap or 5.1 s
saved-child first open non-blocking. Background analysis/preparation and recovery
remain architectural follow-up work; all-source updates with every child open
are not claimed fluent. No EXE has been rebuilt.

The first mixed full-suite run passed all functional assertions but exceeded two
latency limits (hidden-page edit: 0.973 s / 0.65 s; post-load idle: 0.140 s /
0.1 s). Investigation after 133 GUI tests found 12,579 top-level Qt widgets;
ordinary deferred deletion and garbage collection still left over 11,000.
An isolated closed five-plot fixture retained 50 QMenus, 10 QFrames and five
ViewBoxMenus before ownership was fixed; the same fixture afterward retained
only the application's existing QLabel. A new lifecycle test fails on the old
code and verifies deletion of all native menus, including a secondary axis, on
the new code. Performance fixtures now explicitly deliver earlier fixtures'
DeferredDelete events before timing, without disabling garbage collection,
relaxing any budgets or skipping measured workflow work.

### Current verification and remaining latency limits

- Latest complete mixed run: `python run_tests.py` — **499 tests, 220.710 s,
  three latency failures**. All functional assertions passed, including save,
  recovery, Undo, exports, source selection, grouping and fitted values. The
  failing timing checks were grouped 9,000-row first analysis (1.586 s / 1.5 s),
  one hidden-page replacement (1.027 s / 0.65 s), and saved grouped Correlation
  restoration (2.324 s / 2 s). Menu ownership did not eliminate all mixed-run
  variability; its remaining cause is not asserted as resolved.
- Same final source, fresh-process focused run:
  `python run_tests.py tests.test_performance_regressions -v` — **17 tests,
  20.517 s, OK**, with all original latency budgets retained. This does **not**
  make the mixed full-suite run green or prove absence of long-running stalls.
- All seven original Desktop WKB files passed independent source-derived fit,
  participation, Group deduplication and complete snapshot round-trip checks.
  Three sample CSV imports passed; original SHA-256 hashes were unchanged during
  validation. `sample_data` currently contains CSVs, not supplied Excel files;
  the suite exercises Excel import/export using temporary files.
- Light/dark Group and 240-wafer metric UI checkers passed. Narrow Group plots
  and checked metrics screenshots were inspected: titles/legends remain outside
  data, labels remain readable, Draw/docking/Uncheck all restores the layout,
  and highlight cancellation still works.
- `main.py --self-test`: exit 0 using scratch settings and recovery.
- `git diff --check`: exit 0, with only Windows line-ending notices.
- No original WKB or user settings were rewritten, no dependencies/GPU code were
  installed, and no EXE, Git commit, tag or publication was produced.

These current results supersede earlier phase-specific “Final verification”
headings for the current source. The present changes improve measured workflows
without feature removal; the overall non-blocking responsiveness goal remains
incomplete and the three mixed-run latency failures remain explicitly open.

## Recovery follow-up: measured duplicate-write elimination

The explicitly requested `systematic-debugging` skill was installed from
[obra/superpowers](https://github.com/obra/superpowers/tree/main/skills/systematic-debugging)
and used for reproduction, separate first-write/repeat profiling, working-pattern
comparison, single-hypothesis changes and regression checks. Existing TDD/BDD
skills kept the workflow assertions executable. No recovery protection or
validation was removed to meet a timing budget.

The root timer still checks every 30 seconds. Previously any dirty document
rewrote a complete aggregate recovery on every tick, even with no new edit. The
multi-parameter Desktop fixture produces a 34,496,512-byte recovery payload.
The repeated write was synchronous on the GUI thread, and root/child snapshots
were captured again during dirty checks and payload construction. Repeat-only
profiling also showed large state serialization occurring before an already
changed measurement table could establish dirtiness.

The root now captures each candidate once, compares it to the last successfully
written frozen payload before copying/packing another payload, and skips a write
only if live data, accepted baseline, child scopes, child drafts and source-follow
state still match. The recovery path, source revision and full on-disk SHA-256
must match too: a deleted or replaced file is not mistaken for a durable draft.
Snapshot comparison tests frame equality before serializing settings. Restore
still gets owned copies, and the existing schema validation, lock, atomic replace
and accepted/draft ownership rules remain unchanged. A single latest payload is
retained in memory per root document; this trades memory for eliminating repeated
packing and writes. New successful writes replace that cache; cleanup invalidates it.

Sequential unprofiled paired probes used the source frozen at the start of this
follow-up and the current source, with identical scratch-only harness/fixture and
no other validation workload running. Three callbacks each:

| Recovery callback | Frozen source | Current source |
| --- | ---: | ---: |
| First changed-draft write | 919.34 ms | 728.66 ms |
| Repeat check 1, no new edit | 1,451.05 ms | 309.36 ms |
| Repeat check 2, no new edit | 1,467.33 ms | 292.17 ms |
| Repeat median | 1,459.19 ms | 300.76 ms |
| File writes across these callbacks | 3 | 1 |

This is about a 79% reduction in the repeat-check median, not proof of a
non-blocking application. The synthetic 6,000-row/300-wafer/33-column probe with
a saved broad Correlation selection passes its unchanged 250 ms repeat-check
budget in the focused run. The real fixture still exceeds that budget. First
writes and new-version writes still run synchronously; snapshot copying and
validation remain measurable work.

Additional public workflow tests cover unchanged file revision/mtime, later exact
string edits, recovery and Discard to the accepted file, missing/replaced recovery
files, Undo cleanup, and a failed atomic commit retaining the previous draft and
retrying the next check. Existing parent/child recovery tests cover independent
accepted bases and other child drafts. The input WKB hash was unchanged in both
paired probes. Full-suite status for this follow-up is recorded below; the earlier
mixed-run results above are not a green result for this code.

### GitHub patterns and the next architectural boundary

- [Spyder autosave](https://github.com/spyder-ide/spyder/blob/master/spyder/plugins/editor/utils/autosave.py)
  is the closest Python/Qt reference: it compares current/accepted/autosaved
  content hashes, avoids duplicate writes and removes obsolete drafts. Its text
  editor assumptions, skipped newly created files and interval are not copied
  into this application's typed, untitled and parent/child workspaces.
- [VS Code WorkingCopyBackupTracker](https://github.com/microsoft/vscode/blob/main/src/vs/workbench/services/workingCopy/common/workingCopyBackupTracker.ts)
  uses content versions, cancellable delayed backup operations and asynchronous
  backup preparation. Its lifecycle/restore handling is a reference for a future
  single-writer latest-generation recovery scheduler, not code already added here.

The recommended next stage is an owned snapshot captured on the GUI thread,
followed by one background writer that never reads Qt widgets. Keep at most the
latest pending generation, retain the last valid file until atomic commit, and
coordinate Save/Discard/close before stale callbacks can recreate old recovery.
This changes the synchronous persistence boundary accepted in ADR 0002 and needs
a focused design decision plus race/lifecycle tests; it is not silently bundled
into this duplicate-write fix. GPU acceleration would not address the observed
deepcopy/JSON/SQLite bottlenecks. No new application dependency, file format or EXE
build was introduced.

### Recovery follow-up verification

- Full mixed suite: `python run_tests.py` — **503 tests, 226.346 s, two latency
  failures**. The hidden-page replacement maximum was 1.024 s against 0.65 s;
  saved grouped Correlation restoration was 2.285 s against 2 s. All functional
  assertions and the new recovery timing test passed. This run is not green.
- Focused recovery/typed-storage run: **25 tests, 14.520 s, OK**; missing/replaced
  recovery, Undo cleanup and failed-commit retry probes subsequently passed too.
- Fresh-process performance suite: **18 tests, 27.890 s, OK**. It does not replace
  or invalidate the two mixed-run timing failures.
- All seven original Desktop WKB files passed complete temporary snapshot round
  trips, independent fit/participation checks and original SHA-256 preservation.
  All three sample CSV imports passed with unchanged hashes.
- `main.py --self-test` passed with scratch settings/recovery; `git diff --check`
  passed, with Windows line-ending notices only. No EXE was rebuilt.
- Original latency budgets are unchanged. The paired real-fixture check above
  remains about 0.30 s; meeting the synthetic budget is not a claim that all real
  workspaces or long-running sessions have no pauses.

## Window and control latency audit

This continuation preserves the current source/row semantics and the already
agreed public seams: document open/save, Raw Data replacement/Undo, plotting and
export. `systematic-debugging` and Python profiling guided hotspot selection;
TDD kept numerical, selection and persistence assertions next to the timing
checks. Codebase-design kept comparison state distinct from owned persistence
snapshots without introducing a new storage format or background writer.

Changes verified through these workflows:

- Die Seq detection now slices the sequence column rather than a whole wide
  table for every wafer. Conversion, missing values, run detection, non-default
  indexes, source strings and positional row mappings remain unchanged.
- Default wafer counts already returned by header recognition are reused rather
  than scanning all numeric columns again. Custom grouping still uses its own
  selected primary column.
- Correlation table restoration suppresses provisional plot plans between Ref
  and Raw loads and installs saved sidebar choices before preparing the combined
  source plan. All unselected Raw columns remain stored. Duplicate-header drafts
  are still accepted as editable drafts; no analysis is forced on invalid headers.
- Valid current Cards are reused when offering them to a child. The immediate
  edit-before-queued-analysis workflow verifies freshly fitted coefficients, not
  a stale prior result. Opening Correlation/Map reuses its validated Workbook
  descriptor for participation instead of capturing it again in registration.
- Dirty checks may request an immediate read-only Match snapshot. Default
  snapshots and Save/recovery continue to own/freeze state, and full validation
  is retained. Baseline equality and typed Save/Discard/failed-write tests cover
  the comparison path's non-mutation requirement.
- Participation validation uses an ID set rather than a repeated list scan.
  All exclusions and invalid-ID rejection remain intact.
- Trend font changes update existing titles and primary axis label styles;
  curve arrays, comparison controls, panel sizes, zoom and scroll stay in place.
  Export/copy caches are invalidated so the static mirror uses the new font.
  A stronger on-screen label assertion caught an intermediate style-only API
  call that cleared omitted axis text. The final call explicitly retains text,
  units, unit power and SI-prefix policy; the original callback budget remains.
- Visual inspection also exposed a pre-existing large-font export defect:
  three-line wafer metadata could overlap the next row's title, and the first
  title extended beyond the canvas. The frozen source reproduces the new failing
  geometry test. Export now reserves font-dependent header/footer space for
  every row; 8/16/20-point checks keep annotations inside the canvas and between
  their own plots, retaining all eight source points and linked secondary axes.
  This adjusts export height, not curve values, units, X ranges or interpolation.

The window harness now distinguishes direct callback time, async completion,
queued GUI work and heartbeat gaps. Plot controls are tested after explicit
draw, not after sidebar invalidation left an empty selection page. Map controls
use a bounded four-map sample (two wafers by two mapped parameters), not every
possible map. Recovery is stopped only inside this diagnostic mode and measured
as a separate explicit action; production recovery remains every 30 seconds.
The source-file hash is checked even during harness cleanup.

Scientific-visualization/Matplotlib guardrails informed the style-only change:
no point thinning, interpolation change, hidden data or altered unit/axis policy.
Skill source: Kassis, T., Agarwal, V., He, Y., Patel, D., & Brueckner, A. M. (2026).
[Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents](https://doi.org/10.48550/arXiv.2609.00065).
The current arXiv record was checked; this citation is provenance for the skill,
not evidence that these latency changes or plots have an external certification.

### Paired real-workbook control measurements

Sequential unprofiled probes used identical current harnesses and the source
frozen at the start of this audit. No other validation workload ran alongside
either probe. Fixture: `matching-analysis_nova_multi_param.wkb`, 7,731 Raw rows,
33 columns, three mappings, saved child plots. These are single paired samples,
not confidence intervals or frozen-EXE frame-rate measurements.
The current column below is the final repeat after the visual/axis-label fixes.

| Callback / workflow | Frozen source | Current source |
| --- | ---: | ---: |
| Open WKB | 3,268.96 ms | 3,068.76 ms |
| Restore/open Correlation + Trend | 5,155.87 ms | 4,464.86 ms |
| Open Map after Correlation imports | 915.83 ms | 624.35 ms |
| Unchanged Group Apply | 476.60 ms | 399.42 ms |
| Dirty identity check | 199.54 ms | 120.99 ms |
| Trend font change on drawn plots | 1,261.95 ms | 2.43 ms |
| Explicit Correlation redraw | 167.49 ms | 125.28 ms |
| Explicit Trend redraw | 1,909.55 ms | 1,940.07 ms |

Settings dialogs themselves remain prompt: Group settings 1.80 ms direct,
26.53 ms largest heartbeat gap; Analysis dialog action 20.58 ms, including a
scheduled 20 ms dialog rejection (not 21 ms intrinsic widget construction).
Correlation wafer checks took 25.29–33.76 ms; parameter checks 85.85–123.30 ms.
Their unchanged order-of-magnitude latency is not claimed newly accelerated.

For deferred/worker work, direct time alone is misleading. Correlation font and
minimum-R² changes were under 0.2 ms direct but largest gaps were 55.47/98.61 ms.
Trend font's current largest gap was 11.62 ms. The four-map draw completed in
873.56 ms, with a 460.93 ms GUI gap; fill-edge completed in 617.27 ms, with a
289.23 ms GUI gap. Point/contour toggles peaked at 126.87/152.39 ms, and colorbar
at 377.86 ms. The colorbar/interpolation rendering path itself was not changed.
The separate first aggregate recovery after child control edits still blocked
for 1,513.76 ms; unchanged recovery deduplication does not remove new-write cost.
Every ordinary settled sample includes a fixed 600 ms observation window; that
must not be quoted as callback or completion latency.

The source shell opened in 341.85 ms in a separate fresh-process probe, with no
analysis modules preloaded. This is not packaged-EXE startup time. WKB open,
first restored child plots, new recovery versions, broad explicit Trend redraw
and portions of Map rendering are still synchronous stalls. The proposed
staged/background opening UX was asked about, not silently implemented.

Additional fresh-process probes covered TEM (13 rows, five mappings) and KLA
(3,300 rows, one mapping; the file is named `matching-analysis_nova.wkb` but its
stored Match type is KLA). WKB open took 669.06/457.61 ms, first-use Map including
plot imports 721.01/878.11 ms, subsequent Correlation 825.64/628.95 ms. Their
wafer/parameter toggles ranged from 1.06 to 27.75 ms direct. The later `map`
measurement in `--map-first` mode is reactivation, not first opening.

The multi-parameter whole-table replacement probe (three iterations, no linked
children open) measured 1,042.76/1,021.12/1,010.45 ms including queued analysis and
dirty-title checks. Undo took 1,111.62/1,087.09/1,094.83 ms, and the largest
heartbeat gap was 889.04 ms. These remain visible pauses; this unpaired sample is
not a claim that frequent Raw Data replacement is now non-blocking.

## Parameter mapping and Raw Data keyboard follow-up

The added workflows are mapping Use off/on, actual Ctrl+A, Delete/Backspace and
keyboard Undo on the Raw Data view. Profiling separated immediate callbacks
from queued analysis and drawing. The old mapping layout key included the
complete parameter list, so changing one Use check discarded every remaining
plot card. The existing data-equality reuse check could not run after that clear.
The final implementation removes only deselected cards when mode, Match type,
Bias views and grouping layout remain compatible. Surviving curves, docking and
zoom remain. A newly selected parameter is still fitted and drawn normally.

Reuse also compares both source-column names: an independent three-row test
reproduces a stale Raw title on the frozen source when equal-valued columns are
switched. The final source refreshes the title without changing the fit.

Ctrl+A itself returned in under 1 ms, but Qt's subsequent selection paint made
tens of thousands of calls to cell flags. Normal SheetModel flags now reuse the
exact native selectable/editable/never-has-children mask. Clearing the whole
sheet previously materialized about 326,000 QModelIndex objects, including
trailing empty cells. Normal uniformly selectable sheets now clear stored
values intersecting selection ranges and retain the existing positional edit/
Undo transaction. Models with custom disabled cells or source-row projections
keep the original Qt selectable-index path. Tests cover partial ranges, protected
cells, exact source strings, retained blank-row extent and full keyboard Undo.

### Paired input-control measurements

Frozen source was captured before these two input optimizations. The same final
`--input-controls` harness and original 7,731-row/33-column multi-parameter WKB
were used sequentially. Mapping and Undo measurements explicitly wait for
automatic analysis completion, followed by a separate 600 ms observation window.
This prevents remaining paint from the previous action being attributed solely
to Ctrl+A. Values below exclude that fixed observation window.

| Workflow | Frozen input source | Current input source |
| --- | ---: | ---: |
| Uncheck mapping, analysis complete | 2,016.59 ms | 556.58 ms |
| Check mapping, analysis complete | 2,586.07 ms | 1,326.28 ms |
| Ctrl+A largest GUI gap | 436.55 ms | 292.42 ms |
| Delete selected Raw cells, direct | 3,509.87 ms | 723.38 ms |
| Undo, analysis complete | 3,100.25 ms | 2,895.94 ms |

Both WKB hashes remained unchanged and exact Raw Data was restored after Undo.
These are single paired samples, not confidence intervals; they do not imply
instant mapping calculation, repaint or Undo. The added parameter still needs
its own plot, and all-row analysis remains synchronous. Broader Correlation and
Map first opens were about 10.1/1.2 s in this later process environment, versus
about 4.5/0.6 s in the earlier control audit. Do not mix those environments into
a claimed before/after improvement; parent opening in this pair was similarly
3.85/3.88 s. No source calculation or display-sampling policy was reduced.

The later Windows sandbox default Temp directory refused settings/cache writes
and temporary-folder cleanup. Validation was moved to the already authorized
visualization output directory using process-local `tempfile.tempdir`, not by
changing user settings, system Temp or filesystem permissions. Earlier failed
cleanup runs are not recorded as successful validations.

The long mixed run also exposed a real view-restoration race, not just a timing
threshold: the Map scroll offset became horizontally centered instead of staying
at 70. An expanded existing public test deterministically reproduces it with a
late workspace resize after `restore_view`. Percentage zoom does not depend on
viewport width, so resizeEvent now schedules width fitting only in Fit-width
mode. The expanded test, option-refresh view preservation and KLA child-refresh
view preservation all passed (three tests, 45.070 s). No delays/budgets were
extended to hide the recenter, and user-selected zoom/scroll were retained.

Verification history matters here: earlier mixed audits were not fully green.
The 508-test run took 241.765 s with four timing failures. After the export
spacing fix, 509 tests took 241.905 s with three timing failures. A later
509-test run took 389.789 s with seven timing failures plus the Map view race;
the cause of its broader timing variability is not claimed resolved. After the
input changes, an authorized-scratch 197-test focused run took 240.459 s with
eight timing failures plus the same view race. The four newly added input
correctness/performance guards passed, and a specific late-resize trigger was
then reproduced and guarded as described above. None of those older runs is a green result for
the final source; final-source verification is recorded separately below.

### Final-source verification

- Complete final-source run with a fresh scratch settings/recovery location:
  **513 tests, 507.919 s; nine failures and one error**. Seven failures were
  unchanged latency guards (grouped Trend, hidden-page update, measurement
  identity, repeat recovery, saved Correlation restoration, dirty identity and
  warm Map opening). Two were UI-state assertions in the long mixed run:
  threshold-filter refresh had one fit instead of two after its existing wait,
  and the KLA Map refresh still centered at 1,733 instead of offset 70. The
  bounded percentage-resize fix above does not establish that every recenter
  path is fixed. The error was Windows sandbox refusal of `os.link` in the
  existing same-file-alias safety test; that protection was not removed.
- Fresh-process recheck of the two UI-state workflows plus mapping preservation
  and Raw keyboard clear/Undo: **four tests, 25.709 s, OK**. This does not erase
  the mixed-run failures or prove long-session stability. The four added input
  guards also passed together (**four tests, 2.753 s**), including equal-valued
  column-title refresh, partial ranges and protected cells.
- The final comparison uses exact source snapshots and fit assertions, not
  disabled tests or relaxed budgets. No EXE, commit, tag or GitHub publication
  was produced. Source-file comparisons against the frozen input baseline
  reported no whitespace errors; normal repository work-tree Git operations
  became unavailable in the later sandbox, so their exit status is not claimed
  green for this phase.
- All seven original Desktop WKB files passed final-source independent fit,
  participation, Group-row deduplication and complete temporary snapshot
  round-trip checks. All three sample CSV imports passed. Original SHA-256
  hashes remained unchanged. `sample_data` contains no supplied Excel files;
  temporary Excel import/export remains covered by the suite.
- Final-source `main.py --self-test` passed using authorized scratch settings
  and recovery. Scientific calculation/plot policy was not changed for speed;
  the remaining long-run UI-state and latency failures are explicitly unresolved.

## Recovery implementation and configurable interval — 2026-10-07

The user explicitly approved background recovery, cancellation and final-file
publication after the initial safety review required separate confirmation.
The incomplete first wiring was withdrawn before that approval; only the
approved implementation below remains. Original workbook files, user settings,
calculation/plot semantics and EXE builds are not modified by the probes.

### Implemented scope

- Main-window Settings now exposes **Recovery interval**, default **120 seconds**,
  range **30–1800 seconds**, persisted as `recovery_interval_seconds`. Save updates
  every open document; Cancel retains the saved value. Managed child timers stay
  stopped, and saving unrelated settings does not restart an unchanged interval.
  Invalid stored values fall back to 120 seconds. Global timer preferences are
  not measurement/document edits. Longer periods increase the crash-loss window.
- Automatic timer callbacks call `request_recovery()`. One background disk writer
  receives owned frames and detached plain state, compares accepted/current/last
  recovered content, validates Match/Group state and prepares a complete private
  SQLite candidate through the existing storage module. It never reads Qt widgets
  or models. Repeated requests retain one latest-request marker, not another full
  queued snapshot. Cancelled queued requests also release their input frames while
  waiting behind a slow writer.
- The GUI owner publishes only a still-owned completed result, with an exclusive
  lock and final full SHA-256 revision check before atomic replacement. Preparation
  errors and failed publication leave the previous valid recovery intact. A closed
  or discarded document cannot publish its old future; eventual private-candidate
  cleanup does not access Qt. File format/payload versions remain unchanged.
- Save/Open/Recover/close decisions pause automatic recovery, including nested
  modal event loops. A test first reproduced publication while a cancelled Save As
  dialog was open; the shared decision guard now suspends publication and resumes
  an outstanding draft after cancellation. Parent/child accepted bases, unaccepted
  drafts and source-follow semantics remain distinct.

This is a bounded first stage, not the complete version-token/incremental design.
Owned snapshot capture, final SHA-256/replace, rare clean-draft rechecks and explicit
`write_recovery()` calls used by synchronous lifecycle workflows remain on the GUI
thread. Large open children can add capture cost. Python/GIL contention and private
candidate cleanup are still measurable; there is no universal zero-stutter claim.
Recovery is periodic at the configured interval, not a new 2-second autosave loop.

### Paired real-file measurements

The source frozen at the start of this turn and current source used the identical
updated `benchmark_workbook_recovery.py --automatic --iterations 3` harness.
Each pair ran sequentially with no competing suite. The fixture was Desktop
`matching-analysis_nova_multi_param.wkb`, 7,731 × 33, including saved child state
but no additional open child windows. Offscreen Qt, scratch settings/recovery,
same 34,496,512-byte payload, exact edited string and unchanged source SHA-256.

| Probe | Frozen-source GUI gap | Current-source GUI gap |
| --- | ---: | ---: |
| Pair 1, first changed recovery | 1,288.74 ms | 178.89 ms |
| Pair 1, unchanged checks | 600.74 / 633.78 ms | 127.73 / 98.56 ms |
| Pair 2, first changed recovery | 750.33 ms | 178.73 ms |
| Pair 2, unchanged checks | 297.50 / 326.09 ms | 118.20 / 155.44 ms |

Current request callbacks took 160.09–178.64 ms for the first write and
88.35–118.15 ms for repeats. End-to-end first-write completion was 1,104.36 /
1,095.07 ms versus the frozen 1,288.68 / 750.31 ms: total durability latency is
not consistently faster. Three callbacks wrote one recovery file in each run.
These are paired samples, not p95 or EXE frame-rate measurements. The proposed
100 ms maximum-gap target is not met by every sample; owned state capture remains
a next optimization seam. Profiling data is kept separate from these timings.

### Verification

Public document/window tests cover slow fsync while accepting edits, merged latest
requests, Save/Discard/close cancellation, cancelled Save As through a nested event
loop, failed final replace retaining the last good draft and retrying, deleted
recovery recreation, aggregate child drafts and each child's Discard basis, settings
Save/Cancel and live root/independent/managed timer updates. Initial storage/settings
run: **84 tests, 19.863 s, 83 passed, one environment error**: Windows sandbox refusal
of the existing `os.link` same-file-alias test. That safety test was not removed.
Full-run and final-state checks are recorded after completion below.

Final-state verification:

- A final-source automatic probe after the private `.tmp` and queue-input guards
  measured request callbacks **162.77 / 123.28 / 84.78 ms**, GUI heartbeat gaps
  **183.40 / 129.58 / 101.51 ms**, and completion **1,230.73 / 612.78 / 566.86 ms**.
  One file write, identical payload size, edited-string and original-hash checks
  passed. This confirms improved responsiveness, not faster total persistence or
  the proposed 100 ms worst-gap budget.

- Final storage/settings subset: **84 tests, 40.066 s**, 83 passed and the same
  sandbox `os.link` error. All nine newly added settings/recovery behaviors passed.
  Ready candidates use a private `.tmp` suffix, outside Recover's workspace filter
  and valid Save As suffixes; cancelled queued work releases its captured inputs.
- First complete run: **522 tests, 406.028 s**, eight failures and one environment
  error. After the final private-candidate and queue-input cleanup guards, a fresh
  complete run: **522 tests, 488.288 s**, **515 passed, six failures, one environment
  error**. There were no new recovery or settings failures. The final failures were
  the pre-existing KLA Map scroll restoration (1,733 instead of 70), grouped Trend
  preparation (2.698 s / 1.5 s), hidden Group replacement (1.840 s / 0.65 s), saved
  Correlation restore (4.691 s / 2 s), wide-workbook dirty check (0.120 s / 0.10 s),
  and warm Map opening (1.049 s / 0.4 s). No threshold was relaxed. The explicit
  synchronous repeat-recovery guard varied between runs; that path is not claimed
  newly non-blocking. The full suite is not green.
- Seven original Desktop WKB files passed complete temporary round trips,
  independent coefficients/participation checks and unchanged original SHA-256
  assertions. Three sample CSV imports also passed. No supplied Excel fixtures
  were present in `sample_data`; existing temporary spreadsheet tests remain.
- `main.py --self-test`: exit 0 with isolated settings and recovery directories.
  Light/Dark Settings previews were checked at 440 × 661 px with the new interval
  row readable and Save/Cancel in bounds. Source comparisons use Windows-aware
  whitespace checks against the frozen source; normal Git work-tree operations
  remain unavailable in this sandbox. No EXE, commit, tag or push was produced.
