Feature: Select the current measurement rectangle
  Engineers select all current sheet content without reserved blank edges
  while keeping internal gaps in the same data rectangle.

  # Automation: tests.test_table_clipboard.TableClipboardTests
  Scenario: Clear the two leftmost columns of a ten-column sheet
    Given a sheet contains ten columns including its header row
    When the engineer clears the two leftmost columns and selects all
    Then only the remaining eight-column rectangle is selected
    And undoing the clear restores the original ten-column boundary

  Scenario: Clear the right edge but retain an internal gap
    Given a ten-column sheet has two empty columns in its middle
    When the engineer clears its two rightmost columns and selects all
    Then the remaining eight-column rectangle includes the internal gap

  Scenario: Row boundaries obey the same rule as column boundaries
    Given a sheet has ten populated rows
    When the engineer clears two top rows, two bottom rows and two internal rows
    Then selecting all excludes the empty top and bottom edges
    And the empty internal rows remain inside the selection

  Scenario: Hidden measurements do not determine a projected sheet's boundary
    Given a filtered sheet displays only wafer "002"
    When the engineer clears its leftmost column and selects all
    Then the selection starts at its first populated visible column
    And the hidden wafer "001" keeps its original measurements
