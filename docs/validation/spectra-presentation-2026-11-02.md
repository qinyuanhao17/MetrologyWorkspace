# Spectra menu dividers, wafer captions and uniform Mueller ticks

The user's final presentation corrections are applied without altering source spectra, calculations or wavelength ranges:

- Tree menu: visible separators follow Uncheck All Spectra, Uncheck Selected and Clear BSL. Unfold Tree and Delete Tree share the final group. A selector scoped to this menu paints the separators with the theme palette's mid color; other menus are unchanged.
- Wafer Die labels: a TextItem child offset places the text frame 8 logical pixels below each point center and removes the text document's internal margin. The offset is maintained by PyQtGraph's screen-aligned TextItem transform, rather than moving labels by a diameter-dependent number of millimetres. Point coordinates, selection geometry, numeric labels and collision priority are unchanged.
- Mueller X axis: the previous `max_labels=2` independently retained the first and last label at every tick level. Combining a pair of major labels with a pair of minor labels produced sequences such as 200, 300, 800. Compact panels now label every native major tick and suppress minor-level text (`maxTextLevel=0`). Native spacing still adapts to view range and width; minor grid lines and tight X limits remain.

## Verification

Focused command: `python run_tests.py tests.test_spectra_analysis tests.test_spectra_viewer tests.test_spectra_map tests.test_sme_spectra -v`: **89 passed**, 25.672 seconds.

The menu workflow checks separator positions through QAction entries. Full-range and zoomed Mueller tick tests check that all major labels are present and evenly spaced. Wafer label tests render both 100 mm and 300 mm maps and verify the same 8-pixel offset in scene coordinates. Existing mouse rectangle, blank click, multi-selection, original/residual/3σ, cache, source identity and source-array checks still pass.

The ten-real-file GRR probe passed again: `spectra-presentation-grr10-2026-11-02.json`. It independently checks residual/3σ values, clears BSL, restores legend visibility, and uses a real mouse drag to select all ten mapped spectra and linked tree/curve entries without zoom. Source hashes remain unchanged.

Images inspected: `qa_spectra_tree_menu.png` confirms the three divider positions and no line before Delete Tree; `qa_spectra_3sigma_grr10.png` confirms uniformly spaced Mueller labels; `qa_spectra_map_box_grr10.png` confirms closer captions and selected points. The map probe uses a 1500×900 window so the full map is visible in offscreen Qt.

Broad regression is recorded separately in `spectra-presentation-regression-2026-11-02.json`, excluding the same AutoWeighting-related modules as earlier runs. Focused success is distinct from repository-wide status.

The final broad run completed **1,320 tests** (678 + 642), with one failure and two errors previously present in baseline runs: the Correlation pagination pending-state assertion, a fake Correlation workspace missing `raw_model`, and pandas read-only literal-frame assignment. All Spectra tests passed. Unrelated code was not changed. Syntax parsing and `git diff --check` passed; `config/settings.yaml` remains unmodified.
