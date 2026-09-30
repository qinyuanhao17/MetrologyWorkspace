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

  Scenario: Compare selected parameters and inspect each separately
    Given one measurement set and DP and EW are selected in Data
    When the engineer opens the Dynamic tab
    Then no second parameter picker is shown
    And the pivot rows are Cycle and the columns group Die Seq by parameter
    And the last row is three times the sample standard deviation across cycles
    And one grouped bar chart compares DP and EW using distinct colours, markers, and a legend
    And one separate bar chart is shown for DP and one for EW
    And every chart is 510 pixels wide and 330 pixels high
    And the chart area scrolls horizontally when the charts exceed the viewport

  Scenario: Do not silently average ambiguous rows
    Given a measurement set contains the same Cycle and Die Seq more than once
    When the engineer requests its Dynamic pivot
    Then the analysis reports the duplicate pair
    And no average is substituted
