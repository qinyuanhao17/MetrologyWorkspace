Feature: Review Dynamic repeatability by cycle and die
  Metrology engineers need repeat testing summarized without rebuilding an
  Excel pivot table for every parameter.

  Scenario: Infer repeated cycles from Dynamic run folders
    Given one measurement set contains repeated Die Seq rows from several Dynamic runs
    When the engineer opens the table in Dynamic
    Then a one-based Cycle column is inserted after Die Seq
    And every row from the same Dynamic run has the same Cycle

  Scenario: Fall back to repeated die order
    Given the source paths do not identify Dynamic run folders
    And each cycle repeats the same ordered Die Seq values
    When the engineer opens the table in Dynamic
    Then a new Cycle begins whenever a Die Seq repeats
    And the number of dies and cycles is not fixed to 13 by 10

  Scenario: Review selected parameters in separate scrollable sections
    Given one measurement set and DP and EW are selected in Data
    When the engineer opens the Dynamic tab
    Then no second parameter picker is shown
    And DP and EW each have their own Cycle by Die Seq table
    And every table ends with three times the sample standard deviation across cycles
    And the tables are stacked in a scrollable upper region
    And the lower region starts with one colour-coded chart comparing all selected parameters
    And the combined chart replaces its redundant title with one horizontal legend
    And the legend uses compact colour swatches
    And each parameter also has its own compact 3 Sigma chart
    And the bars do not have point markers overlaid
    And the repeated Dynamic page heading is omitted

  Scenario: Wrap compact parameter charts in rows of three
    Given one measurement set and five parameters are selected in Data
    When the engineer opens the Dynamic tab
    Then the combined chart and first two parameter charts share one row
    And the remaining three parameter charts continue on the next row

  Scenario: Keep selected parameters when Dynamic data is replaced
    Given DP and EW are selected for one Dynamic measurement set
    When a replacement table still contains DP and EW
    Then DP and EW remain selected
    And their tables and charts refresh with the replacement values

  Scenario: Do not silently average ambiguous rows
    Given a measurement set contains the same Cycle and Die Seq more than once
    When the engineer requests its Dynamic pivot
    Then the analysis reports the duplicate pair
    And no average is substituted

  Scenario: Drop outlier grid points from a Dynamic table
    Given DP has a Cycle by Die Seq table
    When the engineer selects a value cell and presses Delete
    Then that measurement point is removed from the Data sheet
    And the affected 3 Sigma values are recomputed
    And the table stays on the same scroll position and current cell

  Scenario: Undo one step without a redundant Restore button
    Given the engineer deleted several cells from a Dynamic table
    When the engineer presses Ctrl+Z
    Then only the most recent deletion is undone
    And no Restore button is shown in the parameter section

  Scenario: Correct repeat measurements without disturbing other parameter views
    Given DP and EW repeatability results and Cycle trends are displayed
    When the engineer corrects a DP measurement or undoes that correction
    Then DP statistics and its displayed Cycle curve reflect the current measurement
    And EW curves keep their zoom and chosen Die
    And the tables keep their current cells and scroll positions

  Scenario: Keep derived Dynamic cells read-only
    Given a Dynamic Cycle by Die Seq table
    Then the Cycle and Die labels are not editable
    And the 3 Sigma row is not editable

  Scenario: Read the Dynamic Trend tab as Cycle versus Die
    Given one measurement set and DP and EW are selected in Data
    When the engineer opens the Trend tab of Dynamic
    Then DP and EW each have their own interactive panel
    And Cycle runs along the bottom axis of every panel
    And every panel draws exactly one Die Seq at a time
    And a Die selector sits to the right of each panel
    And an Add Compare control can add other selected parameters for that same Die
    And no curve-box selector is required

  Scenario: Switch the Die of one Dynamic Trend panel
    Given the Dynamic Trend tab shows a panel per parameter
    When the engineer picks Die 7 in the DP panel
    Then the DP panel redraws that Die only
    And every other panel keeps the Die it was showing
    And the exported figure titles DP as DP · Die 7
    When the engineer scrolls over that Die selector
    Then scrolling down selects the next Die and scrolling up selects the previous Die
    And the page stays at its current scroll position
    And scrolling beyond the first or last Die keeps that Die selected

  Scenario: Refresh and export the Dynamic Trend panels
    Given the Dynamic Trend tab shows a Cycle panel
    When the loaded data or the Data selection changes
    Then the panels are redrawn without another command
    And the panel list keeps its scroll position
    And Copy PNG and Export PNG both use the Cycle axis and Die legends

  # Automation: RequestedPlotControlsTests.test_dynamic_comparisons_follow_the_same_die_and_export_every_curve
  Scenario: Compare multiple parameters for one Die
    Given DP and EW are selected
    When Add Compare adds EW to DP and the DP Die picker changes to Die 2
    Then both curves in DP use Die 2 and keep their original values
    And the independent EW panel keeps its selected Die
    And removing the comparison removes only that curve
    And PNG export includes every displayed comparison

  # Automation: RequestedPlotControlsTests.test_dynamic_all_dies_view_keeps_missing_gaps_and_statistics
  Scenario: Compare all Dies for the same parameter
    When the engineer switches Trend to All Dies
    Then each parameter has one plot with all of its Die curves
    And the legend identifies each Die
    And missing values remain gaps
    And Y ticks use unscaled values without an axis multiplier
    And Mean, sample sigma, Min and Max appear on empty-space hover without a title annotation
