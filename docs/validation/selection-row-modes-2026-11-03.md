# Data selection row modes — 2026-11-03

Reported behavior: spectra manually unchecked in the tree were missing from
Data selection's Unchecked rows view. The latest participation state was
correctly loaded, but both participation views also applied retained filter
conditions, hiding records outside those conditions.

The shared dialog now applies filter conditions only in Filtered rows. Checked
rows and Unchecked rows show current participation across source records; the
search box still refines every mode. Filters, AND/OR connectors, script contents,
source rows and Hide excluded settings remain intact when switching modes.

The regression scenario first saves a filter for W1, manually unchecks a W2
spectrum, then opens Data selection and checks all four row modes and Apply.
It failed before the fix: Checked rows showed only W1, omitting checked W2.
After the fix, it and the shared dialog bulk-edit/script scenario pass.

Focused command:
`python run_tests.py tests.test_selection_script tests.test_spectra_workbook tests.test_participation_bulk tests.test_matching_window.MatchingWindowTests.test_data_selection_filters_sort_click_range_and_cancel_are_view_only tests.test_matching_window.MatchingWindowTests.test_data_selection_adds_and_connects_filter_rows_with_and_or -v`

All 37 tests passed in 9.672 seconds. No full regression was run, as explicitly
requested by the user. AutoWeighting remains deferred and was not tested.

Real-file validation used 20 original UVSE SME files, retained a Die filter,
and manually unchecked a different Die in the Spectra tree. The dialog showed
20 All rows, 1 Filtered row, 19 Checked rows and 1 Unchecked row; Apply retained
the manual uncheck and the saved filter. All 20 source SHA-256 hashes were
unchanged. Logs, scratch probe and machine-readable results are under
`.cache/selection-row-modes-*`; validation used isolated settings and temp paths.
