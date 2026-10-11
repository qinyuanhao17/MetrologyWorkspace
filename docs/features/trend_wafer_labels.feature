# Executable examples: tests/test_trend_wafer_labels.py
Feature: Read wafer identities in continuous trends
  Analysts can read all wafer identities without changing source measurements.

  Scenario: Reopen a linked Trend after disabling classification
    Given a saved linked Trend used Mark classification
    And the Workbook now has both Head groups and Mark disabled
    When the linked Trend is reopened
    Then its captions identify wafers instead of the old Mark names
    And its drawn observations and selected parameters are retained

  Scenario: Read every wafer in an expanded Trend
    Given 40 measurement sets have long wafer identities
    When their Trend is expanded horizontally
    Then all wafer captions are readable without overlap
    And horizontal scrolling reaches the first and last wafer
    And disabling expansion restores the compact layout without changing observations

  Scenario: Keep expansion choices with each saved analysis
    Given two named Trends have different expansion choices
    When the Workbook is saved and reopened
    Then each Trend retains its own expansion choice
    And a Workbook without saved expansion choices uses the compact layout

  Scenario: Expand uneven wafers compactly
    Given some wafers contain one observation and others contain many
    When Expand Wafers is enabled
    Then each wafer receives only enough space for its captions and observations
    And no short wafer stretches every other wafer
    And all observations, identities and selected measurements remain unchanged
    And disabling expansion restores the original ordinal positions and docking

  Scenario: Expand interleaved Wafer identities
    Given one Wafer alternates between two Lots in the source rows
    When Expand Wafers is enabled on a Workbook Trend
    Then each Wafer and Lot identity occupies one continuous range
    And the drawn Trend and Bias curves keep their objects and observations
    And the saved Trend order value is unchanged
    And disabling expansion restores the exact source row order

  Scenario: Keep expanded positions across comparisons and Card changes
    Given an expanded Trend has unequal wafer sizes
    When its Card choice changes or a comparison uses a second Y axis
    Then all curves use the same wafer positions with their complete original values
    And Group classification and real Die Seq labels are unchanged

  Scenario: Retain selected source measurements when enabling classification
    Given a saved linked Trend displayed wafer captions
    When the Workbook enables Mark classification before reopening that Trend
    Then the Trend uses the current Mark captions
    And its selected source measurements survive another Save and reopen

  Scenario: Preserve Full data within current classification
    Given a Workbook classifies 12 source rows into Head A and Head B
    And its participation excludes the 6 Head B rows
    When a linked Trend uses Full data and selects both source wafers
    Then all 12 source observations are available under their correct Head captions
    And Save and reopen preserve that scope without changing Workbook participation
