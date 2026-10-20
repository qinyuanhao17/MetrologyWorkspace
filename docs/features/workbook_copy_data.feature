Feature: Choose analysis input without stale sources
  Engineers can remove or replace an analysis's input
  without changing the owning Workbook's original measurements.

  # Automation: WorkbookCopyDataTests.test_tem_map_with_copy_checked_follows_repeated_workbook_raw_edits
  # Automation: NamedAnalysisWindowTests.test_named_tem_map_copy_follows_workbook_raw_values
  # Automation: NamedAnalysisWindowTests.test_named_nova_and_kla_maps_follow_workbook_values_after_copy
  Scenario: Map windows keep following Workbook after explicit Copy
    Given a TEM, NOVA or KLA Map window has Copy from WKB enabled
    When Workbook Raw values or column names change repeatedly
    Then the Map data follows the current stage without requiring another Copy or Save
    And Preview and Final retain their own source rows
    And a named window continues following after saving and reopening

  # Automation: WorkbookCopyDataTests.test_old_nova_and_kla_copy_checked_map_follows_raw_not_saved_snapshot
  Scenario: An old Workbook's linked Map does not freeze on its saved snapshot
    Given an old NOVA or KLA Workbook contains a saved Map snapshot or independent-data marker
    And its Map window has Copy from WKB enabled
    When Workbook Raw values change
    Then the Map uses the current stage source rather than the saved Map snapshot
    And an unsaved local Map measurement edit is not overwritten
    And the stored independent Map snapshot is not mutated by refreshing the child

  # Automation: NamedAnalysisWindowTests.test_named_correlation_copy_follows_workbook_raw_values
  Scenario: A named analysis follows Raw Data after copying from Workbook
    Given a new named Correlation and Trend window starts with manual input
    When the engineer enables Copy from WKB and changes Workbook Raw values or column names
    Then the copied Raw table follows repeated Workbook updates without requiring a Save first
    And the copy remains an unsaved draft until explicitly saved

  # Automation: WorkbookCopyDataTests.test_correlation_reference_is_manual_and_raw_copy_does_not_replace_or_clear_it
  Scenario: Reference stays manual while Raw follows Workbook
    Given a newly opened Correlation and Trend window has an empty Ref Data table
    When the engineer enters Reference measurements and enables Copy from WKB for Raw
    Then Workbook updates refresh Raw without replacing the manual Reference measurements
    And disabling or enabling Copy from WKB does not clear or copy Reference
    And the manual Reference and Raw link survive saving and reopening

  # Automation: WorkbookCopyDataTests.test_manual_raw_edits_are_preserved_and_stop_the_copy_link
  Scenario: Local Raw edits cannot be silently overwritten
    Given an analysis follows Workbook Raw Data
    When the engineer edits its copied Raw measurements before another Workbook update
    Then the local measurements remain intact and the copy link becomes unchecked

  # Automation: tests.test_workbook_copy_data.WorkbookCopyDataTests
  Scenario: Raw measurements remain drawable after removing Reference
    Given an analysis compares Reference and Raw measurements for wafer "001"
    When the engineer removes all Reference measurements
    Then Select maps no longer offers Reference measurements
    And the unchanged Raw measurements can still be drawn in Correlation and Trend

  Scenario: Switch an owned analysis to manual input and back
    Given a NOVA Workbook has measurements for wafer "001"
    When the engineer turns off Copy from WKB in an owned analysis
    Then its copied Raw table and drawing choices are empty
    And any manually entered Reference table remains unchanged
    And newly supplied manual measurements can still be drawn
    And turning Copy from WKB back on restores the current Workbook measurements

  Scenario: Cancel replacing manual measurements
    Given an owned analysis contains manually supplied measurements
    When the engineer cancels replacing them with Workbook measurements
    Then the manual measurements and the disabled copy choice remain unchanged

  Scenario: Saved manual mode is not silently replenished
    Given the engineer saved an owned analysis with Copy from WKB turned off
    When the Workbook measurements change and the analysis is reopened
    Then its input stays empty until the engineer explicitly copies or supplies measurements

  Scenario: Full data keeps its own participation choices after changing scope
    Given a saved NOVA Workbook excludes die "002" from Workbook analysis
    And its Full data wafer map also excludes die "002" from its own analysis
    When the engineer reopens the wafer map and switches to Workbook selection and back to Full data
    Then all four original measurements remain in the Full data table
    And only die "002" remains excluded from the wafer map analysis

  Scenario: Save local Raw edits before the Workbook refreshes
    Given a Correlation window is copying Raw from its Workbook
    When the engineer manually edits a Raw cell and immediately saves the Workbook
    Then Copy from WKB is disabled and the literal local Raw value is saved
    And reopening restores that value without changing the parent Raw or manual Ref
    # tests.test_workbook_copy_data.WorkbookCopyDataTests.test_manual_raw_saved_before_parent_refresh_keeps_literal_edits_and_detaches_copy
