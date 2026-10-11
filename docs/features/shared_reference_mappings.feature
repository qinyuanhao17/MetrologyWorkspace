# Executable examples: tests/test_mapping_row_controls.py
Feature: Compare several Raw Data parameters against one Reference
  Analysts can reuse a Reference measurement without duplicating source records.

  Scenario: Keep a second comparison as an unfinished draft
    Given CD Reference is the only Reference parameter and is mapped to CD
    When the analyst adds another mapping for CD Reference and chooses Depth
    Then the original CD mapping is unchanged
    And the new mapping stays unused until the analyst enables it
    And saving and reopening the Workbook retains both mappings and all source measurements

  Scenario: Renaming a draft comparison does not enable it
    Given a new CD Reference mapping is unused and has no Raw Data column
    When the analyst names it CD and refreshes the source tables
    Then the new mapping remains unused without an inferred Raw Data column
    And the same choice is retained when the saved Workbook is reopened

  Scenario: Keep distinct calibration results for a shared Reference
    Given CD Reference is mapped to both CD and Depth as separate named comparisons
    When the analyst runs matching and reopens the saved Workbook
    Then each comparison retains its own Card and Bias limit
    And unused mappings are retained without showing a Card

  Scenario: Remove one comparison without removing another using the same Reference
    Given CD and Depth are separately mapped to CD Reference
    When the analyst removes only the CD comparison
    Then the Depth comparison is retained
    And all source measurements are unchanged
