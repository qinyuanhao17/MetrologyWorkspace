Feature: Name independent analysis windows directly in their list
  Engineers distinguish their analysis drafts without replacing measurements
  or changing which windows reopen from the Workbook.

  # Automation: tests.test_named_analysis_windows.NamedAnalysisWindowTests
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
