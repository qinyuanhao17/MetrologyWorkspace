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
