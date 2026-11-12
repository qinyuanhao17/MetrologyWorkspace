# Spectra Viewer Groups, Marks and resizable legends

Date: 2026-11-12. Local development only, no publication. Full-suite testing
remains deferred by the user; AutoWeighting was not run.

## Delivered behavior

- Groups offers a presentation switch, one-time Copy WKB Groups, and local Group
  settings reusing GroupControls/GroupPlan. Only applied Workbook classification
  is copied. Trend ordering and calibration controls are not exposed in Spectra
  settings: source, Spectra Info and spectral analysis ordering are unchanged.
- Copy pairs Wafer ID/Lot ID/PAD/Die, canonicalizing numeric Die spelling and
  ignoring filename/path. Same-identity conflicting classifications reject the
  operation atomically. Missing identities are reported and remain unassigned.
- The local draft keeps named Head/Mark definitions and per-spectrum identity,
  Mark and Group TestFlag records. **Superseded by the latest user correction:**
  live Group flags now share Spectra Info's authoritative Test Flags; applying
  Group flags or explicitly copying WKB Groups updates them. Participation stays
  independent. See the interaction validation below for the updated contract.
- Tree context menu Set Mark offers existing Marks and Add Mark. A newly
  configured local classification uses the first Mark as fallback, as WKB does.
  Mark is appended as `Wafer ID | Mark` and prepended as `Mark | legend`.
  Multiple Marks on one wafer are listed; a partially copied wafer reports
  Unassigned alongside its known Marks rather than assigning a false fallback.
- Die Map titles and point tooltips carry Group labels, including copied combined
  group names where applicable. Updates retain scatter widgets, coordinates and
  flag/check state. Tree expansion paths retain original identity text.
- Classification changes update captions in place, preserving curve objects,
  color keys, selected spectra, hidden channels and axes. Mark edits use the
  existing shared Undo/Redo history. The master switch hides presentation only.
- Legend widths remain draggable. Fixed legend heights are removed and a new
  vertical splitter separates legends from plots. Double-click restores default
  proportions. Its saved splitter entry is appended, preserving old index order.
- Classification and legend proportions persist through .spec and standard WKB
  child drafts. Old files default to no classification captions; malformed new
  drafts are rejected before replacing current sources.

## Verification

Red/green checks first failed for the absent group module/Mark menu, unbound WKB
copy source, missing persistence and invalid draft validation. An existing exact
tree-menu expectation was updated to include the requested Set Mark entry.

- Broad related run: **117 tests passed in 40.424 seconds** across
  `tests.test_spectra_groups`, `tests.test_spectra_viewer`,
  `tests.test_spectra_workbook`, `tests.test_spectra_map`,
  `tests.test_spectra_info_edits`.
- After adding strict malformed-draft checks: **26 Group/storage tests passed in
  12.229 seconds** (`tests.test_spectra_groups`, `tests.test_spectra_workbook`).
- Final Group settings presentation check: **5 tests passed in 1.402 seconds**.
  All runs used scratch settings. These are focused runs, not a full regression.

The actual JC1913 Workbook's **1,890** saved SME metadata identities all matched
its Raw Data for copying; filename paths differ and do not enter matching. The
source's Head and Mark grouping switches are disabled, and that disabled
classification is preserved during the copy. A UI probe then loads **three real
original SME files**, assigns New locally and verifies the tree, legend prefix,
map caption/tooltip, unchanged curves/colors/ranges/checks/Spectra Info flags,
legend resizing, and .spec save/restore. Rendered screenshots were inspected.
The Workbook and all three original SME hashes remain unchanged.

The final real-file harness uses a Windows multiprocessing main guard, unique
scratch save paths and explicit widget cleanup; it exited successfully. Earlier
diagnostic harness attempts were stopped and were not counted as acceptance.

BDD scenarios in `docs/features/spectra_viewer.feature` map to the executable
tests in `tests/test_spectra_groups.py`. Machine evidence:
[spectra-groups-2026-11-12.json](spectra-groups-2026-11-12.json).
Local logs/probe/screenshots: `.cache/spectra-groups-*.log`,
`.cache/validate_spectra_groups.py`, `.cache/spectra-groups-validation/`.
Production `config/settings.yaml` has no worktree modification.

Follow-up UI, shared flags, composite Marks, Highlight and U acceptance:
[spectra-group-interactions-2026-11-12.md](spectra-group-interactions-2026-11-12.md).
