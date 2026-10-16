# Executable examples: tests/test_excel_export.py
Feature: Export analysis with editable Excel charts or Matplotlib pictures
  # Layout automation: tests.test_excel_report_layout.ExcelReportLayoutTests
  Scenario: Trace grouped reports back to Original
    Given Original rows alternate between W1 and W2 in Head A and Head B
    When the grouped Workbook is exported in either mode
    Then Original retains the source strings and original row order
    And grouped parameter tables collect each Group and Wafer, Lot and PAD identity
    And their PMISH values reference the matching Original source row
    And the source document and its selected plotting order remain unchanged

  Scenario: Read a separate Wafer report without changing Original
    Given original rows alternate between W2 and W1 across different Groups
    When the Workbook is exported in either mode
    Then Original contains source data in its unchanged original order and no plots
    And a separate matched Reference area leaves its literal Raw Data columns intact
    And Wafer collects W2 before W1 with original row order within each Wafer, Lot and PAD identity
    And Wafer PMISH and Reference values reference the matching Original source rows
    And its Trend and Bias use compact expanded Wafer captions without a Group overview
    And every available stage has its own Original and Wafer sheets

  Scenario: Edit native Trend ranges without hidden plot coordinates
    Given a parameter contains repeated measurements of Wafer W1
    When the Workbook is exported with native Excel charts
    Then Trend and Bias reference their visible parameter values and identity columns
    And their ordinary Excel data-range selections remain editable
    And charts use square corners and the Excel chart theme with an orange Reference line
    And contiguous records of the same Wafer, Lot and PAD share one merged Wafer caption
    And the original Raw Data cells remain unmerged and unchanged

  Scenario: Export legible physical-size panels
    Given a NOVA Workbook has several Wafers in Head A and Head B
    When the Workbook is exported in either mode
    Then each Match panel is 15 cm wide and 11 cm high
    And Trend and Bias panels are 11 cm high and at least 25 cm wide
    And the Group overview precedes separate Wafer detail panels with every identity caption
    And independent panels align with the full-width parameter heading
    And ordinal horizontal limits leave only a small margin around the observations

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
    Then Match begins with its original Raw Data at A1
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
    Given FullMap contains CD and an unmapped Other column
    And Parameter mapping includes only CD
    When the Workbook is exported in either mode
    Then FullMap contains its own data and the CD Trend
    And the Other column is not plotted
    And successful software Wafer Map and Radius pictures are placed on FullMap beside the data

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
