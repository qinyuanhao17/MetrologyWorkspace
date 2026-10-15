Feature: Name independent analysis windows directly in their list
  Engineers distinguish their analysis drafts without replacing measurements
  or changing which windows reopen from the Workbook.

  # Automation: tests.test_named_analysis_windows.NamedAnalysisWindowTests
  Scenario: Delete an obsolete independent analysis
    Given "Keep Map" and "Delete Map" are independent analysis drafts
    When the engineer confirms deleting "Delete Map" from its window list
    Then "Delete Map" and its independent tables are absent after saving and reopening
    And "Keep Map" and the Workbook source tables are unchanged
    And cancelling deletion keeps the selected draft intact

  Scenario: Open one analysis without changing which windows reopen together
    Given "Map baseline" and "Map adjusted" are hidden analysis windows
    And "Map baseline" is not chosen to reopen with the others
    When the engineer selects the name "Map baseline" in the analysis list
    Then only "Map baseline" opens
    And its reopening choice remains unchecked

  Scenario: Choose windows without opening them
    Given "Map baseline" is a hidden analysis window
    When the engineer checks its reopening choice
    Then it is chosen to reopen with the others
    And it remains hidden

  Scenario: Create an independent blank analysis
    Given a Workbook already contains Reference and Raw Data
    When the engineer creates a new named analysis window
    Then its editable input tables are empty and Copy from WKB is off
    And parent data changes do not fill its tables
    And it stays empty when saved and reopened from the Workbook

  Scenario Outline: Keep the original first Map window linked to Raw Data
    Given a <match_type> Workbook contains Reference and Raw Data
    When the engineer opens its first Map window from the list
    Then Copy from WKB is on and its table contains the Workbook Raw Data
    And additional New windows start with empty manual tables

    Examples:
      | match_type |
      | KLA        |
      | NOVA       |

  Scenario: Rename a window without changing its draft or reopening choice
    Given an open wafer map named "Map baseline" has unsaved measurements
    When the engineer renames that window to "Map tuned" directly in its analysis list
    Then the same open window is named "Map tuned"
    And its measurements and reopening choice remain unchanged

  Scenario: Cancel a rename without changing an unchecked window
    Given a Dynamic analysis named "Dynamic baseline" is not chosen to reopen
    When the engineer cancels renaming that analysis
    Then it remains named "Dynamic baseline"
    And its measurements and unchecked reopening choice remain unchanged
