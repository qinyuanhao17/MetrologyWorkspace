Feature: Compare selected Trend parameters
  The default Trend layout remains one panel per selected parameter. An
  engineer can add one or more comparison curves without removing those panels.

  Scenario: Add multiple comparison parameters from a Trend panel
    Given multiple numeric parameters are selected for Trend
    And each Trend plot shows an Add Compare control at its right edge
    When the engineer adds comparison selectors from that control
    Then each selector can switch parameters with the mouse wheel
    And all original parameter panels remain visible
    And equal units with comparable magnitudes share the left Y axis in Auto mode
    And equal units over the entered median ratio use a linked right Y axis
    And each differing unit can use a linked right Y axis
    And missing values are not interpolated
    And the right-click menu keeps only the native plot options

  Scenario: Read the unit from an OCD parameter name
    Given a model parameter name contains SWA
    Then that axis is measured in degrees
    Given a model parameter name contains ratio
    Then that axis is dimensionless
    Given any other model parameter
    Then that axis is measured in nanometres
    But an explicit suffix such as EW (V) or Si_SWA [rad] still wins

  Scenario: Enter a decimal automatic threshold or force an axis mode
    Given two compared curves share one unit
    And Analysis ▸ Trend Y axes is set to Auto at 10×
    When the engineer enters 7.5× in its spinbox
    Then a comparison whose median magnitudes are 8× apart moves to a linked right Y axis
    And entering 8.5× returns that comparison to the shared axis
    And Always two Y axes puts every comparison on a second axis
    And Always one Y axis puts every comparison on the left axis
    And mixing units on one axis is labeled as mixed units
    And the mode and decimal threshold are saved with the Matching Workbook
    And an older workbook with only the threshold restores Auto mode
    But a stand-alone Correlation and Trend window keeps its own in-page controls

  Scenario: Share the Analysis axis policy between Preview and Final
    Given Preview and Final Correlation and Trend windows are open
    When the engineer changes the Analysis axis mode or decimal threshold
    Then both windows immediately use the same policy
    And switching Preview and Final never replaces that policy
    And later opened windows use the same policy
    And saving without any child window open still persists that policy
    And reopening the WKB restores one policy for both stages
    But wafer and parameter checks remain independent for each stage

  Scenario: Migrate an older workbook with stage-specific axis policies
    Given an older WKB stores different policies for Preview and Final
    When that WKB is opened
    Then the saved active stage supplies the shared policy
    And the other stage is used only if the saved active stage has no policy
    And missing policy fields use defaults rather than the other stage's fields

  Scenario: Keep the panel an engineer is working on in view
    Given a Trend page shows more panels than fit on the screen
    And the engineer has scrolled down to a lower panel
    When a comparison selector is added, switched or removed
    Then every panel is redrawn
    And the page stays at the same scroll position
    And it never visibly jumps to the top on the way

  Scenario: Preserve source identity and colour during comparison
    Given Reference and Raw Data Trend panels are visible
    When a comparison parameter is added
    Then the Reference base curve remains orange
    And the Raw Data base curve remains blue
    And added parameters use colours other than orange and blue
    And every legend item names both its source and parameter

  Scenario: Keep comparison choices clear without narrowing the plot
    Given Reference and Raw Data Trend panels are visible
    When the engineer adds comparison selectors
    Then every selector offers parameters from both Ref Data and Raw Data
    And every choice names the table that supplies its data
    And a selected curve uses values from that named table
    And the selectors stay grouped in a reserved control area
    And the Trend plot keeps its original width

  Scenario: Remove one comparison selector
    Given a Trend panel has multiple comparison selectors
    When the engineer removes one selector
    Then only that comparison curve is removed
    And all original parameter panels remain visible
