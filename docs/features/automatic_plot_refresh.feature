Feature: Refresh an established plot selection
  Metrology engineers should not repeat the draw command after they have
  established how a plot should be built.

  Scenario: Change the selected Wafer Map boxes after the first draw
    Given the engineer has successfully drawn a Wafer Map selection
    When the engineer changes the selected map boxes
    Then Wafer Map redraws the changed selection automatically
    And no second draw command is required

  Scenario: Change the selected Radius Plot boxes after the first draw
    Given the engineer has successfully drawn a Radius Plot selection
    When the engineer changes the selected plot boxes
    Then Radius Plot redraws the changed selection automatically
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
