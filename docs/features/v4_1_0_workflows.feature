Feature: Reversible table views and unambiguous plot inspection
  # Automation: RenderPreparationTests
  # Automation: WorkbookPerformanceTests.test_correlation_checkbox_changes_keep_exact_sources_and_are_prompt
  # Automation: WorkbookPerformanceTests.test_saved_correlation_restores_complete_grouped_plots_promptly
  Scenario: Prepare a wide comparison without dropping measurements
    When a source parameter or Wafer selection changes
    Then every enabled curve box and source-qualified selection remains exact
    And drawing and restoring retain all selected points and source rows
    And shared label preparation does not repeat for each Wafer or parameter

  # Automation: V41Workflows.test_hidden_participation_is_reversible_and_edits_only_visible_source_rows
  # Automation: V41Workflows.test_partial_paste_maps_noncontiguous_visible_rows_and_undo_restores_them
  # Automation: V41Workflows.test_hidden_table_captions_report_visible_and_total_rows
  Scenario: Edit only visible records without deleting excluded measurements
    Given Groups Data selection excludes some Workbook records
    When Hide excluded rows in tables is checked and Apply is chosen
    Then Order, Reference and Raw Data show only participating source rows
    And their size captions distinguish visible records from the complete source row count
    And original row numbers and measurement strings are retained
    When fewer replacement rows are pasted starting at a visible row
    Then only those visible rows are modified and Undo restores them
    And a paste beyond the remaining visible rows is rejected before any write
    When Hide excluded rows is unchecked and Apply is chosen
    Then the complete source table becomes visible again without reselecting excluded records

  # Automation: V41Workflows.test_partial_visible_paste_keeps_counts_and_unhide_restores_untouched_rows
  # Automation: V41Workflows.test_workbook_captions_follow_replacement_growth_and_undo
  # Automation: V41Workflows.test_order_caption_keeps_actual_rows_when_a_draft_has_more_flags_than_raw
  # Automation: V41Workflows.test_analysis_table_sizes_refresh_on_edits_without_waiting_for_recognition
  # Automation: V41Workflows.test_correlation_reference_size_refreshes_on_edits_replacement_and_undo
  # Automation: V41Workflows.test_analysis_counts_include_blank_source_rows_and_survive_invalid_headers
  # Automation: V41Workflows.test_linked_analysis_captions_distinguish_visible_rows_from_total
  Scenario: Table dimensions follow live source content and visibility
    Given a Workbook or analysis table contains editable source records
    When content is pasted, replaced, extended or undone
    Then its row and column counts update without waiting for a plot refresh
    And hidden tables distinguish visible rows from total source rows
    And original source row labels are not mistaken for the visible row count
    And loaded blank source rows are retained but reserved editing cells are not counted
    And incomplete tables and invalid headers do not leave stale dimension captions

  # Automation: HiddenRowMarkerTests
  # Automation: V41Workflows.test_partial_paste_maps_noncontiguous_visible_rows_and_undo_restores_them
  # Automation: V41Workflows.test_partial_exclusion_refreshes_map_and_radius_membership_without_reloading_sources
  Scenario: Notice collapsed rows between visible measurements
    Given Data selection hides a contiguous source-row interval
    Then its boundary has an amber dashed separator and a fold mark beside the row number
    And hovering the separator or row-number header explains the hidden count and original row range
    And the marker is legible in light and dark themes
    And the same markers apply in Workbook tables and linked analysis tables
    And sorting visible records does not incorrectly label those records as hidden
    And revealing all rows removes the markers
    And no placeholder records are inserted or copied
    And pasting and Undo still address the same original visible rows

  # Automation: V41Workflows.test_hidden_selection_survives_workspace_restore_and_unhide_in_child
  Scenario: Linked analysis editors follow the same visibility policy
    Given a Wafer Map or Correlation and Trend window follows Match WKB selection
    Then it keeps complete source data and follows the Workbook's hide preference
    And Full data shows every record without discarding local edits
    And saving and reopening retains the hide choice and source row mapping

  # Automation: V41Workflows.test_statistics_are_default_hover_not_a_checkbox_or_title
  # Automation: RequestedPlotControlsTests.test_match_points_and_sequence_curves_keep_die_metadata_and_full_statistics
  Scenario: Inspect summaries without covering measurements
    When the pointer is over empty space in a Trend or Bias plot
    Then the tooltip shows finite-data Mean, sample sigma, Min and Max
    When the pointer is over a data point
    Then Die, X and Y take priority
    And leaving the point restores the summary
    And no statistics checkbox or title annotation is needed
    And Wafer boundaries are thin grey lines behind the curves while Group boundaries stay thick black

  # Automation: V41Workflows.test_group_and_all_parameter_trend_cards_are_exclusive_and_use_distinct_fits
  Scenario: Choose one Trend calibration source
    When All-parameter Card is chosen the Trend uses the overall fit
    When Group Card is chosen the Trend uses its own Group plots fit
    Then the two choices are mutually exclusive and no calibration is applied twice

  # Automation: V41Workflows.test_raw_card_floats_and_returns_with_the_same_live_editor
  Scenario: Float the live Raw Data editor
    When Raw Data is double-clicked outside its table
    Then it becomes a non-modal topmost tool window with the same editor and Undo history
    When it is double-clicked again or the tool window is closed
    Then it returns to its original layout without closing or copying the document

  # Automation: V41Workflows.test_decimals_round_half_up_and_are_global_not_workspace_state
  Scenario: Round point labels using the application preference
    Given Decimals defaults to two and can be set from zero to ten
    Then decimal ties round half up, including negative measurements
    And the preference is stored in Settings and shared by open Wafer Maps
    And opening a Workbook cannot replace it, even if the old file contains a decimal preference
