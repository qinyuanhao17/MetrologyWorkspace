# Groups Data selection and Wafer Map point precision

## Scope

- Keep Match Workbook Groups → Data selection when switching Preview/Final,
  including the first paste into an empty stage and a temporarily cleared stage.
- Add Decimals after Opacity on the Wafer Map appearance row. Default 2;
  supported range 0–10. Only point-value labels are rounded, not source data,
  interpolation, color limits, statistics or hover values.
- Preserve this presentation choice in workspace files; older saved controls
  without this field use 2. PNG/copy/report export use the current choice even
  before the overlay timer fires or while Select maps is visible.

## Reproduction and cause

`run_tests.py tests.test_stage_selection_and_point_precision.StageSelectionAndPointPrecisionTests.test_loading_final_after_preview_selection_keeps_shared_participation -v`

Before the fix, Preview excluded W2 (three of six records). Pasting the same
identities into initially empty Final cleared all three exclusion IDs in both
draft and applied state, before analysis or cache reuse. Final and then Preview
included all six records. Existing-stage tab switches without replacement did
not reproduce this failure.

`_sync_selection_to_raw` derived its identity lookup solely from the previous
active-stage table. An empty Final table supplied no records, so every incoming
record received a new participation ID and the exclusions were pruned. It now
retains matching IDs from the persisted selection too. An empty stage does not
replace the shared participation state. Existing source identity/order guards
remain in place; different records are not made equivalent by row count.

## Verification

- New isolated regression module: 14 tests passed, including restored Head/Mark
  selections, source-value preservation, no reinterpolation, workspace roundtrip,
  legacy defaults, immediate PNG/copy/report export, and a hidden map canvas.
- Existing minimum-window toolbar test passed at 1180 × 760. Offscreen visual QA
  confirmed Decimals follows Opacity and the point labels show two decimal places.
- Full suite: `.venv\Scripts\python.exe -X utf8 run_tests.py`, final log
  `.cache/stage-selection-precision-full-final.log`: **891 tests, 886 passed,
  5 failed, 0 errors**, 743.790 seconds. All five failures were timing assertions;
  this is not a fully green suite. All 14 new regressions passed in this run too.
- The five failing tests were rerun together without changing code or thresholds:
  **5 tests, 3 passed, 2 failed**, 17.851 seconds. Log:
  `.cache/stage-selection-precision-performance-recheck.log`. A passing recheck
  does not supersede the full-suite failure or establish stable performance.

| Timing check | Full run | Required | Isolated recheck |
| --- | ---: | ---: | --- |
| Correlation check/uncheck | 0.154283 s | < 0.150 s | Passed |
| Clear selected Raw cells | 0.605269 s | < 0.600 s | Passed |
| Restore saved grouped Correlation | 2.501491 s | < 2.000 s | Passed |
| Open Wafer Map with current Cards | 0.414609 s | < 0.400 s | Failed: 0.421941 s |
| Warm Preview/Final switch / Apply | 0.269814 s | < 0.250 s | Failed: 0.261163 s |

- No tests were removed and no performance limits were relaxed. Performance
  limits remain unresolved; no new performance improvement is claimed here.
- All tests run through `run_tests.py` and scratch settings. User settings were
  unchanged before and after the final full run and isolated recheck (SHA-256
  `F48EBA97501F1612FECBFA5611755C94F2259FE46F67A5222C482464FF9653E1`).

The earlier full run was interrupted after adding the Select maps export edge
case, so that the final run tests the final implementation and all 14 regressions.
No tag, branch, release or installer is created or updated for this request.
