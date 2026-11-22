Feature: Summarize multi-vendor reference exports
  Metrology engineers need a consistent, checked batch output from vendor files
  without changing the original measurements or crowding the desktop with raw rows.

  Rule: A summary run publishes only complete checked output

    Scenario: Summarize a NOVA batch
      Given one or more NOVA CSV exports are selected
      When the engineer runs Reference Summarizer
      Then complete duplicate measurement rows are removed
      And the source CSV files are not modified
      And channels, files, issues, provenance and schemas are sheets in one Excel report
      And an HTML summary lists vendor metadata beside the measurement output
      And the measurement CSV name identifies the wafer, lot and PAD where available
      And the output folder name includes the original measurement date where available
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

    Scenario: Reorder Ref to match Raw
      Given the Ref and Raw wafers have explicit links
      When the engineer clicks Raw order on Wafer Alignment
      Then linked Ref wafer blocks follow the current Raw wafer order
      And uniquely matched Field X/Y points follow Raw order within the linked wafers
      And an equal-length pair keeps its point order when those positions cannot all be matched uniquely
      And the Raw table, source row identities and wafer links are preserved

    Scenario: Reorder Raw to match Ref
      Given the Ref and Raw wafers have explicit links
      When the engineer clicks Ref Order on Wafer Alignment
      Then linked Raw wafer blocks and their uniquely matched points follow the current Ref order
      And the Ref table, source row identities and wafer links are preserved
      And the sorting toolbar has no success message after a successful reorder

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

    Scenario: Plot labelled coordinate text and sequence numbers
      Given the input uses Seq for Die Seq and supplies X/Y coordinates with axis prefixes
      When the engineer draws XY Bias, Trend, WaferMap or Radius
      Then the plot reads Seq as the die identifier and extracts the signed coordinate values
      And the original coordinate strings, die labels and source row identities are preserved
      And each XY Bias panel title identifies only the linked Raw wafer
      And selecting one XY Bias point immediately marks every linked panel and analysis plot

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

    Scenario: Edit Ref and Raw tables with Match Workbook navigation
      Given the engineer opens Wafer Alignment with Ref and Raw measurements
      When the engineer presses Ctrl+Shift+Arrow in either measurement table
      Then the selection extends to the next populated data boundary
      When the engineer double-clicks a row number
      Then the same row is selected and revealed in the other table
      When the engineer holds Ctrl and scrolls either table
      Then both measurement tables keep aligned scroll progress

    Scenario: Summarize metadata when loading an existing Ref CSV
      Given an existing Ref output CSV includes instrument and wafer metadata
      When the engineer loads its folder from the Summary tab
      Then an HTML summary is written beside the CSV with instrument and recipe information first
      And choosing a Ref output in the Summary tab shows that output's HTML and selects it in the analysis tabs
      And opening an HTML summary shows it inside the Summary tab
      And the selected output's folder path and files are visible in the Summary tab
      And the selected CSV and any preexisting notes are preserved

    Scenario: Switch between earlier Ref outputs
      Given two earlier summary CSVs are loaded as Ref outputs
      And each output has its own edited Raw Data and plotted wafer links
      When the engineer chooses an output from either Wafer Alignment or XY Bias
      Then both Ref output selectors show the chosen absolute path
      And that output's Raw Data, links and trends are restored
      And the analysis tabs use that output's successful alignment

    Scenario: Switch to a Ref output before plotting XY Bias
      Given the current Ref output has been plotted and another has not
      When the engineer chooses the unplotted output
      Then the analysis tabs remain available with empty data tabs
      When Plot XY Bias succeeds for the new output
      Then Data immediately shows the new matched rows in original Raw order

    Scenario: Plot only reference measurements in WaferMap and Radius
      Given the current Ref output has been plotted in XY Bias
      When the engineer draws a plot on Ref WaferMap or Ref Radius Plot
      Then the plot uses the aligned Ref measurements
      When the engineer applies Data selection from the Data menu
      Then the analysis tabs and XY Bias use the same included rows for this output
      And hiding unchecked rows leaves the original aligned tables intact

    # Automation: ReferenceAlignmentTests.test_invalid_saved_group_options_leave_current_reference_document_intact
    Scenario: Reject invalid saved Group settings without changing the open Reference workspace
      Given the engineer already has a Reference workspace open
      When another workspace cannot be opened because its Group settings are invalid
      Then the open workspace retains its data and save location

    # Automation: ReferenceAlignmentTests.test_analysis_data_waits_for_plot_and_copies_reference_in_raw_input_order
    Scenario: Use Raw coordinates for paired Reference plots
      Given Ref and Raw have been aligned and each has its own original Die identifiers
      Then Raw Data displays the original Raw columns in their original column order
      And Ref Data includes the aligned Wafer, Die and coordinate columns
      When the engineer chooses a different Die column on the Raw side
      Then both Trend sources use that Raw Die column for their paired rows
      And the Ref WaferMap and Radius use the aligned Raw X and Y coordinates

    Scenario: Reopen a saved Reference workspace
      Given the Ref outputs have distinct Raw tables, links, mappings and plot states
      When the engineer saves a .ref file and reopens it without the original Ref CSVs
      Then the saved Ref and Raw worksheet values and original row identities are recovered
      And each output retains its own plotted or unplotted state
      And saving the workspace does not generate a new HTML summary

    Scenario: Choose Y axes for Trend comparisons
      Given the engineer has overlaid two parameters in Trend
      When the engineer chooses automatic, always one, or always two Y axes in the Analysis menu
      Then the Trend redraws using that choice
      And saving and reopening the Reference workspace restores the choice and automatic median ratio threshold

    Scenario: Name a Reference workspace with local date and time
      Given the engineer is saving a new Reference workspace
      When the naming dialog opens
      Then Date and Time is prefilled from the local clock
      And File Name previews the vendor and wafer identity with that minute
      When the engineer changes the date and time
      Then the suggested Reference filename updates in the same dialog
      And only the Reference workspace is written

    Scenario: Use Match Workbook Groups in Reference analysis
      Given linked Ref and Raw measurements are plotting in the analysis tabs
      When the engineer opens Group settings from the Groups menu
      Then the same Head, Mark, Group and Plot labels controls used by Match Workbook are available
      And every Group settings column can be filtered, including TestFlag, Head, Mark and Group
      And Set Test Flag is available and right-click flag changes update the same settings
      When the engineer enables Groups and applies them
      Then Trend, Wafer Mean / Sigma and plot labels use the selected classification
      When the engineer opens Manage groups and selects Show Wafer
      Then wafer identity captions and group boundaries follow that selection
      And saving and reopening the Reference workspace restores the grouping choices

    # Automation: ReferenceAlignmentTests.test_replacement_reference_rows_use_their_own_test_flags
    Scenario: Group replacement Raw measurements by their own TestFlag
      Given a Reference analysis already has applied Groups
      When the engineer replaces the Raw measurements with values containing different TestFlags
      Then the affected measurements are grouped using the replacement TestFlags
