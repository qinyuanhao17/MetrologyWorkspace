Feature: Keep the main workspace comfortable between sessions
  Metrology engineers adjust the diagnostic Log while investigating a run
  and should not repeat that layout work after restarting the application.

  Rule: The diagnostic workspace remembers deliberate layout changes

    Scenario: Restore the adjusted Log height
      Given the engineer has dragged the divider above the Log
      When the application is closed and opened again
      Then the Log divider returns to the saved position

    Scenario: Show no redundant empty-tool message
      Given no analysis tool is open
      When the engineer views the main workspace
      Then no "No tools open" message is shown above the Log

    Scenario: Keep the shell free of redundant global status controls
      Given the analysis tools are available from the left navigation
      When the engineer views the main workspace
      Then no global Close all control is shown
      And no Ready label or green status dot reserves extra space

  Rule: Scrolling a result page does not accidentally change its plots

    Scenario: Continue down the page while the pointer is over a plot
      Given an analysis result has more content below the visible area
      When the engineer scrolls while the pointer is over a plot
      Then the result page moves down
      And the plot range remains unchanged

    Scenario: Deliberately zoom one plot
      Given an analysis result contains an interactive plot
      When the engineer holds Control while scrolling over that plot
      Then only that plot range is zoomed
      And the result page remains at the same position
