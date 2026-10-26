# Executable examples: tests/test_excel_export.py
Feature: Export analysis with editable Excel charts or Matplotlib pictures
  # Layout automation: tests.test_excel_report_layout.ExcelReportLayoutTests
  Scenario: Find exported plots immediately after opening a large report
    Given NOVA contains 7731 original measurement rows
    When the analyst opens either completed export
    Then Match Original opens at the first parameter with its data visible
    And its raw source rows remain unchanged above the parameter blocks

  Scenario: Keep complete identity labels after Excel redraws its chart
    Given a NOVA parameter contains several Groups and 255 measurement identities
    When the export is opened and redrawn in Excel
    Then Group and Wafer captions are not repeated for each data point
    And short neighboring Groups retain their names with separated captions
    And dense Wafer names may be sampled without dropping source rows
    And Matplotlib Trend and Bias include real Die Seq ticks and separated identity captions

  Scenario: Change a native Match chart's selected data range
    Given a Match chart contains scatter points and an Excel linear trendline
    When the analyst selects the scatter series and changes its X and Y ranges
    Then its points follow the newly selected cells on the same sheet
    And Excel recalculates its trendline from the edited series

  # Executable examples: tests.test_excel_report_layout.ExcelReportLayoutTests
  Scenario: Read the full numeric range without excessive X padding
    Given the drawable X values are 10, 10.1 and 10.2
    And an unpaired source row has X 999 and no Y value
    When either renderer exports the numeric plot
    Then its X range is 9.995 to 10.205 without cropping any plotted points
    And the unpaired source row remains in the data table
    And native axis labels retain the decimal boundary precision

  Scenario: Distinguish Reference and Raw Data on exported Trends
    Given a Trend compares Reference and Raw Data in either selection order
    When either renderer exports the Trend
    Then the orange Reference is a solid line above Raw Data
    And the report retains the source records in their original table order
    And points, strokes and all four frame edges are visible at the requested size

  # Executable examples: tests.test_v4_release_exports.ReleaseExportTests
  Scenario: Navigate the three Match views without redundant sheets
    Given NOVA contains Head A and Head B with their own source rows
    When either renderer exports the Workbook
    Then Match Original uses Die ticks in original source-row order
    And Match Group uses only Group captions at a tight proportional width
    And Match Group show Wafer uses the WKB Show Wafer choices
    And Match Wafer collects contiguous Wafer identities with sparse captions
    And the individual group sheets retain Head A and Head B in their names
    And no separate Original, Match, Group Fits, Order or All Trend sheet is added

  Scenario: Trace grouped reports back to Original
    Given Original rows alternate between W1 and W2 in Head A and Head B
    When the grouped Workbook is exported in either mode
    Then Match Original retains the source strings and original row order
    And grouped parameter tables collect each Group and Wafer, Lot and PAD identity
    And their PMISH values reference the matching Match Original source row
    And the source document and its selected plotting order remain unchanged

  Scenario: Separate group-only and Wafer-expanded Group reports
    Given Old and New groups have different point counts
    And only New MM1 and New MM2 are set to Show Wafer
    When the grouped Workbook is exported in either mode
    Then Match Group uses only Group captions and the smallest Group sets the tight scale
    And larger Groups keep widths proportional to their plotted point counts
    And Group captions are single-line and centred without leader lines
    And Match Group show Wafer appears for both stages
    And Groups without Show Wafer keep their Match Group widths
    And Show Wafer Groups expand to fit every Wafer label and complete separator line
    And every individual Group Match shows all of its Wafers regardless of Show wafer
    And Show wafer only chooses which individual Group detail appears in the combined view
    And the selectively expanded combined Native report retains the caption numeric x scale
    And uniformly spaced Group-only and Wafer reports use their parameter block's Die Seq categories
    And their X and Y values remain bound to cells for draggable Excel ranges
    And automatic internal numeric x tick text remains hidden
    And sparse cell-linked Die Seq ticks remain below the plot

  # Executable examples: tests.test_export_native_die_categories
  Scenario: Select native Die Seq ranges without changing exported geometry
    Given a Group-only, Wafer, individual Group or all-Show-Wafer combined report
    And its existing point and footer geometry is uniformly spaced
    When native Excel charts are exported
    Then Trend, Bias and Bias percent categories reference each parameter's own Die Seq column
    And leading zeros, repeated Die values, row order and editable Y sources are preserved
    And the Die Seq source outline can be dragged in Excel
    And the existing point positions, sparse tick drawings, captions, boundaries and dimensions remain unchanged
    But mixed Show Wafer or nonuniform label and missing-pair layouts keep the existing numeric XY scale

  Scenario: Read a separate Wafer report without changing Original
    Given original rows alternate between W2 and W1 across different Groups
    When the Workbook is exported in either mode
    Then Match Original contains unchanged source data above its parameter plots
    And a separate matched Reference area leaves its literal Raw Data columns intact
    And Match Wafer collects W2 before W1 with original row order within each Wafer, Lot and PAD identity
    And Match Wafer PMISH and Reference values reference the matching Match Original source rows
    And its Trend and Bias use compact expanded Wafer captions without a Group overview
    And every available stage has its own Match Original and Match Wafer sheets

  Scenario: Edit native Trend ranges without hidden plot coordinates
    Given a parameter contains repeated measurements of Wafer W1
    When the Workbook is exported with native Excel charts
    Then Trend and Bias reference their visible parameter values and identity columns
    And their ordinary Excel data-range selections remain editable
    And charts use square corners and the Excel chart theme with an orange Reference line
    And contiguous records of the same Wafer, Lot and PAD share one merged Wafer caption
    And the original Raw Data cells remain unmerged and unchanged

  Scenario: Export legible content-tight panels
    Given a NOVA Workbook has several Wafers in Head A and Head B
    When the Workbook is exported in either mode
    Then each Match panel is 15 cm wide and 11 cm high
    And Trend and Bias panels are 11 cm high and expand to fit visible labels
    And Match Wafer keeps every Group and Wafer in one complete Trend and Bias chart
    And Match Wafer never splits the data into Page x/y panels
    And Die Seq ticks are sampled within each visible Wafer span instead of globally skipping whole spans
    And numeric Trend and Bias axes show one Die Seq title
    And Match Original retains its 25 cm Die Seq baseline
    And a Group without visible Wafers scales from the tightest Group before using record proportions
    And a Group with visible Wafers scales from the complete Wafer labels inside that Group
    And visible Wafer, Lot and PAD fields are never omitted to force a narrower panel
    And Group and Wafer widths match between the two export renderers
    And long identity charts keep a 3 cm left margin and a 0.7 cm right margin
    And Match chart panels keep a 1 cm horizontal gap and a 5 mm vertical gap
    And Trend and Bias axes leave marker headroom beyond every plotted value
    And Group and Wafer separator bars sit below, detached from the coordinate axes
    And identity captions never use leader lines
    And Wafer views do not add a redundant Wafer axis title
    And independent panels align with the full-width parameter heading
    And ordinal horizontal limits leave only a small margin around the observations

  Scenario: Export consistent Trend and Bias strokes
    Given an analysis contains Trend, Bias and Bias percent data
    When the Workbook is exported as editable charts or Matplotlib pictures
    Then every data curve uses a 2.5 pt line and 6 pt circle markers
    And a secondary Trend axis uses the same stroke and marker size
    And Match fits, Correlation fits, zero baselines and Bias limits keep their auxiliary styles

  Scenario: Stack Match identity panels for wide Trends
    Given a Match parameter has Match, Trend, Bias and optional Bias percent
    When the Workbook is exported in either mode
    Then Match occupies the left square panel
    And Trend, Bias and Bias percent stack vertically to its right
    And every right-hand panel starts at the same left coordinate
    And the next parameter begins below the complete panel group

  Scenario: Choose an export renderer
    Given an analysis has selected measurements and software fitted results
    When the analyst chooses Export Excel or Export Matplotlib
    Then both exports contain the same source strings and numerical data
    And Export Excel contains editable charts bound to cells
    And Export Matplotlib embeds pictures in one Excel file without separate PNG files
    And generated labels are English with Times New Roman as the default font

  Scenario: Export both available stages
    Given Preview and Final have their own matching source tables
    When the Workbook is exported
    Then Preview sheets end with (WO Card)
    And Final sheets end with (W Card)
    And Final values are not calibrated a second time

  Scenario: Read a compact Match report beside its charts
    Given Preview contains PMISH and NOVA measurements for Wafer W1
    When the Workbook is exported in either mode
    Then Match Original begins with its original Raw Data at A1
    And each parameter table contains Wafer, Die Seq, PMISH, PMISH+Card, NOVA, Bias and Bias %
    And Group is included only when grouping is enabled
    And Wafer captions follow the plot label choices
    And charts sit to the right of their parameter data and align at the top
    And Reference, Summary, Raw Data and Preview are not separate visible sheets

  Scenario: Read accepted Final measurements without a duplicate Card column
    Given Final contains accepted PMISH measurements
    When the Workbook is exported
    Then its parameter tables have no PMISH+Card column
    And its Bias uses the accepted values without applying a Card again

  Scenario: Export only mapped FullMap Trends
    Given a TEM FullMap contains CD and an unmapped Other column
    And Parameter mapping includes only CD
    When the Workbook is exported in either mode
    Then FullMap contains its own data and the CD Trend
    And the Other column is not plotted
    And successful software Wafer Map and Radius pictures are placed on FullMap beside the data

  # Executable examples: tests.test_v4_release_exports.ReleaseExportTests
  Scenario: Keep NOVA and KLA FullMap focused on maps and radius
    Given a NOVA or KLA analysis has successfully drawn Wafer Map and Radius
    When either renderer exports FullMap
    Then those software PNGs have a fixed physical height with their aspect ratio preserved
    And no additional FullMap Trend is added

  Scenario: Read Dynamic results in one aligned view
    Given Dynamic has selected parameters with Cycle and Die measurements
    When either renderer exports Dynamic
    Then literal source data is on the left of one Dynamic sheet
    And each parameter's Cycle by Die table is stacked in the middle
    And its 3 Sigma chart aligns to that table's top on the right
    And a grouped 3 Sigma summary starts at the top farther right
    And per-Die Cycle trends are omitted from the export while remaining available in the application
    And native tables reference the raw cells and retain sample standard deviation

  Scenario: Compare positive and negative Bias fairly
    Given Bias contains unequal positive and negative extremes
    When either renderer exports Bias or Bias percent
    Then its lower Y limit is the negative of its upper Y limit

  Scenario: Export independent child analyses
    Given a named child window has its own data and successful drawing choices
    When that window is exported
    Then its own selected curves and software statistics are exported
    And Wafer Map and Radius reuse the current software PNG
    And the source document and its selection remain unchanged

  Scenario: Cancel while writing an existing export
    Given a complete export already exists
    When the analyst cancels while the replacement is being written
    Then the previous complete export remains intact
    And incomplete temporary files are removed safely

  Scenario: Cancel a large report while its parameter tables are being prepared
    Given a previous complete export exists
    When the analyst cancels while a parameter's progress is shown in either renderer
    Then preparation stops without completing the remaining parameter reports
    And the previous complete export remains intact

  Scenario: Keep the previous report after a disk-write failure
    Given a previous complete export exists
    When writing its replacement fails after a partial temporary file is created
    Then the previous complete export remains intact
    And the partial export is removed
