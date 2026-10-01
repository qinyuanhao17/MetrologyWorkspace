Feature: Compare two selected Trend parameters
  The default Trend layout remains one panel per selected parameter, while an
  engineer may explicitly compare two compatible selections in one panel.

  Scenario: Overlay two parameters from a Trend panel
    Given two numeric parameters are selected for Trend
    When the engineer chooses overlay comparison from a panel context menu
    Then equal explicit units share the left Y axis
    And different or unknown units use a linked right Y axis
    And missing values are not interpolated

  Scenario: Remove a Trend overlay
    Given two parameters are shown in one comparison panel
    When the engineer chooses remove comparison
    Then each parameter returns to its own panel
    And the selected measurement sets and X-axis semantics remain unchanged
