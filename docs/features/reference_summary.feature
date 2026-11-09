Feature: Summarize multi-vendor reference exports
  Metrology engineers need a consistent, checked batch output from vendor files
  without changing the original measurements or crowding the desktop with raw rows.

  Rule: A summary run publishes only complete checked output

    Scenario: Summarize a NOVA batch
      Given one or more NOVA CSV exports are selected
      When the engineer runs Reference Summary
      Then complete duplicate measurement rows are removed
      And the source CSV files are not modified
      And the window shows counts, checks and generated files instead of a 100-row preview

    Scenario: Cancel a running batch
      Given a Reference Summary batch is running
      When the engineer cancels the batch
      Then no incomplete output folder is published

  Rule: CDSEM1 workbooks remain independent measurement batches

    Scenario: Summarize a CDSEM1 workbook
      Given a CDSEM1 workbook contains CD and non-CD records on its first worksheet
      When the engineer runs Reference Summary
      Then only ACD_No=CD records from the first worksheet are summarized
      And the workbook produces CD Pivot, CD Results and Checks sheets
      And the source workbook is not combined with another CDSEM1 workbook
