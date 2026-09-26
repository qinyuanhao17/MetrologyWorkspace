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
      When the engineer saves and reopens the WKB file
      Then the Reference table, Raw Data, mappings, and analysis settings are restored

    Scenario: Compare absolute and percentage bias in one review
      Given DP and EW have valid Reference and Raw Data mappings
      And both absolute and percentage bias are selected
      When the engineer runs a Preview match
      Then each Card result is shown beside its parameter mapping
      And DP and EW each have a separate plot card in vertical order
      And Match, Trend, absolute bias, and percentage bias use an unclipped 2 by 2 grid
      And no parameter selector is required

    Scenario: Reopen both selected bias views
      Given a completed matching workbook with both bias views selected
      When the engineer saves and reopens the WKB file
      Then absolute and percentage bias are both restored

  Rule: Repeated clipboard runs stay in one compact workspace

    Scenario: Re-run automatically after the first manual analysis
      Given Reference and Raw Data are mapped in the Preview tab
      And the engineer has run the analysis once
      When a replacement table is pasted into Raw Data at A1
      Then the new Raw Data is analyzed automatically
      And the result remains in the same scrollable workspace

    Scenario: Choose Preview or Final from the top mode tabs
      Given the Match Workbook is open
      When the engineer selects the Final tab
      Then Final is used as the result mode
      And only the Final Wafer Map and Radius action is shown at the top right

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
