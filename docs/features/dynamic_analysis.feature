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

  Scenario: Compare sample three sigma by die
    Given one measurement set and DP are selected in Data
    When the engineer opens the Dynamic tab
    Then the pivot rows are Cycle and the columns are Die Seq
    And the last row is three times the sample standard deviation across cycles
    And a bar chart uses Die Seq horizontally and 3 Sigma vertically

  Scenario: Do not silently average ambiguous rows
    Given a measurement set contains the same Cycle and Die Seq more than once
    When the engineer requests its Dynamic pivot
    Then the analysis reports the duplicate pair
    And no average is substituted
