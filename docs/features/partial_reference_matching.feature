Feature: Match a partially populated Reference without discarding Raw measurements
  Reference and Raw measurements correspond by original row position.
  Missing Reference values do not make the later measurements move upward.

  # Automation: PartialReferenceMatchingTests.test_partial_reference_matches_only_finite_original_row_pairs_in_every_mode
  # Automation: PartialReferenceMatchingTests.test_partial_reference_does_not_block_run_or_compact_empty_rows_in_workbook_ui
  Scenario: Run Preview or Final with fewer Reference rows
    Given TEM, NOVA or KLA has fewer Reference rows than Raw rows
    And Reference also contains an empty interior measurement
    When the engineer runs matching
    Then only finite Reference and Raw pairs at the same source positions fit the Card
    And all Raw rows remain available in their original order
    And missing Reference pairs produce no Bias value
    And the original Reference strings and shorter row count remain unchanged

  # Automation: PartialReferenceMatchingTests.test_editing_blank_reference_cells_and_undo_preserve_original_pair_positions
  Scenario: Clear or undo Reference measurements without moving later pairs
    Given Head and Mark grouping are disabled
    When the engineer clears an interior Reference cell and then undoes the edit
    Then each step retains the original Reference row positions
    And matching uses the correctly corresponding Raw measurements

  # Automation: PartialReferenceMatchingTests.test_reference_filters_and_head_groups_keep_the_complete_raw_row_space
  # Automation: PartialReferenceMatchingTests.test_partial_reference_keeps_selected_raw_row_scope_in_copied_child
  Scenario: Keep classifications and participation with a partial Reference
    Given a Workbook has a partial Reference and Raw-based Head classifications
    When the engineer filters Reference values or selects Raw records
    Then fitted pairs and copied Raw measurements retain their original source positions

  # Automation: PartialReferenceMatchingTests.test_partial_reference_survives_wkb_reopen_and_existing_analysis_windows
  # Automation: ExcelExportTests.test_partial_reference_export_keeps_raw_rows_and_missing_pair_gaps
  Scenario: Preserve partial Reference through persistence and reports
    When the engineer saves and reopens the Workbook or exports its Match results
    Then Reference gaps and unmatched Raw rows remain intact
    And saved Correlation and Map windows can still open
