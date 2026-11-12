# Mueller labels and SME export root — 2026-11-04

## Behavior

Mueller plot titles now use one-based labels, M11–M44, in row-major order.
Enlarged plot titles inherit the same labels, including existing Residual/3σ
suffix behavior. Internal metric keys remain M00–M33, so measured values,
matrix element mapping, saved plot ranges and old WKB/`.spec` files keep their
existing meaning. No matrix values were changed or transposed.

Checked-SME exports omit the common source root instead of including its
basename. For example, `JC1913/AIE0058.15/.../measured.sme` exports as
`<destination>/AIE0058.15/.../measured.sme`. Internal folder structure remains
intact. Export still copies existing file bytes only, keeps retry/skip/cancel
behavior, refuses overwrites and rolls back files created by a cancelled run.

## Validation

- The changed display and export expectations were observed failing before
  the production change. Existing acceptance checks now inspect all 16 plot
  captions, an enlarged plot caption, destination paths, byte preservation,
  collisions and cancellation.
- The initial 110-test focused run had one fixture-length failure: removing
  the root shortened a long-path destination to 259 characters. The fixture's
  destination was lengthened to preserve the existing greater-than-260 test
  case. All three export tests then passed, including copying and loading back
  long paths. The other 109 focused tests had already passed.
- A native Windows probe copied three existing SME files from separate
  JC1913 subfolders. Output paths exactly matched paths relative to JC1913,
  with no additional JC1913 directory. Every copied SHA-256 matched its
  original, original SHA-256 hashes stayed unchanged, and all three output
  spectra loaded back without issues.
- All 16 captions and the enlarged M11 plot title were checked on those real
  files. The native grid screenshot was visually inspected.
- Full non-deferred repository regression passed: **1,424 tests, 530.586 s,
  zero failures/errors/skips**, through the isolated `run_tests.py` runner in
  the normal Windows temporary directory. This includes the pending Spectra
  Info live-refresh change. AutoWeighting remains excluded by user request
  (`test_auto_weighting`, `test_auto_weighting_ocr`,
  `test_auto_weighting_window`). `git diff --check` passed.

Probe and logs: `.cache/verify_mueller_export_real.py`,
`.cache/mueller-export-focused.log`, `.cache/mueller-export-paths.log` and
`.cache/mueller-export-tests/`. Acceptance examples are in
`docs/features/spectra_viewer.feature`.
