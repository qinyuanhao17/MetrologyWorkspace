Feature: View several drawn parameters together
  Engineers compare related plots without changing measurements or fitted results.

  # Automation: ParameterFilterTests.test_source_groups_have_distinct_containers_and_keep_wrapped_buttons_inside
  Scenario: Distinguish Reference and Raw controls at any window width
    Given drawn plots contain both Reference and Raw parameters
    Then REF and RAW appear in separate outlined groups with distinct source badges
    And wrapped buttons stay inside their source group with a visible gap between groups
    And ALL remains a global choice outside both groups

  # Automation: ParameterFilterTests.test_source_rows_keep_same_named_parameters_independent_and_wrap_separately
  Scenario: Navigate Reference and Raw parameters independently
    Given drawn plots contain "DP" in both Reference and Raw Data
    When the engineer chooses "DP" in the REF row
    Then only plots containing Reference "DP" are displayed
    And Raw "DP" remains independently selectable in the lower RAW row

  # Automation: ParameterFilterTests.test_cross_source_same_name_pairs_use_aligned_rows_and_export_distinct_axes
  Scenario: Correlate same-named columns from different sources
    Given Reference "DP" and Raw "DP" are different row-aligned measurement columns
    When the engineer chooses both source-qualified parameters with Ctrl and Alt
    Then their paired correlation is displayed and exported with distinct REF and RAW axes
    And missing or excluded observations do not shift the remaining pairs
    And saved source choices and axis direction are restored when reopened

  # Automation: tests.test_parameter_filter.ParameterFilterTests
  Scenario: Isolate the correlation between two drawn parameters
    Given drawn correlations contain parameters "DP", "TG", and "EW"
    When the engineer chooses "DP" and "EW" with Ctrl and Alt
    Then only the correlation between "DP" and "EW" is displayed and exported
    And measurements, fitted results, axis direction, and zoom remain unchanged

  # Automation: CorrelationMultiPairTests.test_keyboard_pair_selection_keeps_three_and_restore_and_removal_keep_pair_mode
  # Automation: CorrelationMultiPairTests.test_three_of_four_parameters_draw_three_pairs_not_the_union_or_reverse_duplicates
  # Automation: CorrelationMultiPairTests.test_source_qualified_multi_pair_selection_saves_and_reopens_without_reverse_duplicates
  Scenario: Compare all unordered pairs inside a multi-parameter choice
    Given drawn correlations contain parameters A, B, C and D
    When the engineer chooses A, B and C with Ctrl and Alt
    Then A-B, A-C and B-C are displayed and exported exactly once each
    And reversed B-A, C-A and C-B do not create extra plots
    And no pair containing unselected D is displayed
    When D is also chosen with Ctrl and Alt
    Then all six unordered pairs are available without dropping the previous choices
    And Ctrl and Alt can remove individual choices again
    And saved multi-pair choices reopen with the same source-qualified pairs
    And Reference A and Raw A remain different columns
    And ordinary Ctrl union filtering and Trend navigation remain unchanged

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
