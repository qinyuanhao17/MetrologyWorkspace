Feature: Choose analysis input without stale sources
  Engineers can remove or replace an analysis's input
  without changing the owning Workbook's original measurements.

  # Automation: tests.test_workbook_copy_data.WorkbookCopyDataTests
  Scenario: Raw measurements remain drawable after removing Reference
    Given an analysis compares Reference and Raw measurements for wafer "001"
    When the engineer removes all Reference measurements
    Then Select maps no longer offers Reference measurements
    And the unchanged Raw measurements can still be drawn in Correlation and Trend

  Scenario: Switch an owned analysis to manual input and back
    Given a NOVA Workbook has measurements for wafer "001"
    When the engineer turns off Copy from WKB in an owned analysis
    Then its source tables and drawing choices are empty
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
