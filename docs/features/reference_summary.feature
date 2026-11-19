Feature: Summarize multi-vendor reference exports
  Metrology engineers need a consistent, checked batch output from vendor files
  without changing the original measurements or crowding the desktop with raw rows.

  Rule: A summary run publishes only complete checked output

    Scenario: Summarize a NOVA batch
      Given one or more NOVA CSV exports are selected
      When the engineer runs Reference Summarizer
      Then complete duplicate measurement rows are removed
      And the source CSV files are not modified
      And the window shows counts, checks and generated files instead of a 100-row preview

    Scenario: Cancel a running batch
      Given a Reference Summarizer batch is running
      When the engineer cancels the batch
      Then no incomplete output folder is published

    Scenario: Read surplus trailing empty fields and consolidate LBH flags
      Given NOVA data records have extra trailing empty CSV fields
      When the engineer runs Reference Summarizer
      Then all declared measurement values and original source row identities are retained
      And extra nonempty fields and short records still produce errors
      And the original _LBH columns are replaced by one LBH column
      And LBH is 0 only when all original flags are NO_LBH, otherwise it is 1

    Scenario: Choose a vendor without introductory prose
      Given the Reference Summarizer window is open
      Then the source panel is titled Vendor
      And the page title and introductory and vendor-processing paragraphs are absent

  Rule: CDSEM1 workbooks remain independent measurement batches

    Scenario: Summarize a CDSEM1 workbook
      Given a CDSEM1 workbook contains CD and non-CD records on its first worksheet
      When the engineer runs Reference Summarizer
      Then only ACD_No=CD records from the first worksheet are summarized
      And the workbook produces CD Pivot, CD Results and Checks sheets
      And the source workbook is not combined with another CDSEM1 workbook

    Scenario: Read a confirmed single wafer without identity columns
      Given a single-wafer CDSEM1 file has no Wafer_ID or Lot_ID columns
      When the engineer runs Reference Summarizer
      Then both identity columns remain empty and chips are grouped by Chip_X and Chip_Y
      And MP names retain their spelling, case and first appearance order
      And CD Pivot retains its Common and per-MP field groups
      And CD Results, Results CSV and Checks describe the same measurements

    Scenario: Reject ambiguous measurements instead of overwriting them
      Given CDSEM1 records have the same chip and MP name
      When only their SourceRow values differ
      Then only the first complete measurement is retained
      When their measurement values differ
      Then that source file fails with a conflict report
      And blank MP names or Chip coordinates also fail with their source rows

  Rule: All vendors accept CSV and first-sheet Excel input

    Scenario: Read equivalent vendor records through either transport
      Given equivalent NOVA, PMISH, KLA or CDSEM1 records in CSV, XLSX and XLSM
      When the engineer selects files or scans source folders
      Then all three formats are available
      And parsing produces the same measurements and vendor field order
      And other Excel worksheets and temporary lock files are ignored
      And source files remain unchanged

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
      And the window reports missing physical coordinates

    Scenario: Compare common points in wafer links of different lengths
      Given at least one linked wafer has more Ref points than Raw points
      When the engineer plots coordinate Bias
      Then only points with uniquely matching Field X and Field Y are compared in that link
      And other valid linked wafers still have their own Trends
      And the original worksheet rows are retained

    Scenario: Paste Raw Data with unavailable physical coordinates
      Given Raw Data contains NA coordinates but valid FIELD X and FIELD Y indices
      When the engineer pastes into the Raw table using Ctrl+V
      Then original NA strings and wafer identities are retained
      And Field sorting works without inventing physical coordinates
      And plotting Bias reports the missing coordinates and source rows

    Scenario: Scroll linked-wafer trends
      Given linked wafer trends are drawn in three columns by default
      When the engineer uses the ordinary mouse wheel over a curve
      Then the page scrolls and the plot range is unchanged
      When the engineer holds Ctrl and uses the mouse wheel
      Then only the pointed plot zooms
      And changing the column count retains existing curves and zoom
      And a sparse grid keeps each plot the same size with space to the right and below
      And no Add Compare action is offered

  Rule: Folder selection can span multiple source directories

    Scenario: Select overlapping source folders
      Given two source folders and their shared parent are selected
      When the engineer accepts the folder selection
      Then supported vendor files are scanned recursively
      And each source path is included only once
      And only checked source files are summarized

  Rule: Ref output selection keeps independent working data

    Scenario: Switch between earlier Ref outputs
      Given two earlier summary CSVs are loaded as Ref outputs
      And each output has its own edited Raw Data and plotted wafer links
      When the engineer chooses an output from either Wafer Alignment or XY Bias
      Then both Ref output selectors show the chosen absolute path
      And that output's Raw Data, links and trends are restored
      And Data and the analysis tabs use that output's successful alignment

    Scenario: Switch to a Ref output before plotting XY Bias
      Given the current Ref output has been plotted and another has not
      When the engineer chooses the unplotted output
      Then the analysis tabs remain available and Data is empty
      When Plot XY Bias succeeds for the new output
      Then Data immediately shows the new matched rows in original Raw order

    Scenario: Reopen a saved Reference workspace
      Given the Ref outputs have distinct Raw tables, links, mappings and plot states
      When the engineer saves a .ref file and reopens it without the original Ref CSVs
      Then the saved Ref and Raw worksheet values and original row identities are recovered
      And each output retains its own plotted or unplotted state
