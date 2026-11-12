# Group parity, Correlation locks and Wafer Map pagination

Date: 2026-11-12. Local development only. The user continues to defer full-suite
testing; AutoWeighting was not run. No release or Git tag was changed.

## Behavior

- Correlation and Trend and Wafer Map use the compact Group editor shared with
  Spectra Viewer. Identity columns precede editable TestFlag and derived
  Head/Mark/Group. Trend order remains available in Correlation; Wafer Map only
  displays classification and does not split wafers or restrict participation.
- New local Mark definitions are POR (first/fallback), POR+, POR-. Old saved or
  copied Workbook definitions are retained. Marks bulk assignment has Replace
  and Append. Appending creates/reuses a genuine composite such as Old/POR.
- Both windows retain the optional live WKB Group following switch and add
  explicit one-time Copy WKB Groups, which detaches following and preserves
  later local edits. Independent documents and Workbook child drafts retain
  Group options, flags and named assignments.
- Wafer Map captions use parameter on line one, Group / Wafer / Lot / PAD on
  line two with middle-dot separators, and Min/Max/Mean/Sigma on line three.
  Missing Group is omitted. Sigma is measured values' population standard
  deviation (one sigma, ddof=0), not the interpolated grid. Screen and Matplotlib
  use the same statistic formatter.
- Caption-only changes update current map/radius captions and selector labels
  without recreating surfaces, plot objects or selected boxes. Latest captions
  also win if changed during background rendering. Duplicate-header drafts
  remain editable and do not block reopening the parent Workbook.
- Correlation Ref and Raw sheets expose the existing metadata lock icons and
  Ctrl+L toggle. Headers, exact strings and row slots stay protected during
  paste/delete; unlocked measurements and Undo remain usable. Locks persist in
  independent documents and child drafts. Other tools' lock policy is retained.
  Linked WKB Raw refresh also merges around locked metadata before publishing
  new measurements; its former bypass was reproduced with an X-coordinate
  fixture and fixed. Manual Reference ownership stays unchanged.
- The existing 120-map preparation limit remains. Pagination now uses selected
  parameter count as well as requested wafers per page, preventing 12 wafers ×
  24 parameters from being rejected as one 288-map batch. It does not drop
  parameters. Effective page size is shown when automatically reduced.

## Focused verification

New parity/lock/caption/pagination tests first demonstrated missing behavior,
then passed after implementation. Related regression after fixing the
duplicate-header restoration issue: **221 tests passed in 96.638 seconds**,
using isolated settings. This is a focused multi-module run, not the full suite.

After final caption/pagination refinements and the explicit copy-once fixture,
**55 related tests passed in 46.802 seconds**. Full-suite testing stays deferred.

The final linked-lock fix passed **45 focused tests in 16.659 seconds**, including
`tests.test_workbook_copy_data` and its temporary-empty-parent retention checks.

The first broad invocation had one incorrectly named test module and one real
duplicate-header restoration error; neither is counted as a pass. The module
name was corrected to `tests.test_selector_updates`; the restoration error was
fixed without discarding the saved draft. A new copy-once test initially lacked
a selected parameter mapping; its fixture now explicitly selects CD.

Actual file: `C:/Users/Yuanhao Qin/OneDrive/Desktop/JC1913/matching-analysis.mwkb`.
The current participation leaves **89 wafers**, with **24** selectable numeric
parameters. All map boxes selected are reachable exactly once through **18
pages**. Real UI draws succeeded for the first page (**5 × 24 = 120 maps**) and
last page (**4 × 24 = 96 maps**); no parameter was removed. Single observations
were about 0.73 s and 0.61 s respectively; these are acceptance observations,
not a general latency guarantee or before/after speed claim.

The same probe verified a Group caption, measured Sigma, in-place Group toggle,
one-time WKB Group copying and lock-enabled Correlation source views. Native
map and both compact editor screenshots were inspected. Source SHA-256 stayed
`c002afab609b5b5820263e71abd5cdb677e77df7e464d22266af5e9e61985ab2`.

Executable workflows: `tests.test_workspace_group_parity`,
`tests.test_correlation_group_options`, `tests.test_metadata_locks` plus the
existing Array, static wafer, deferred-render, selector, Group, Spectra and
document-storage modules. BDD scenarios:
`docs/features/correlation_group_options.feature`.

Machine evidence: [workspace-groups-2026-11-12.json](workspace-groups-2026-11-12.json).
Local real-file harness: `.cache/validate_workspace_groups.py`.
Screenshots and source report: `.cache/workspace-group-validation/`.
