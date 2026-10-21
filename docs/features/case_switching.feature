Feature: Reuse a Workbook without stale analysis sources
  # All fixtures are synthetic; no customer or company measurements are needed.

  # Automation: CaseSwitchingTests.test_wrong_offset_paste_cut_and_correct_paste_does_not_leave_phantom_rows
  # Automation: CaseSwitchingTests.test_cut_after_offset_paste_restores_extent_on_undo_and_keeps_original_blank_rows
  Scenario: Recover from a paste at the wrong offset
    Given data was accidentally pasted below and to the right of its intended position
    When the entire just-pasted range is cut and data is pasted at the correct position
    Then newly introduced empty tail rows do not inflate the document row count
    And pre-existing blank source rows are preserved
    And Undo and Redo restore both cell contents and document extent

  # Automation: CaseSwitchingTests.test_ordinary_paste_of_different_cases_keeps_open_linked_sources_complete
  # Automation: CaseSwitchingTests.test_same_named_ref_raw_can_analyze_after_an_intermediate_incompatible_case
  # Automation: CaseSwitchingTests.test_failed_child_refresh_is_not_remembered_as_success
  # Automation: WorkbookCopyDataTests.test_map_copy_off_keeps_locked_positions_and_recopy_preserves_them_in_saved_workbook
  Scenario: Overlay successive cases while linked analyses are open
    Given Wafer Map and Correlation and Trend follow the Workbook
    When ordinary paste changes Raw or Reference headers, dimensions or values
    Then mapped Raw columns and their literal measurement strings remain in Wafer Map
    And an unambiguous same-named Raw replacement remains eligible for matching
    And an independent child Reference is not overwritten by Workbook changes
    And ordinary overlay preserves cells outside the pasted range
    And protected Map coordinates survive recopy while unlocked source strings remain exact
    And unsuccessful child refreshes remain eligible for retry

  # Automation: CaseSwitchingTests.test_original_raw_column_uses_its_mapping_card_and_restores_without_changing_literals
  # Automation: CaseSwitchingTests.test_calibrated_stage_reads_original_columns_for_swapped_aliases_and_shared_inputs
  Scenario: Preserve calibration when the mapped Raw column is retained
    When a linked Map applies the Card of a uniquely mapped Raw column
    Then the plotted values use that mapping's fitted coefficients
    And the table retains its original measurement strings
    And saving and restoring the plot options preserves the Card
    And overlapping aliases never calibrate already-calibrated intermediate values

  # Automation: CaseSwitchingTests.test_pasting_raw_identity_into_incomplete_ref_enables_ref_plots
  # Automation: CaseSwitchingTests.test_manual_ref_wafer_selection_draws_mixed_numeric_values_after_identity_paste
  # Automation: CaseSwitchingTests.test_shorter_ref_with_explicit_identity_can_draw_without_a_row_count_gate
  # Automation: CaseSwitchingTests.test_duplicate_ref_headers_do_not_prevent_valid_raw_only_plots
  # Automation: CaseSwitchingTests.test_user_source_column_does_not_block_reference_and_raw_plots
  # Automation: CaseSwitchingTests.test_reference_identity_auto_detection_does_not_reset_an_explicit_empty_group_choice
  Scenario: Draw independently valid Reference and Raw sources
    When Raw Wafer and Die identities are pasted into an incomplete Reference
    Then newly recognized Reference measurements are selectable for drawing
    And invalid numeric cells do not invalidate otherwise usable measurements
    And fewer Reference rows do not block a source with its own identity
    And invalid duplicate headers in one source do not block its valid peer
    And user metadata named Source is preserved without colliding with internal labels
    And automatic recognition does not replace an explicit grouping choice with defaults

  # Automation: CaseSwitchingTests.test_match_fit_equation_and_r_squared_support_selection_and_copy
  # Automation: CaseSwitchingTests.test_floating_raw_has_no_native_transient_owner_and_closes_with_workbook
  Scenario: Inspect plots while editing in the floating Raw window
    Then Match fit equation and R-squared text can be selected and copied
    And the Raw tool has no native Workbook transient owner or system-wide topmost flag
    And closing the Workbook also dismisses its floating Raw editor
