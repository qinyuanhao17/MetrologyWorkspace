Feature: Recognize editable Reference and Raw identities without replacing data
  Wafer grouping controls choose which measurements to plot.
  They do not rewrite either editable source table.

  # Automation: WorkbookCopyDataTests.test_parent_cut_keeps_linked_correlation_until_raw_is_replaced
  # Automation: LinkedCorrelationValueTests.test_parent_cut_preserves_selection_then_large_replacement_resumes_link
  Scenario: Retain linked Correlation while Workbook Raw Data is temporarily empty
    Given Correlation follows Raw Data from the Match Workbook
    And the engineer has chosen Wafers and Parameters and drawn the analysis
    When the engineer cuts all Raw Data in the Match Workbook
    Then Correlation retains its last data, Wafers, Parameters and draw choices
    And its manual Reference remains unchanged
    When the engineer pastes replacement Raw Data in the Match Workbook
    Then Correlation follows the new measurements with its surviving choices
    And undoing the replacement retains that data until the source is restored

  # Automation: CorrelationSourceIdentityTests.test_pasting_cells_into_initially_blank_ref_enables_wafer_menu
  # Automation: CorrelationSourceIdentityTests.test_ref_only_edits_refresh_wafer_recognition_and_grouping_menu
  # Automation: CorrelationSourceIdentityTests.test_ref_only_measurements_can_draw_both_analysis_pages
  Scenario: Recognize Reference without requiring Raw measurements
    Given Ref Data is initially blank and Raw Data is empty
    When the engineer pastes Reference headers and measurements
    Then the Wafer grouping menu offers the current Reference metadata columns
    And editing Reference headers updates those choices automatically
    And Reference measurements can be drawn without requiring Raw measurements

  # Automation: CorrelationSourceIdentityTests.test_ref_header_and_literal_edits_can_be_undone_after_grouping_changes
  # Automation: CorrelationSourceIdentityTests.test_raw_identity_edits_survive_recognition_and_wafer_check_changes
  Scenario: Grouping is read-only for source measurements
    Given Reference or Raw identities and literal measurement strings were edited
    When the engineer changes grouping columns or checks a Wafer
    Then the edited table remains unchanged
    And its edits can still be undone and redone

  # Automation: CorrelationSourceIdentityTests.test_linked_raw_refresh_and_reopen_preserve_manual_ref_identity
  # Automation: CorrelationSourceIdentityTests.test_imported_ref_identity_is_not_replaced_by_existing_or_later_raw
  Scenario: Raw updates do not own manually supplied Reference identities
    Given Ref Data contains manually supplied Wafer and Die identities
    When Raw Data is loaded or follows Workbook changes
    Then the Reference identities, headers and measurements remain intact
    And they remain intact after saving and reopening the Workbook

  # Automation: CorrelationSourceIdentityTests.test_ref_and_raw_grouping_menus_remain_open_after_repeated_check_changes
  Scenario: Select multiple grouping fields in either source
    Given Reference and Raw Data each have metadata fields
    When the engineer checks several fields in either Wafer grouping menu
    Then that menu remains open and each field keeps its chosen state
