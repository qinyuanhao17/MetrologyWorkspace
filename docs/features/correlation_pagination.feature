Feature: Browse ranked correlation fits without truncation
  Engineers can inspect every fit that passes the R² threshold without loading
  an unbounded number of interactive plots at once.

  Scenario: Move through every passing correlation fit
    Given more correlation fits pass the R² threshold than fit on one page
    When the engineer draws the selected fits
    Then the first ranked page is shown
    And Previous and Next move through every passing fit
    And changing the page size returns to the first page
    And global R² rank numbers are preserved across pages

  Scenario: Export every passing correlation page
    Given passing correlation fits span multiple pages
    When the engineer exports all pages
    Then each page is written as a numbered PNG
    And the current on-screen page does not change

  Scenario: Keep plot size stable on a partial final page
    Given the final ranked page does not fill every configured grid cell
    When the engineer moves to that page
    Then each visible plot keeps the same width and height as a full page plot
    And the unused grid cells remain empty instead of stretching the plots
