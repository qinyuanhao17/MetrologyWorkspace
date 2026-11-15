# Group Script, shared spectrum menus and color categories

Date: 2026-11-13. Current working tree, including earlier uncommitted work.

## Implemented behavior

- Group settings in the shared GroupControls editor offer Group Script with
  Copy, Paste from Clipboard and Apply Script. Versioned JSON carries Head,
  Mark, combined Group and display definitions plus TestFlag/Mark assignments.
  Wafer / Lot / PAD / canonical Die identities map assignments across reordered
  tables. Missing target identities, conflicting duplicates and malformed
  scripts fail before changing the draft. Wafer and Die are required; missing
  Lot/PAD columns represent empty identity values. Apply Script edits the draft;
  the existing Group Apply accepts it. Participation and measurements are kept.
- Spectra Viewer and its Die Map build the same context menu, including checks,
  flags, Marks, Highlight, BSL, tree operations, export and similar-wafer actions.
  Map unselected actions retain the clicked Wafer/Lot/PAD scope. The tree uses
  all unselected sources and enables similar-wafer actions for one selected
  measurement set. Read-only out-of-range maps retain their existing menu.
- After selecting map points, typing a configured integer assigns their shared
  TestFlag after Enter or a 700 ms pause. Signed and multiple-digit flags work;
  unconfigured numbers do not change assignments or the configured flag list.
  Changing selection or moving focus cancels pending input. Other controls
  keep their normal keyboard input. Edits use the existing Undo/Redo history.
- Color By adds Folder and TestFlag. Full source-parent paths distinguish
  folders, and an absent assignment belongs to TestFlag 0. Each category/channel
  has a shared color and explicit legend label. Flag edits and Undo refresh
  main/floating plots; document snapshots retain both modes. Original samples
  and existing per-Wafer/channel 3-sigma calculations are retained.
- Group Script text uses the existing readable editor styles for both themes.

## Verification

Interpreter: `C:/Users/Yuanhao Qin/.conda/envs/metrology-workspace/python.exe`.
All test runs used `run_tests.py`, which isolates settings and recovery paths.
The shell's `python` alias points to an inaccessible Windows Store launcher.

The new behavior tests first failed for missing Group Script controls, missing
menu actions and missing color modes. Further regressions cover changing Mark
definitions, identity reordering, combined Groups, atomic rejection, draft-only
application, flag-only pending state, actual point clicks, multiple-digit and
negative flags, invalid prefixes, delayed input, Undo, numerical preservation,
floating plots and document restoration.

Final focused command:

```text
python run_tests.py tests.test_group_script tests.test_spectra_group_interactions tests.test_spectra_groups tests.test_spectra_map tests.test_spectra_viewer tests.test_spectra_workbook tests.test_workspace_group_parity tests.test_core.PlotTests.test_axes_colorbar_constant_and_rotation tests.test_matching_window.MatchingWindowTests.test_analysis_results_share_the_scrollable_setup_workspace tests.test_radius.RadiusTests.test_real_data_draws_selected_parameters -v
```

Result: **137 tests passed in 92.448 seconds**.
Log: `.cache/group-script-final-focused-20261113.log`.

Full working-tree command: `python run_tests.py`.
Result: **1,535 tests in 1,196.307 seconds; 5 failures and 2 errors**.
This run included AutoWeighting/OCR and the earlier workspace changes.
Log: `.cache/group-script-full-20261113.log`.

The full run started before the assertion corrections below and the final
flag-only draft regression were added. The final focused run covers these
subsequent changes; the entire suite was not rerun after them.

Full-run issue disposition:

| Check | Follow-up result |
| --- | --- |
| Core map title expected no Sigma | Updated the old assertion to include Sigma; final focused run passed. |
| Match Workbook menu omitted Data | Updated the old menu assertion; final focused run passed. |
| Radius title expected a PAD prefix | Updated the assertion to the existing compact Wafer/Lot/PAD format; final focused run passed. |
| Original-order plot label switches | Updated initial caption expectations; a later assertion still fails because hiding PAD/Lot does not remove them from existing Wafer/Radius captions. Outstanding. |
| Wafer child opening budget | Full run: 0.896 s against a 0.4 s limit. Isolated recheck outside the sandbox: 0.858 s. Outstanding. |
| Spectra long-path export | Sandbox test fixture failed creating its original file before export. The unmodified test passed outside the sandbox. |
| Storage same-file alias protection | Sandbox denied creating a temporary hardlink. The unmodified test passed outside the sandbox. |

Platform recheck log: `.cache/group-script-platform-recheck-20261113.log`.
The two outstanding regressions are retained as failures, with their assertions
and timing limit intact. Compact caption generation in
`CorrelationOptions.decorate_wafer_selection()` supplies flat strings, while
`measurement_caption()` recognizes typed metadata lines; this explains the
remaining label-switch failure.

`git diff --check` passed. `config/settings.yaml` SHA-256 was unchanged:
`DBC30E7CA71B7E8375C7511F264E0B24DB568FFF965CEC4D635CC0997073C01C`.

Offscreen UI previews were inspected after explicitly registering system fonts
in the preview process; its default font database was empty. Preview files are
under `.cache/qa-group-script-20261113.png` and
`.cache/qa-group-testflag-color-20261113.png`.
