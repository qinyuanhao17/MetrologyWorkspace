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

    Scenario: Final data is not carded a second time
      Given Raw Data already produced by the OCD software with a Card
      When the engineer runs a Final match
      Then trend and bias data use the supplied Raw Data directly

  Rule: A workbook can be reopened without copying the tables again

    Scenario: Reopen a saved matching workbook
      Given a completed matching workbook with multiple parameters
      When the engineer saves and reopens the WKB file
      Then the Reference table, Raw Data, mappings, and analysis settings are restored
  Rule: Approved results can leave the workbook

    Scenario: Export a customer-facing result
      Given a completed Preview or Final analysis
      When the engineer exports the result
      Then the workbook contains Summary, Reference, Raw Data, and result sheets
      And each analysis plot is saved as a separate image file