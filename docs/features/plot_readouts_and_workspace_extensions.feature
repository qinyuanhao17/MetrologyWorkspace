Feature: Read literal plotted values and reopen workspaces safely
  # Automation: StageSelectionAndPointPrecisionTests.test_loading_final_after_preview_selection_keeps_shared_participation
  # Automation: StageSelectionAndPointPrecisionTests.test_restored_head_mark_selection_survives_first_final_paste
  Scenario: Keep shared participation while populating and switching stages
    Given Preview has an applied Groups Data selection excluding some records
    When Final is first populated with the same source record identities
    And the analyst switches between Preview and Final
    Then the same excluded records remain excluded in both stages
    And temporarily clearing one stage does not reset the other stage's selection

  # Automation: StageSelectionAndPointPrecisionTests.test_precision_changes_existing_labels_without_reinterpolation
  # Automation: StageSelectionAndPointPrecisionTests.test_precision_is_an_application_preference_not_restored_from_documents
  # Automation: StageSelectionAndPointPrecisionTests.test_immediate_export_and_copy_flush_pending_precision
  Scenario: Set decimal places for Wafer Map point values
    Given point values default to two fixed decimal places
    When the analyst changes Decimals beside Opacity to a value from zero to ten
    Then existing point labels update without recalculating surfaces
    And the measurements and source row mappings are not changed
    And copied and exported pictures use the current decimal places
    And decimal ties round half up without changing measurement precision
    And the choice is saved in application Settings, not the workspace
    And opening a legacy workspace cannot replace the application choice

  # Automation: RequestedPlotControlsTests.test_match_points_and_sequence_curves_keep_die_metadata_and_full_statistics
  Scenario: Inspect Trend, Bias and Match observations
    When the pointer hovers over a plotted observation
    Then the tooltip shows its Die and actual plotted X and Y values
    And filtered or reordered observations retain their source Die
    And regression lines and zero-reference lines are not measurement points
    When the pointer is over empty plot space instead of a data point
    Then Trend and Bias show Mean, sample sigma, Min and Max in a tooltip
    And these summaries use all finite selected observations, not a display sample
    And Wafer separators are thin grey lines behind the measurements
    And Group separators remain thick black lines

  # Automation: WaferStatisticsTests.test_draws_wafer_mean_then_sigma_in_a_fixed_two_column_grid
  Scenario: Keep Wafer Mean and Sigma bars readable while widening a plot
    Given Wafer Mean and Wafer Sigma bars are drawn
    Then each title contains only the parameter and statistic name
    And the title is centred above the plot
    And individual wafer ticks and the Wafer axis title are not repeated
    And wafer identity and Group captions remain below the plot
    When the plot is widened
    Then every bar keeps the same pixel width and centre spacing
    And the exported figure omits the duplicate wafer ticks and axis title

  # Automation: PlotPointSelectionTests.test_analysis_pages_register_and_preview_the_same_source_point
  # Automation: PlotPointSelectionTests.test_wafer_maps_and_radius_paint_the_shared_linked_preview_ring
  Scenario: Follow one selected measurement across linked plots
    Given Correlation, Trend, Wafer Map and Radius Plot share a measurement table
    When the analyst clicks one measurement in any interactive chart
    Then that source measurement gets the red selected ring in the originating chart
    And every other visible chart marks the same source row with a yellow ring
    And Wafer Map and Radius Plot paint the yellow ring on the matching die
    When the analyst clicks blank chart space
    Then all linked yellow rings and the red source ring are cleared
    And linked previews use source rows without rebuilding every record identity

  # Automation: PlotPointSelectionTests.test_match_and_map_windows_keep_separate_point_selections
  # Automation: BiasDieMapTests.test_chart_selection_does_not_highlight_the_separate_bias_die_map
  Scenario: Keep plot selections in the window where the analyst made them
    Given a Match Workbook and a child window show the same measurements
    When the analyst selects a point in either window
    Then the point selection in the other window stays as it was

  # Automation: PlotPointSelectionTests.test_map_and_radius_link_the_same_die_across_parameters_inside_one_window
  Scenario: Follow the same die across parameter plots in one Wafer Map window
    Given the Wafer Map window shows several parameters for a wafer
    When the analyst clicks a die in one parameter plot
    Then that plot shows the selected die in red
    And the other parameter maps and Radius Plot in the same window show that die in yellow
    When the analyst clicks blank space
    Then the red and yellow rings disappear

  # Automation: RequestedPlotControlsTests.test_new_match_paths_migrate_but_old_wkb_and_backup_contents_remain_readable
  Scenario: Open legacy and backup files without overwriting them
    Given a Match Workbook uses the old wkb extension or is a bak backup
    When it is opened using its actual saved document type
    Then its source measurement strings remain unchanged
    And the file chooser offers backup files
    And a new Match Workbook is saved as mwkb
    And saving an opened backup requires choosing a formal document target
    And the backup cannot itself be an overwrite target
