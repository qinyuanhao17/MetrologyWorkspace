Feature: View several drawn parameters together
  Engineers compare related plots without changing measurements or fitted results.

  # Automation: tests.test_parameter_filter.ParameterFilterTests
  Scenario: Add a second parameter to the displayed plots
    Given drawn plots contain parameters "DP", "TG", "EW", and "UC"
    And the engineer is viewing "DP"
    When the engineer also chooses "EW" with Ctrl
    Then plots containing "DP" or "EW" are displayed together
    And the measurements, fitted results, and zoom remain unchanged

  Scenario: Saved multi-parameter views reopen together
    Given a Workbook analysis displays "DP" and "EW" together
    When the engineer saves and reopens the Workbook analysis
    Then "DP" and "EW" remain chosen in Correlation and Trend
    And the original measurements remain unchanged
