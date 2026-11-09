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

    Scenario: Read surplus trailing empty fields and consolidate LBH flags
      Given NOVA data records have extra trailing empty CSV fields
      When the engineer runs Reference Summary
      Then all declared measurement values and original source row identities are retained
      And extra nonempty fields and short records still produce errors
      And the original _LBH columns are replaced by one LBH column
      And LBH is 0 only when all original flags are NO_LBH, otherwise it is 1

    Scenario: Choose a vendor without introductory prose
      Given the Reference Summary window is open
      Then the source panel is titled Vendor
      And the page title and introductory and vendor-processing paragraphs are absent

  Rule: CDSEM1 workbooks remain independent measurement batches

    Scenario: Summarize a CDSEM1 workbook
      Given a CDSEM1 workbook contains CD and non-CD records on its first worksheet
      When the engineer runs Reference Summary
      Then only ACD_No=CD records from the first worksheet are summarized
      And the workbook produces CD Pivot, CD Results and Checks sheets
      And the source workbook is not combined with another CDSEM1 workbook

  Rule: Coordinate comparison uses explicit one-to-one wafer links

    Scenario: Align Ref wafer blocks while Raw order is fixed
      Given Summary output has loaded into Ref and Raw Data has been pasted
      And wafers are identified by selected Wafer, Lot and PAD or Slot columns
      When the engineer drags a Ref wafer into an available Raw wafer position
      Then its complete table rows move together and that wafer pair is linked
      And Raw wafer order remains fixed unless the engineer unlocks it
      And a wafer cannot be used in two links

    Scenario: Compare sorted coordinates with different source units
      Given explicitly linked Ref and Raw wafers have chosen absolute coordinates and units
      When the engineer sorts each wafer by X then Y in the chosen directions
      Then both source tables reorder whole rows and retain their source row identities
      When the engineer plots coordinate Bias
      Then Ref is converted into the selected Raw coordinate unit
      And each linked wafer has one Trend with X and Y Bias equal to Raw minus Ref in that unit
      And trends follow the displayed Raw wafer order
      And unlinked wafers are not plotted
      And different point counts or missing coordinates produce a message without truncation

    Scenario: Paste Raw Data with unavailable physical coordinates
      Given Raw Data contains NA coordinates but valid FIELD X and FIELD Y indices
      When the engineer pastes into the Raw table using Ctrl+V
      Then original NA strings and wafer identities are retained
      And Field sorting works without inventing physical coordinates
      And plotting Bias reports the missing coordinates and source rows

    Scenario: Scroll linked-wafer trends
      Given linked wafer trends are drawn in two columns by default
      When the engineer uses the ordinary mouse wheel over a curve
      Then the page scrolls and the plot range is unchanged
      When the engineer holds Ctrl and uses the mouse wheel
      Then only the pointed plot zooms
      And changing the column count retains existing curves and zoom
      And no Add Compare action is offered

  Rule: Folder selection can span multiple source directories

    Scenario: Select overlapping source folders
      Given two source folders and their shared parent are selected
      When the engineer accepts the folder selection
      Then supported vendor files are scanned recursively
      And each source path is included only once
