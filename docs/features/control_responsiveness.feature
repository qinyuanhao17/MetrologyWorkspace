Feature: Responsive editing and plotting without losing measurements
  Engineers repeatedly update large NOVA workbooks. Faster interaction must
  preserve source records, stage-specific results and complete exported curves.

  Scenario: Select a filtered Raw Data table and return to one cell
    Given thousands of source records are displayed in a filtered or sorted table
    When the engineer selects all records and then clicks one cell
    Then the whole-table selection becomes a single-cell selection promptly
    And clearing and undoing the selected cells preserves exact source values

  Scenario: Return to a previously analyzed stage
    Given Preview and Final contain different Raw Data
    When the engineer switches repeatedly between Preview and Final
    Then the displayed Card and curves belong to the selected stage
    And existing plot arrangements and views survive the switch

  Scenario: Apply a group order with an analysis window open
    Given the engineer is reading a child analysis's selection panel
    When the workbook updates its sources or applied group settings
    Then the child receives one consistent final selection
    And the selection panel remains visible

  Scenario: Zoom a dense Trend and immediately export it
    Given a Trend contains many measured points including a gap and a narrow spike
    When the engineer uses Ctrl and the wheel to zoom
    Then the plot remains responsive and retains every measured point
    And an immediate export contains the complete current curve
    And an older rendering result cannot replace newer source data

  Scenario: Restore a wafer view while automatic fitting is queued
    Given an earlier window resize has queued automatic fitting
    When the engineer explicitly restores a percentage zoom and scroll position
    Then the earlier automatic fit cannot overwrite the restored view

  Scenario: Prepare sparse and repeated Die Seq values
    Given a source contains missing Die Seq values and repeated valid sequence numbers
    When Trend is drawn in sequence order or preserved group order
    Then invalid sequence rows are excluded by the existing rule
    And repeated sequence numbers retain their stable source order
    And missing parameter values remain gaps rather than interpolated data
