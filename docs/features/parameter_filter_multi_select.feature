Feature: View several drawn parameters together
  Engineers compare related plots without changing measurements or fitted results.

  # Automation: tests.test_parameter_filter.ParameterFilterTests
  Scenario: Isolate the correlation between two drawn parameters
    Given drawn correlations contain parameters "DP", "TG", and "EW"
    When the engineer chooses "DP" and "EW" with Ctrl and Alt
    Then only the correlation between "DP" and "EW" is displayed and exported
    And measurements, fitted results, axis direction, and zoom remain unchanged

  Scenario: Keep a chosen pair when reopening an analysis
    Given a Workbook analysis isolates the correlation between "DP" and "EW"
    When the engineer saves and reopens the Workbook analysis
    Then only the correlation between "DP" and "EW" remains displayed and exported
    And the Trend parameter selection and original measurements remain unchanged

  Scenario: A requested pair does not pass the current fit threshold
    Given correlations for "DP" with "TG" and "EW" pass the fit threshold
    But the correlation between "TG" and "EW" does not
    When the engineer chooses "TG" and "EW" with Ctrl and Alt
    Then a clear no-correlation message replaces the plots and plot export is unavailable
    And the threshold and fitted results remain unchanged

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
