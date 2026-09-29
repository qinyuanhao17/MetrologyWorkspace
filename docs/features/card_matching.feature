Feature: Build a card matching workbook
  Metrology engineers need one reusable workflow for Reference and Raw Data
  so that daily matching no longer depends on rebuilding an Excel workbook.

  Rule: Reference defines the parameters that can be matched

    Scenario: Preview two mapped parameters in one workbook
      Given a Reference table with CD_Bot Reference and SPA Reference
      And row-aligned Raw Data with CD_Bot and SPA
      When the engineer runs a Preview match
      Then one Card is reported for each mapped parameter
      And trend and bias data use the Card-adjusted values

    Scenario: Manually map a numeric Reference column without a suffix
      Given a Reference table with Wafer ID, Die Seq, PMISH, TEM, and BIAS
      And Raw Data whose matching parameter uses a different column name
      When the engineer chooses TEM and its corresponding Raw Data column
      Then Wafer ID and Die Seq are not offered as parameters
      And the engineer can run the analysis without renaming TEM

    Scenario: Final data is not carded a second time
      Given Raw Data already produced by the OCD software with a Card
      When the engineer runs a Final match
      Then trend and bias data use the supplied Raw Data directly

  Rule: A workbook can be reopened without copying the tables again

    Scenario: Reopen a saved matching workbook
      Given a completed matching workbook with multiple parameters
      And the engineer has resized the input, mapping, and result sections
      And the engineer has reordered the parameter cards
      When the engineer saves and reopens the WKB file
      Then the Reference table, Raw Data, mappings, and analysis settings are restored
      And the saved section layout is restored
      And the saved parameter order is restored

    Scenario: Compare absolute and percentage bias in one review
      Given DP and EW have valid Reference and Raw Data mappings
      And both absolute and percentage bias are selected
      When the engineer runs a Preview match
      Then each Card result is shown beside its parameter mapping
      And DP and EW each have a separate plot card in vertical order
      And Match, Trend, absolute bias, and percentage bias use one unclipped horizontal row
      And Match is narrower than the Trend and bias plots
      And each Match plot is titled by its Raw Data column and shows its fitted equation and R squared
      And Trend labels the blue solid line PMISH and the orange solid line with the Match Type
      And Match labels PMISH horizontally and the Match Type vertically
      And Bias reports nanometres and percentage points without scale multipliers
      And no parameter selector is required

    Scenario: Review single-wafer quality separately from parameter plots
      Given KLA or NOVA Raw Data contains Wafer ID, Lot ID, PAD Name, and Die Seq
      When the engineer runs the analysis
      Then All parameter plots and Single-wafer metrics are separate result tabs
      And single-wafer groups use the same identity rules as Wafer Map
      And changing Lot or PAD creates a separate multi-line wafer label

    Scenario: Highlight a poor fit
      Given a completed analysis contains fitted Card metrics
      When a Slope is outside 0.9 through 1.1 or R squared is below 0.9
      Then the affected value is shown with a red warning treatment
      And an explanation identifies the failed threshold

    Scenario: Reopen both selected bias views
      Given a completed matching workbook with both bias views selected
      When the engineer saves and reopens the WKB file
      Then absolute and percentage bias are both restored

  Rule: Repeated clipboard runs stay in one compact workspace

    Scenario: Undo a replaced input table
      Given Reference and Raw Data have already been pasted
      When the engineer replaces either input table and undoes the change
      Then the previous table is restored
      And its parameter mappings are restored with it

    Scenario: Keep mappings while Raw Data is temporarily missing
      Given Reference parameters have valid Raw Data mappings
      When the engineer clears the Raw Data table
      Then the Reference parameter mappings remain visible and selected
      And the engineer is prompted to paste Raw Data and fix missing columns

    Scenario: Select every Reference parameter for mapping
      Given the Reference table contains several parameter candidates
      When the engineer selects all mappings
      Then every parameter candidate is selected
      And any missing Raw Data column is clearly reported

    Scenario: Re-run automatically after the first manual analysis
      Given Reference and Raw Data are mapped in the Preview tab
      And the engineer has run the analysis once
      When the engineer edits Reference, Raw Data, or a parameter mapping
      Then the current data is analyzed automatically
      And the result remains in the same scrollable workspace
      And the engineer's resized section layout remains unchanged

    Scenario: Re-run after changing a Raw Data mapping
      Given the engineer has completed the first manual analysis
      When a mapped parameter is changed to another valid Raw Data column
      Then the analysis updates automatically
      And the engineer's section layout and parameter order remain unchanged

    Scenario: Run analysis keeps a manually resized workspace
      Given the engineer has dragged the input, mapping, and result boundaries
      When the engineer runs the analysis
      Then the two upper boundaries stay at the positions chosen by the engineer

    Scenario: Choose Preview or Final from the top mode tabs
      Given a completed Preview analysis with a resized workspace
      When the engineer selects the Final tab
      Then Final is used as the result mode
      And the Reference, mappings, results, and section layout remain available
      And Final has its own Raw Data input instead of reusing Preview Raw Data
      And only the Final Wafer Map and Radius action is shown at the top right

    Scenario: Choose whether Trend displays Card-adjusted values
      Given a completed match contains Raw Data and a fitted Card
      When the engineer changes the Card choice on a Trend plot
      Then PMISH changes between the original Raw Data and Card-adjusted values
      And the Reference comparison remains visible

    Scenario: Keep one parameter at the top of the result area
      Given exactly one mapped parameter has been analyzed
      When the engineer reviews All parameter plots
      Then the parameter plot card starts at the top without an empty gap

    Scenario: Reorder parameter cards for review
      Given several mapped parameters have been analyzed
      When the engineer drags one parameter card above another
      Then all parameter results follow the chosen order
      And Reset restores Parameter mapping order

    Scenario: Use the compact workbook menu
      Given the Match Workbook is open
      Then file actions, Match Type, and Bias choices are available from the menu bar
      And no duplicate workbook heading or settings panel consumes the workspace

    Scenario: Show explanatory guidance only when requested
      Given a workspace section has explanatory guidance
      When the engineer views the workspace
      Then the section title is shown without a persistent annotation row
      And hovering the section title shows the same guidance
      And data status, warnings, errors, and empty-state feedback remain visible

  Rule: Match rows and FullMap rows have separate responsibilities

    Scenario: Apply a TEM Card to a later Preview FullMap
      Given a Card fitted from a small TEM match
      And a separate Preview FullMap with wafer coordinates
      When the engineer opens the Preview wafer workspace
      Then the fitted Card is applied to every mapped FullMap parameter
      And the wafer identifiers and coordinates are preserved

    Scenario: Open Final FullMap without applying Card again
      Given Final Raw Data already produced by the OCD software with a Card
      When the engineer opens the Final wafer workspace
      Then the Final parameter values are used directly
      And the existing Wafer Map and Radius Plot workspace is reused

  Rule: Approved results can leave the workbook

    Scenario: Export a customer-facing result
      Given a completed Preview or Final analysis
      When the engineer exports the result
      Then the workbook contains Summary, Reference, Raw Data, and result sheets
      And each analysis plot is saved as a separate image file
