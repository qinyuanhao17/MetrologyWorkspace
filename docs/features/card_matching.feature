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

    Scenario: Keep saving to the current workbook path
      Given the engineer has saved or opened a Match Workbook
      When the engineer saves the workbook again
      Then the current WKB file is replaced without asking for another path
      And Save As can choose a different WKB file for later saves

    Scenario: Compare absolute and percentage bias in one review
      Given DP and EW have valid Reference and Raw Data mappings
      And both absolute and percentage bias are selected
      When the engineer runs a Preview match
      Then each Card result is shown beside its parameter mapping
      And DP and EW each have a separate plot card in vertical order
      And Match, Trend, absolute bias, and percentage bias use one unclipped horizontal row
      And all four plots fit the visible workbook without horizontal scrolling
      And each Match plot is 340 pixels wide
      And Trend and bias plots share the remaining width evenly
      And every primary plot is 330 pixels high
      And each Match plot has a reserved heading with its Raw Data column and fitted equation with R squared to the right
      And the reserved heading ends above the Match curve and data points
      And Trend labels the blue solid line PMISH and the orange solid line with the Match Type
      And Match labels PMISH horizontally and the Match Type vertically
      And Trend and Bias omit the redundant Wafer axis title
      And the three plot frames align with equal-weight edges
      And Bias reports nanometres and percentage points without scale multipliers
      And no parameter selector is required

    Scenario: Inspect a smaller region of a result plot
      Given a completed Match Workbook analysis has visible result plots
      When the engineer drags a selection box inside one plot
      Then that plot zooms to the selected region
      And every plot keeps a complete four-sided axis frame

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
      And only the Final Wafer Map, Radius, and Dynamic actions are shown at the top right

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
      And the chosen order is kept when the workbook is reopened

    Scenario: Use the compact workbook menu
      Given the Match Workbook is open
      Then file actions, Match Type, and Bias choices are available from the menu bar
      And no duplicate workbook heading or settings panel consumes the workspace

    Scenario: Reopen a recently used workbook
      Given matching-analysis.wkb was opened successfully
      When the engineer returns to Match Workbook later
      Then matching-analysis.wkb is available from the recent workbook list
      And choosing it opens that workbook directly

    Scenario: Locate the current workbook on disk
      Given matching-analysis.wkb is the current saved workbook
      When the engineer asks to reveal the workbook
      Then the operating system opens its folder with matching-analysis.wkb selected

    Scenario: Compare workbook Reference and Raw Data correlations
      Given a Match Workbook has mapped Reference and Raw Data parameters
      When the engineer opens Correlation and Trend from the active mode
      Then the standard Correlation and Trend workspace opens with separate Ref Data and Raw Data tabs
      And each data tab has its own wafer and parameter choices
      And each wafer choice shows the real measurement identity instead of the data source name
      And Raw Data keeps all original columns
      And Reference measurement identity is aligned row by row from Raw Data
      And correlations are fitted only within their own source table
      And all Reference plots precede all Raw Data plots
      And Reference plots are orange while Raw Data plots are blue
      And Trend uses the same Reference-first source order and colours

    Scenario: Reopen drawn Correlation and Trend without selecting again
      Given Preview Correlation and Trend has independent Ref and Raw choices
      And the engineer has drawn selected Correlation fits and Trend curves once
      When the analysis window or its saved WKB is closed and reopened
      Then the surviving sidebar choices and selected plot boxes are restored
      And Correlation and Trend redraw automatically
      And Final keeps a separate selection state from Preview

    Scenario: Repair duplicate headers in every editable data table
      Given an editable Reference or Raw Data table has duplicate row-1 names
      When the engineer uses Auto rename in the visible warning
      Then only the repeated headers receive unique numeric suffixes
      And the measurement rows remain unchanged

    Scenario: Show explanatory guidance only when requested
      Given a workspace section has explanatory guidance
      When the engineer views the workspace
      Then the section title is shown without a persistent annotation row
      And hovering the section title shows the same guidance
      And data status, warnings, errors, and empty-state feedback remain visible

  Rule: Match rows and FullMap rows have separate responsibilities

    Scenario: Reopen an edited KLA or NOVA map from the workbook
      Given a KLA or NOVA workbook whose Map starts from matching Raw Data
      When the engineer edits the Map table and saves the WKB file
      Then reopening the WKB restores the edited Map table exactly
      And no separate Map file is required

    Scenario: Keep TEM Map data separate from matching Raw Data
      Given a TEM workbook has matching Raw Data but no Map table
      When the engineer opens the wafer workspace
      Then the Map table is empty instead of copying matching Raw Data
      And Map data entered later is restored from the saved WKB file

    Scenario: Apply a TEM Card to a later Preview FullMap
      Given a Card fitted from a small TEM match
      And a separate Preview FullMap with wafer coordinates
      When the engineer opens the Preview wafer workspace
      Then the fitted Card is applied to every mapped FullMap parameter
      And the wafer identifiers and coordinates are preserved

    Scenario: Restore Map and Dynamic choices after restarting the workbook
      Given Preview Map has only CD_Bot selected
      And Preview Dynamic has only SPA selected
      When the Matching Workbook is saved, closed, and reopened
      Then Preview Map still has only CD_Bot selected
      And Preview Dynamic still has only SPA selected

    Scenario: Open Final FullMap without applying Card again
      Given Final Raw Data already produced by the OCD software with a Card
      When the engineer opens the Final wafer workspace
      Then the Final parameter values are used directly
      And the existing Wafer Map and Radius Plot workspace is reused

    Scenario: Reopen Preview and Final Dynamic data independently
      Given Preview and Final have different Dynamic tables
      When the engineer saves and reopens the WKB file
      Then the Preview Dynamic table is restored exactly
      And the Final Dynamic table is restored exactly

    Scenario: Reopen a stage workspace without selecting parameters again
      Given parameters are selected in a Preview Dynamic or Wafer Map workspace
      When the engineer closes and reopens that Preview workspace
      Then parameters still present in its data remain selected
      And the corresponding analysis refreshes immediately

    Scenario: Close a workbook-managed workspace without discarding edits
      Given a Wafer Map or Dynamic workspace was opened from a saved Match Workbook
      And its table has been edited
      When the engineer closes that workspace
      Then no discard-edits confirmation is shown
      And the edited table is saved into the current WKB file
      But an independently opened workspace still confirms before discarding edits

    Scenario: Close a Match Workbook with its analysis workspaces
      Given Wafer Map, Dynamic, and Correlation are open from a saved Match Workbook
      And the Map and Dynamic tables contain current edits
      When the engineer closes the Match Workbook
      Then the current Map and Dynamic tables are saved into that WKB file
      And all three analysis workspaces close with the Match Workbook

    Scenario: Follow workbook edits in KLA and NOVA
      Given KLA or NOVA is selected and its Wafer Map and Correlation windows are open
      When the engineer edits the Raw Data in the Match Workbook
      Then the Wafer Map and Correlation windows show the updated data
      But a window whose table the engineer edited keeps that edit

    Scenario: Keep the Dynamic table independent
      Given a Dynamic window was opened from a Match Workbook
      When the engineer edits the Raw Data in that workbook
      Then the Dynamic table keeps the values it was opened with
      And the engineer's own Dynamic edits are saved with the WKB

    Scenario: Choose whether a workspace applies the parameter Cards
      Given a Wafer Map or Dynamic window was opened from a Match Workbook
      Then its Data tab shows the values as they were loaded
      And a Card option is available but not ticked
      When the engineer ticks Card
      Then the mapped parameters are plotted and analysed with slope × value + intercept
      But the table itself keeps the loaded values
      When the engineer clears Card
      Then the plots return to the loaded values

    Scenario: Keep TEM tables independent and single
      Given TEM is selected
      When the engineer opens the Wafer Map, Dynamic and Correlation windows
      Then all three stay open
      And pressing one of those buttons again reuses its own window
      And the Correlation and Trend window follows Raw Data edits
      But the TEM Wafer Map table is never overwritten from Raw Data

  Rule: Approved results can leave the workbook

    Scenario: Export a customer-facing result
      Given a completed Preview or Final analysis
      When the engineer exports the result
      Then the workbook contains Summary, Reference, Raw Data, and result sheets
      And each analysis plot is saved as a separate image file
