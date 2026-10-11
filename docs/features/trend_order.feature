# Executable examples: tests/test_trend_order.py
Feature: Choose a readable source order for trends
  Analysts can keep source rows in their original order or collect each Wafer's
  Lot and PAD observations without editing measurements or participation.

  Scenario: Collect interleaved Wafer identities
    Given observations from the same Wafer alternate between two Lots
    When Original Wafer order is chosen
    Then each Wafer, Lot and PAD combination occupies one continuous range
    And combinations follow their first appearance in the original source
    And observations within each combination retain their original row order

  Scenario: Choose source order with or without classification
    Given a Workbook has retained Head and Mark assignments
    When classification is disabled
    Then Original row order and Original Wafer order remain available
    And enabling classification also offers Group to Wafer to Die Seq order

  Scenario: Retain observations when changing the presentation order
    Given some source observations are excluded from analysis
    When the Trend order changes
    Then Trend and Bias use the same participating source rows in the chosen order
    And original tables, participation identities and fitted results are unchanged

  Scenario: Reopen a linked Trend in the selected order
    Given a Workbook and its linked Trend use Original Wafer order
    When the Workbook is saved and reopened
    Then the selected order and linked Trend selections are restored
    And the linked Trend shows the same Wafer identity ranges as the Workbook
