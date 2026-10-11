# Reference sources, repeated mapping rows and compact wafer expansion

## User-confirmed behavior

- Parameter mapping can add another row even with only one numeric Reference column. Each row keeps its own name, Raw column, Use flag, Card and Bias limit; unfinished rows survive Save/reopen.
- Ref Data uses the corresponding Raw row's Wafer ID, Lot ID, PAD Name and Die Seq, followed by all original Reference columns and literal values. Parameter mapping does not rename or remove these Reference columns. Existing Data selection and Full data scope remain in force.
- Both expansion controls are named `Expand Wafers`. Each wafer receives enough space for its own captions and observations, rather than letting the shortest wafer stretch the whole chart. Horizontal scrolling is used only when the content exceeds the viewport.

## Implementation boundaries

- Mapping choices use ordered row records rather than a Reference-keyed dictionary. Existing dictionary-format WKB remains readable. A newly added draft never enables itself based on its name.
- Reference-only legacy aliases are reconciled on linked restore; Raw choices, comparisons and filters retain their source identity. Literal saved-column equality is required for positional alias recovery. Independent/manual data is not automatically overwritten.
- Shared rendering logic spaces only ordinal display positions. Source strings, row order/identity, all Y values, fit/statistics, participation, classification and static export semantics are unchanged. Cancellation restores original X ordinals; Card redraw and secondary Y axes use the same spacing.
- No packaging, pushing or tags; no writes to original Desktop WKB or `config/settings.yaml`. Tests use conda with isolated settings, recovery, Matplotlib cache and temporary paths.

## Executable behavior and verification

BDD examples link to public workflow tests in:

- `docs/features/shared_reference_mappings.feature` / `tests/test_mapping_row_controls.py`.
- `docs/features/reference_source_columns.feature` / `tests/test_reference_source_columns.py`.
- `docs/features/trend_wafer_labels.feature` / `tests/test_trend_wafer_labels.py`.

103 latest focused regressions passed in 35.900 seconds (`.cache/shared-reference-20261011/related-verified.txt`). The earlier broad run exposed an obsolete alias-title expectation and a fixture too small to overflow at every tested font; the former now expects the explicitly requested original Reference title, and the latter uses 12 uneven wafers with real-font width accounting. No numerical, identity, persistence or existing performance thresholds were relaxed.

All seven isolated Desktop WKB copies passed native Qt acceptance for repeated Reference mapping rows (`desktop-complete.txt`), and separately for original Reference headers/values, same-row identity, scope switches, compact expansion and Save/reopen (`compact-native.txt`). The latter includes the real 7,731-row fixture restricted to 6,958 rows; reference-table and first/last Trend images were captured. Root and child expansion show multiple complete wafer captions in one screen. Caption runs with distinct Lot/PAD identities are intentionally retained rather than merging or reordering source records.

Repeatable native helper: `.cache/shared-reference-20261011/compact_source_acceptance.py`.
Images: `C:/Users/Yuanhao Qin/AppData/Local/Temp/metrology-shared-ref-20261011/acceptance/compact-3289fc7b/`.

The first latest-source full run executed 678 tests in 276.826 seconds; four failures and one error were obsolete Reference-alias/merged-column expectations. These now target the original Reference names or the named Raw column, retaining exact numerical, order, Draw, scope, reopening and latency assertions. See `full-latest.txt`.

Follow-up functional tests found and fixed a stale Copy PNG cache when local spacing changed but the grid size did not. The 19 targeted checks for this case, expansion, classification, column/row updates and the five updated source-name expectations passed in 12.985 seconds (`selector-green.txt`).

Keeping source column names independent also doubled selector columns in the three-parameter fixture. Profiling confirmed whole-grid reconstruction on one parameter toggle (`selector-before.prof`). The existing selector now reuses unaffected rows and columns; disabled cells, exact selections, Draw-required state, labels and reordered-array fallback are retained. A frozen pre-fix package and the current package were measured in separate processes, five trials each, on the same 6,000-row fixture with exact source/box assertions:

- Uncheck median: 305.502 ms before, 80.937 ms after.
- Check median: 324.544 ms before, 110.513 ms after.

Repeatable measurement: `selector_compare.py`, `selector-before-measured.txt`, `selector-after-measured.txt` in `.cache/shared-reference-20261011/`. Existing 0.15-second performance assertions remain unchanged.

Final-source native acceptance passed all seven isolated Desktop copies again (`compact-native-final.txt`). Final first/last images and the Reference table are in `C:/Users/Yuanhao Qin/AppData/Local/Temp/metrology-shared-ref-20261011/acceptance/compact-b16959e8/`; the right endpoint was visually inspected after completion.

Final `python run_tests.py`: **681 tests passed in 276.221 seconds** (`full-final.txt`), including the original timing thresholds, exact source/row identity, undo, conflict/backup/atomic-save and recovery tests. The eight protected files—formal settings and all seven original Desktop WKB—retained their original SHA-256 hashes after all tests.

The earlier non-final run's timing failures and unchanged-code baseline comparisons remain in `full.txt`, `timing-recheck.txt` and `timing-baseline.txt` as diagnostic history, not the final result. No commit, package, tag or push was performed; unrelated user changes remain unmodified.
