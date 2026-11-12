# Correlation and Trend — optional Groups and Plot Labels

## Behavior

- New Groups menu: Enable Groups, Use WKB Group settings, Group settings, and Plot labels.
- Independent windows use the existing GroupControls and GroupPlan. The modeless dialog supports editable TestFlag, Head names, Marks and Trend/Group order. Only Apply commits pending classification into plots; unequal nonempty Ref/Raw row counts produce a message.
- Enable Groups switches Group captions/order on and off without changing source tables or Data selection. Disabling it keeps classification available for re-enabling. This presentation switch updates Trend, without resubmitting Correlation fits.
- A Workbook child follows its parent's Group settings by default, preserving earlier linked-window behavior. Disable Use WKB Group settings to edit a copied local configuration. Re-enabling uses the current parent configuration; parent state is never edited by the child.
- Plot labels has a master switch, optional WKB following and separate PAD/Lot choices. Editing an individual local choice detaches label following. Changes update existing Trend axes; curves and zoom remain intact. Group names and primary Wafer identities are retained, consistent with Workbook caption semantics.
- Independent snapshots and managed Workbook drafts save switches, local grouping, TestFlags and caption choices. Saved inherited caption values also remain available when opening a detached snapshot.
- Group configuration is tied to source record identities. A same-count replacement with different identities detaches classification and requires reviewing flags and Apply; flags are not inferred from equal row counts.

## Implementation

`correlation_options.py` owns the menu/dialog and saved local preferences. It reuses GroupControls, GroupPlan and SequencePage.set_identity_labels. CorrelationWindow keeps the prepared Workbook Group-plan fast path, adds option persistence, and bypasses grouped Trend layout only when requested. MatchingWindow routes Trend caption offers through the child's optional following policy; Wafer Map and Radius label handling is unchanged.

No calculations, Card fitting rules, source strings or measurement identities were changed. Existing temporary-empty-parent retention remains in place. No tags or release assets were updated for this feature.

## Validation

- Five new public-workflow tests pass, including local heads, master switches, plot object/range retention, detached/standalone snapshot restore, actual `.mwkb` save/load, parent isolation, view-only dialog inspection and source identity protection.
- The affected Correlation/source-order/named-window/recovery set passed 101 tests in 74.640 s. The final UI adjustments were separately rechecked with all five new tests (1.394 s).
- Actual `JC1913/matching-analysis.mwkb` Raw Data: 1,890 rows; local two-head classification applied successfully. A synthetic row-aligned Reference was used only for this UI probe. Group disabling retained all included rows; caption switching retained plot objects and ranges; Raw strings and original WKB SHA-256 stayed unchanged.
- Native settings and Group Trend screenshots under `.cache/correlation-group-options-validation/` were inspected. Probe: `.cache/verify_correlation_group_options.py`; the source workbook and personal settings were not changed.
- Final full regression: **1,453 tests passed in 952.742 s**, across 120 modules, exit code 0. Scratch settings and ordinary Windows TEMP were used throughout. The explicitly deferred `test_auto_weighting`, `test_auto_weighting_ocr` and `test_auto_weighting_window` modules remain excluded. No failures or errors remain.
- Machine-readable results: [correlation-group-options-2026-11-11.json](correlation-group-options-2026-11-11.json). Full log: `.cache/correlation-group-options-validation/full.log`. No release/tag/branch updates were performed.
