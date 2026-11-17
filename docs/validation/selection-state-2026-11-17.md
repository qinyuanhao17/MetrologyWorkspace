# Data Selection / Dynamic / Wafer Map follow-up

The new issues were reproduced using isolated settings and literal synthetic
measurements. No numerical fitting, residual, interpolation or scaling rules
were changed.

1. Keeping only one paired row produces unavailable regression Cards with
   NaN slope/intercept. Offering those coefficients to child windows polluted
   dirty-state comparison and saving with non-finite JSON values. Child
   parameter-card settings now retain only finite coefficients; valid Cards
   still apply and round-trip unchanged. Insufficient fits remain unavailable.
2. A nonempty Workbook exclusion list had been written as a top-level list
   scope, violating the existing WKB state-object contract. It is now an
   object containing `excluded`. Restore accepts the legacy in-memory list
   representation as well. Standalone export uses the same representation.
3. Hide Excluded projected an empty target stage to a header-only grid,
   preventing a first full paste. Empty stages now use the original editable
   source model. The first paste reuses the other stage's saved identity IDs
   when no old positional ID exists, preserving exclusions and view settings.
4. Map Font adds 4–7 point options; native and export lower font clamps follow
   the smaller choice. Existing choices at 8 points and above retain their
   previous appearance. The dense-map (>100 points) label clamp also follows
   the smaller choice, with native/export label-position and thinning parity.

Script protocols are separate: `metrology-group-script` (Group assignments),
`metrology-selection` (participation/filter recipe), `metrology-die-selection`
(selected Die Map points). Parsers reject the other formats before applying
changes. Applying a Group Script preserves the existing Data Selection.

Reference count correction initially passed tests that checked analysis row
counts only. After the user confirmed Correlation/Trend as the main affected
tool, actual clipboard tests exposed a missing transition: a value-only Ref
imported with the wrong extent had no default Raw identity, and ordinary grid
edits did not derive it when the row counts became aligned. Rows refreshed but
the Reference measurement list remained empty, so it did not plot.

Correlation/Trend now derives default identity from the current aligned Raw for
analysis and measurement choices. It never replaces explicitly supplied Ref
identities, reloads the Ref table, changes literal source values or clears Undo.
Tests cover correcting either source, a short or long Ref, appending missing
cells, clearing the extra cell, Undo/Redo and the resulting plotted Trend rows.
Match Workbook's existing count correction with active Data Selection passes.

Commands:

```text
.venv/Scripts/python.exe -X utf8 run_tests.py tests.test_selection_state_regressions -v
Ran 7 tests in 2.718s
OK

.venv/Scripts/python.exe -X utf8 run_tests.py tests.test_selection_state_regressions tests.test_selection_script tests.test_workbook_copy_data tests.test_correlation_source_identity tests.test_workspace_group_parity tests.test_document_storage tests.test_snapshot_equality tests.test_array tests.test_wafer_static -v
Ran 139 tests in 133.724s
OK
```

The related run began with six new tests; the seventh (Match count correction)
was added and passed in the separate seven-test final run. Full-suite results
are recorded separately in the v5.3.2 release validation.

The additional dense-map small-font test failed on the retained 4.5-point
clamp before the fix, then passed after both renderers were updated:

```text
.venv/Scripts/python.exe -X utf8 run_tests.py tests.test_selection_state_regressions tests.test_wafer_static -v
Ran 14 tests in 20.527s
OK
```

This run contains all eight new issue tests and all six static-map tests.

Final count-correction checks:

```text
.venv/Scripts/python.exe -X utf8 run_tests.py tests.test_selection_state_regressions tests.test_correlation_source_identity tests.test_correlation -v
Ran 85 tests in 49.291s
OK

.venv/Scripts/python.exe -X utf8 run_tests.py tests.test_selection_state_regressions -v
Ran 11 tests in 9.569s
OK
```

The 85-test run preceded the extra append/clear and Undo/Redo checks; the
11-test final run includes all of them and actual Trend drawing. The red
clipboard reproduction failed in both correction directions before the fix.
