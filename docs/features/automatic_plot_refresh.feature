Feature: Refresh an established plot selection
  Metrology engineers should only repeat the draw command when the shape of the
  plot changes. A pure data change may redraw the established selection by
  itself, but a new box selection, or a changed wafer/parameter list, must not
  draw with the stale selection.

  Scenario: Change only the data behind an established Wafer Map selection
    Given the engineer has successfully drawn a Wafer Map selection
    When only the measurement data changes
    Then Wafer Map redraws the established selection automatically
    And no second draw command is required

  Scenario: Change the selected Wafer Map boxes after the first draw
    Given the engineer has successfully drawn a Wafer Map selection
    When the engineer changes the selected map boxes
    Then Wafer Map returns to the box selector
    And nothing is drawn until the engineer presses Draw selected

  Scenario: Add or remove a Wafer Map parameter after the first draw
    Given the engineer has successfully drawn a Wafer Map selection
    When the engineer adds or removes a parameter or measurement set
    Then Wafer Map returns to the box selector
    And the engineer selects the map boxes again and presses Draw selected

  Scenario: Change the selected Radius Plot boxes after the first draw
    Given the engineer has successfully drawn a Radius Plot selection
    When the engineer changes the selected plot boxes
    Then Radius Plot returns to the box selector
    And nothing is drawn until the engineer presses Draw selected

  Scenario: Add or remove a Radius Plot parameter after the first draw
    Given the engineer has successfully drawn a Radius Plot selection
    When the engineer adds or removes a parameter or measurement set
    Then Radius Plot returns to the box selector
    And the engineer selects the plot boxes again and presses Draw selected

  Scenario: Change only the data behind an established Radius Plot selection
    Given the engineer has successfully drawn a Radius Plot selection
    When only the measurement data changes
    Then Radius Plot redraws the established selection automatically
    And no second draw command is required

  Scenario: Reopen an established Wafer Map selection
    Given the engineer has successfully drawn a Wafer Map selection
    When the Wafer Map window or its saved Matching Workbook is reopened
    Then the last available map boxes are drawn automatically
    And no second draw command is required

  Scenario: Reopen an established Radius Plot selection
    Given the engineer has successfully drawn a Radius Plot selection
    When the Radius Plot window or its saved Matching Workbook is reopened
    Then the last available radius boxes are drawn automatically
    And no second draw command is required
