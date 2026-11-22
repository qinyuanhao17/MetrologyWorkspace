Feature: Review Dynamic repeatability by cycle and die
  Metrology engineers need repeat testing summarized without rebuilding an
  Excel pivot table for every parameter.

  Scenario: Infer repeated cycles from Dynamic run folders
    Given one measurement set contains repeated Die Seq rows from several Dynamic runs
    When the engineer opens the table in Dynamic
    Then a one-based Cycle column is inserted after Die Seq
    And every row from the same Dynamic run has the same Cycle

  Scenario: Fall back to repeated die order
    Given the source paths do not identify Dynamic run folders
    And each cycle repeats the same ordered Die Seq values
    When the engineer opens the table in Dynamic
    Then a new Cycle begins whenever a Die Seq repeats
    And the number of dies and cycles is not fixed to 13 by 10

  Scenario: Review selected parameters in separate scrollable sections
    Given one measurement set and DP and EW are selected in Data
    When the engineer opens the Dynamic tab
    Then no second parameter picker is shown
    And DP and EW each have their own Cycle by Die Seq table
    And every table ends with three times the sample standard deviation across cycles
    And the tables are stacked in a scrollable upper region
    And the lower region starts with one colour-coded chart comparing all selected parameters
    And the combined chart replaces its redundant title with one horizontal legend
    And the legend uses compact colour swatches
    And each parameter also has its own compact 3 Sigma chart
    And the bars do not have point markers overlaid
    And the repeated Dynamic page heading is omitted

  Scenario: Wrap compact parameter charts in rows of three
    Given one measurement set and five parameters are selected in Data
    When the engineer opens the Dynamic tab
    Then the combined chart and first two parameter charts share one row
    And the remaining three parameter charts continue on the next row

  Scenario: Keep selected parameters when Dynamic data is replaced
    Given DP and EW are selected for one Dynamic measurement set
    When a replacement table still contains DP and EW
    Then DP and EW remain selected
    And their tables and charts refresh with the replacement values

  Scenario: Do not silently average ambiguous rows
    Given a measurement set contains the same Cycle and Die Seq more than once
    When the engineer requests its Dynamic pivot
    Then the analysis reports the duplicate pair
    And no average is substituted

  # Automation: DynamicWindowTests.test_selected_die_column_drives_pivot_and_trend
  Scenario: Choose the die identifier from Wafers
    Given Dynamic data includes Die Seq and Site Order
    When the engineer chooses Site Order as the Die column
    Then the charts and pivot use Site Order to identify each die
    And reopening the Dynamic workspace restores the choice

  # Automation: DynamicWindowTests.test_pivot_edits_prefer_canonical_die_sequence_over_a_second_alias
  Scenario: Edit Dynamic measurements with two Die Sequence headers
    Given Dynamic data contains conflicting Die Seq and DieSeq columns
    When the engineer edits the displayed value for a Cycle and Die
    Then the edit updates the measurement identified by Die Seq

  Scenario: Drop outlier grid points from a Dynamic table
    Given DP has a Cycle by Die Seq table
    When the engineer selects a value cell and presses Delete
    Then that measurement point is removed from the Data sheet
    And the affected 3 Sigma values are recomputed
    And the table stays on the same scroll position and current cell

  Scenario: Undo one step without a redundant Restore button
    Given the engineer deleted several cells from a Dynamic table
    When the engineer presses Ctrl+Z
    Then only the most recent deletion is undone
    And no Restore button is shown in the parameter section

  Scenario: Correct repeat measurements without disturbing other parameter views
    Given DP and EW repeatability results and Cycle trends are displayed
    When the engineer corrects a DP measurement or undoes that correction
    Then DP statistics and its displayed Cycle curve reflect the current measurement
    And EW curves keep their zoom and chosen Die
    And the tables keep their current cells and scroll positions

  Scenario: Keep derived Dynamic cells read-only
    Given a Dynamic Cycle by Die Seq table
    Then the Cycle and Die labels are not editable
    And the 3 Sigma row is not editable

  Scenario: Read the Dynamic Trend tab as Cycle versus Die
    Given one measurement set and DP and EW are selected in Data
    When the engineer opens the Trend tab of Dynamic
    Then DP and EW each have their own interactive panel
    And Cycle runs along the bottom axis of every panel
    And every panel draws exactly one Die Seq at a time
    And a Die selector sits to the right of each panel
    And an Add Compare control can add other selected parameters for that same Die
    And no curve-box selector is required

  Scenario: Switch the Die of one Dynamic Trend panel
    Given the Dynamic Trend tab shows a panel per parameter
    When the engineer picks Die 7 in the DP panel
    Then the DP panel redraws that Die only
    And every other panel keeps the Die it was showing
    And the exported figure titles DP as DP · Die 7
    When the engineer scrolls over that Die selector
    Then scrolling down selects the next Die and scrolling up selects the previous Die
    And the page stays at its current scroll position
    And scrolling beyond the first or last Die keeps that Die selected

  Scenario: Refresh and export the Dynamic Trend panels
    Given the Dynamic Trend tab shows a Cycle panel
    When the loaded data or the Data selection changes
    Then the panels are redrawn without another command
    And the panel list keeps its scroll position
    And Copy PNG and Export PNG both use the Cycle axis and Die legends

  # Automation: RequestedPlotControlsTests.test_dynamic_comparisons_follow_the_same_die_and_export_every_curve
  Scenario: Compare multiple parameters for one Die
    Given DP and EW are selected
    When Add Compare adds EW to DP and the DP Die picker changes to Die 2
    Then both curves in DP use Die 2 and keep their original values
    And the independent EW panel keeps its selected Die
    And removing the comparison removes only that curve
    And PNG export includes every displayed comparison

  # Automation: RequestedPlotControlsTests.test_dynamic_all_dies_view_keeps_missing_gaps_and_statistics
  Scenario: Compare all Dies for the same parameter
    When the engineer switches Trend to All Dies
    Then each parameter has one plot with all of its Die curves
    And the legend identifies each Die
    And missing values remain gaps
    And Y ticks use unscaled values without an axis multiplier
    And Mean, sample sigma, Min and Max appear on empty-space hover without a title annotation


  # Automation: GrrInputTests.test_first_nine_cycles_and_thirteen_dies_fill_three_input_blocks
  Scenario: Supply Dynamic measurements to the GRR worksheet
    Given a selected parameter has ten cycles of fourteen dies
    When the engineer evaluates GRR
    Then the first nine cycles and first thirteen dies fill D12:P14, D18:P20 and D24:P26
    And Excel recalculates the assessment in the merged M96:R98 range

  # Automation: DynamicGrrWorkflowTests.test_load_grr_updates_each_plot_and_saves_each_parameter_beside_mwkb
  Scenario: Reuse the GRR template and save one report sheet per parameter
    Given the engineer loaded a GRR template and selected CD and EW
    When the engineer edits a Dynamic measurement
    Then Dynamic displays the current temporary GRR report path
    And any previously saved GRR report retains its saved values
    And the assessment updates directly below the corresponding Die Seq axis label
    And the assessment is horizontally centered on that axis label
    And the template remains available when the workbook is reopened
    When the engineer saves the Match Workbook as project.mwkb
    Then GRR_project.xlsx is saved alongside it with CD_GRR and EW_GRR sheets
    And each assessment formula is retained in the Excel report
    And the Dynamic page shows the saved Excel path and can open the file or its directory

  # Automation: DynamicGrrWorkflowTests.test_new_workbook_uses_the_installed_master_even_before_opening_the_dynamic_tab
  Scenario: Save a GRR report in a new workbook using the installed master
    Given a GRR master was previously installed
    And a new Match Workbook has selected Dynamic measurements
    When the engineer saves the workbook from the Data tab
    Then the GRR report is generated from the installed master without an import prompt
    And the installed master is unchanged
    And Dynamic shows that it is using the saved master beside Load GRR

  # Automation: DynamicGrrWorkflowTests.test_excel_lock_warns_after_saving_mwkb_and_report_can_be_retried
  Scenario: Save when Excel holds the GRR report open
    Given an existing GRR Excel report cannot be replaced
    When the engineer saves edited Dynamic measurements
    Then the Match Workbook is saved and the existing Excel report is preserved
    And Dynamic continues to show the temporary report
    And a dialog identifies the report and explains how to retry the save
