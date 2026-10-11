# Executable examples: tests/test_reference_source_columns.py
Feature: Read the original Reference measurements independently of matching
  Analysts can distinguish Reference measurements from Raw Data and calibration names.

  Scenario: A shared Reference retains its original source columns
    Given Raw Data supplies Wafer ID, Lot ID, PAD Name and Die Seq
    And Reference supplies OCD_DEPTH1, W_Recess_Reference and CINDEX
    When OCD_DEPTH1 is used in two differently named parameter mappings
    Then Ref Data retains all three original Reference column names and literal values
    And its four identity columns come from the corresponding Raw Data rows

  Scenario: Source column names do not detach existing classification
    Given a Workbook classifies its source records as Head A and Head B
    When its linked Trend reads Reference with the original column names
    Then the Trend retains both Head classifications and the same source measurements

  Scenario: Reopen a linked analysis saved with Reference aliases
    Given an older linked analysis used a calibration name for its Reference parameter
    When its Workbook is reopened with original Reference column names
    Then its Reference draw choices and comparisons use the original column name
    And identically named Raw Data choices remain unchanged
    And saving and reopening again retains the same plotted source records

  # Executable: tests/test_performance_regressions.py and tests/test_selector_updates.py
  Scenario: Change a Raw parameter without rebuilding unrelated source choices
    Given Reference and Raw Data have independently named parameters
    When one Raw parameter is unchecked and checked again
    Then the corresponding Reference choices remain available
    And all source records and literal values remain unchanged
    And Draw choices follow the same existing selection rules
