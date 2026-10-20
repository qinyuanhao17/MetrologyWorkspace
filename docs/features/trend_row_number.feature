Feature: Trend without a Die Seq column
  REF and RAW choose their horizontal coordinates independently without changing source cells.

  Scenario: Draw a source that has no Die Seq column
    Given a source table with Wafer ID and numeric measurements but no Die Seq
    When the analyst draws its Trend
    Then its axis is labelled Row Number
    And the first data row is labelled 2, matching the visible sheet
    # tests.test_trend_row_number.TrendRowNumberTests.test_raw_without_die_seq_can_draw_using_sheet_row_numbers

  Scenario: Filter a wafer without renumbering observations
    When the analyst excludes another wafer
    Then remaining observations keep their original visible sheet row numbers
    And screen, PNG mirror and exported plot data use those same labels
    # tests.test_trend_row_number.TrendRowNumberTests.test_wafer_filter_keeps_gaps_in_original_visible_row_numbers

  Scenario: Only one of REF and RAW has Die Seq
    Then both sources can draw and each uses its own coordinates and axis title
    And both original source tables remain unchanged
    # tests.test_trend_row_number.TrendRowNumberTests.test_ref_and_raw_choose_coordinates_independently

  Scenario: A supplied Die Seq column contains blank values
    Then its existing missing-value rules remain unchanged
    # tests.test_trend_row_number.TrendRowNumberTests.test_present_but_blank_die_seq_does_not_silently_change_semantics
