# Die Map PAD outlines — 2026-11-09

PADs and measured points have independent origins. Points keep their original
absolute X/Y in mm. PAD Field (0,0) has its lower-left corner at (0,0);
Field (c,r) starts at (c × width, r × height).

Width and height use only three reference points and are rounded once to two
decimal places in mm before reuse across all cells. Prefer (0,0), (1,0), (0,1).
When those samples are absent, choose the reference closest to Field origin
with same-row and same-column neighbours; divide coordinate differences by
Field intervals. Equidistant neighbours prefer the positive direction. Repeated
spectra at one Field share a cell and the first loaded coordinate is used.
No fitting across the remaining points is performed. Missing reference triples
or non-positive dimensions produce an explanatory title tooltip without PADs.

The final user correction requires a complete grid, not individual rectangles
beside measured points. Horizontal/vertical lines at integer multiples of the
common height/width fill the entire wafer, including unmeasured cells. Each
line is analytically clipped to the circle using its chord endpoints. Every
shared border is drawn once. The ordinary rectangular axis background grid is
hidden whenever a PAD grid is available, avoiding lines outside the wafer.
Light gray grid lines are below measurement points and use one non-interactive
graphics item per wafer.
Check, selection and flag changes retain that item and its coordinate buffers.
No source SME, stored coordinates or WKB data are modified.

The pure geometry lives in `spectra_pad_geometry.py`, separate from map UI
orchestration. Four geometry tests cover origin separation, shared edges,
sparse/negative Fields, two-decimal rounding, three-reference-only dimensions
and missing-reference handling. The Qt acceptance check covers layering,
point preservation and buffer reuse. All 19 focused geometry/map tests passed.

The supplied AIE0058.00-23 in JC1913/matching-analysis.mwkb lacks the standard
reference triple. Its available same-row/column references yield **24.17 ×
28.53 mm**. A real-file probe verified that all plotted absolute coordinates
are unchanged and inspected the resulting grid. Probe/logs/screenshots are
under `.cache/pad-validation/` and `.cache/verify_pad_real.py`.

Full regression: 1,433 tests in 1,144.824 s, 1,431 passed and two failed.
The three explicitly deferred AutoWeighting modules were excluded.
`test_wafer_window_opens_with_current_cards_and_uses_new_coefficients_after_edit`
exceeded its 0.4 s opening budget (0.437 s in the complete run; 0.532 s in an
isolated recheck). `test_die_map_sets_flags_without_replacing_maps_or_changing_checks`
observed different aspect-locked view ranges before/after Qt layout settled in
the complete run; the same test passed in isolation. No claim of a completely
green suite or a baseline comparison is made. All added PAD acceptance checks
passed in both focused and complete runs. Existing unrelated work was preserved.

After the full-wafer-grid correction, 103 geometry/map/info/viewer tests passed
in 27.080 s. After suppressing the rectangular background grid, the final 31
geometry/map/info tests passed in 5.632 s and the real wafer was rendered and
visually inspected again. Endpoints are tested to lie on the wafer circle,
and grid lines include negative and unmeasured Fields. The flag test now
captures the initially rendered aspect-locked view before taking its baseline,
rather than comparing pre-layout ranges with post-render ranges. No product
axis limits are relaxed by that test correction. The full repository suite
was not repeated after this follow-up; the earlier full-run results above
remain distinct from these focused results.
