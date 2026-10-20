# Dynamic comparison, plot readouts and MWKB, 2026-10-20

## User-visible changes

- Dynamic Trend has Single Die and All Dies views. All Dies overlays every
  Die for each selected parameter. Single Die retains its independent picker
  and adds/removes other selected parameters with Add Compare. Every added
  curve follows that panel's Die, not the other parameter panel's picker.
- Dynamic parameter sections no longer show Restore. Existing Data-sheet
  Undo/Redo and their source-cell mappings remain intact.
- Dynamic/Correlation Trend and matching Trend/Bias Y ticks no longer use
  automatic SI multipliers. Matplotlib export uses plain, offset-free Y ticks.
- Statistics is optional: Mean, sample standard deviation (n−1), Min and Max
  for each curve's finite observations. One observation has undefined sample
  sigma, shown as N/A. Matching summaries use full selected observations, not
  the display sample. Captions sit below titles, outside the data frame, and
  do not replace the top frame axis or overlap the matching legend.
- Trend, Bias and matching points have per-observation Die and plotted X/Y
  hover details. Fit/reference lines are not measurement observations.
- Wafer boundaries use the Group boundary's 2-pixel black dashed style;
  matching Group/Wafer caption strips also use the same 2-pixel thickness.
  Dark matching plots retain the same 4-pixel contrast halo as Group edges.
- New Match documents use `.mwkb`. Old `.wkb` remains readable. Open/drag/drop
  recognizes `.bak` and routes by the saved manifest. Saving a backup requires
  a formal target; `.bak`/`.lock`/`.tmp` remain forbidden save targets. The
  original legacy file and backup are not renamed or overwritten by migration.

Source measurement strings, identity fields, original row mappings, missing
value gaps, numerical fits and source ownership are unchanged. No application
version/tag, GitHub branch, Release or installed binary is changed by this task.

## Reproductions and verification

The initial four requested-control tests failed in 0.400 s: Restore was still
visible, the open filter omitted backups, `.bak` reached the table importer,
and Match's canonical extension was still `.wkb`. The filter and routing fix
made those four pass. Legacy fixtures for newly saved Match files now use
`.mwkb`; explicit old-extension compatibility tests remain.

The all-data-excluded regression was reproduced with
`tests.test_matching_window.MatchingWindowTests.test_data_selection_applies_to_correlation_without_head_groups_and_can_exclude_every_row`.
The new hover decorator rejected a legitimately empty curve, interrupting
refresh before children received the empty selection. Accepting empty curves
and skipping absent point arrays made that unchanged test pass.

Two stronger boundary checks then caught derived Row Number coordinates being
misreported as Die metadata and equal-value Dynamic restores keeping the old
displayed mode. Row Number hover metadata is now N/A, without changing its X
coordinates. Dynamic restore rebuilds once after all saved presentation
controls and comparisons are restored; equal source values still use the
value-only path for ordinary edits. Both red tests pass after these fixes.

The installer payload guard also rejects `.mwkb` user documents (including
uppercase suffixes), preserving the existing `.wkb` privacy guard. No installer
was built; packaging tests use a small mock compiler artifact in a temp folder.

Latest development checks:

- 161 tests covering Correlation, Dynamic readouts, named windows, storage,
  mapping controls, labels and incomplete workbooks passed in 120.913 s.
- The final 49 focused checks passed in 16.484 s.
- The initial 10 requested-control tests passed in 1.448 s, including the actual
  ScatterPlot hover-event path, plain export axes, comparison removal, missing
  gaps, source text preservation and Dynamic state round-trip.
- After the boundary corrections, 70 related tests passed in 36.711 s; the
  final 11 requested-control plus 2 packaging tests passed in 1.833 s.
- Isolated offscreen visual review used the application's registered Windows
  fonts. It checked Single Die comparisons, All Dies and PNG export, plus
  matching Trend/Bias statistics and legend/header separation. Review harness
  and images are under `.cache/verify_requested_plots.py` and `.cache/*review.png`;
  they are diagnostics, not release payloads.

The first full isolated run passed 875 of 876 tests in 702.341 s, with no
errors or functional failures. Its only failure was saved grouped-Correlation
restoration at 2.357786 s against the unchanged 2.0 s gate. Log:
`.cache/requested-plots-full-tests.log`.

The final full isolated command is
`.venv/Scripts/python.exe -X utf8 run_tests.py`; the final source is frozen
during this rerun, including the boundary corrections above. Result:
**877 tests in 706.709 s: 875 passed, 2 failed, 0 errors**. The runner exited 1;
this is not an entirely passing suite. Both failures are elapsed-time checks,
not functional assertions:

| Test | Observed | Unchanged gate |
| --- | ---: | ---: |
| `test_correlation_checkbox_changes_keep_exact_sources_and_are_prompt` | 150.368700 ms (slowest change) | <150 ms |
| `test_saved_correlation_restores_complete_grouped_plots_promptly` | 2358.566700 ms | <2000 ms |

All 11 requested-control tests passed. Correlation checkbox measurements were
89.899800, 88.190500, 96.423600 and 150.368700 ms. The earlier full run's
checkbox check passed, but its final-run failure remains reported; there was
no retry-to-green or threshold adjustment. Grouped-Correlation restoration
exceeded its gate in both full runs. Log:
`.cache/requested-plots-full-tests-final.log`. No tests were removed. Changes
to existing performance fixtures are only the new canonical filename suffix,
not assertions, data sizes, timing budgets or expected numerical values.

The user's `config/settings.yaml` SHA-256 remains
`780edd52717da4ed1906708647775b37032a5b7c411c51353776632ffe135f10`.
