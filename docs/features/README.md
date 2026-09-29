# Card Matching executable scenario map

`card_matching.feature` 保存业务语言；项目不额外引入 Cucumber 运行时。相同场景由现有 `unittest` 公共接口测试执行：

- Preview two mapped parameters → `MatchWorkbookTests.test_preview_generates_one_card_per_parameter_and_applies_it_lazily`
- Manually map a numeric Reference column without a suffix → `MatchingWindowTests.test_numeric_reference_columns_without_suffix_can_be_mapped_manually`
- Final data is not carded a second time → `MatchingWindowTests.test_final_mode_keeps_evaluated_values_equal_to_raw_data`
- Reopen a saved matching workbook and restore its layout/order → `MatchWorkbookTests.test_wkb_round_trip_preserves_source_tables_and_settings`, `MatchingWindowTests.test_wkb_restores_the_saved_setup_splitter_layout`, and `MatchingWindowTests.test_parameter_plot_order_survives_run_and_wkb_until_reset`
- Load an older schema 1 workbook → `MatchWorkbookTests.test_schema_one_wkb_still_opens_without_fullmap_stage_tables`
- Apply a TEM Card to a later Preview FullMap → `MatchWorkbookTests.test_preview_stage_applies_the_match_card_to_separate_fullmap_rows`
- Open Final FullMap without applying Card again → `MatchWorkbookTests.test_final_stage_uses_separate_already_carded_fullmap_without_reapplying_card` and `MatchingWindowTests.test_preview_and_final_fullmap_open_in_the_existing_wafer_workspace`
- Export a customer-facing result → `MatchingWindowTests.test_exports_excel_and_separate_plot_images_after_analysis`
- Reference-first state → `MatchingWindowTests.test_reference_is_loaded_before_raw_data_and_enables_analysis`
- Editable Reference/Raw spreadsheet grids → `MatchingWindowTests.test_reference_and_raw_inputs_are_editable_spreadsheet_grids`
- All-parameter vertical Card review with unclipped single-row plots and both Bias views → `MatchingWindowTests.test_analysis_results_share_the_scrollable_setup_workspace` and `MatchWorkbookTests.test_wkb_round_trip_preserves_source_tables_and_settings`
- Match title/equation and PMISH-versus-Match-Type Trend styling → `MatchingWindowTests.test_match_plot_uses_raw_column_title_and_shows_fit_equation` and `MatchingWindowTests.test_trend_and_bias_use_visible_point_lines`
- Preview/Final top mode tabs preserve results/layout and use independent Raw Data → `MatchingWindowTests.test_switching_preview_and_final_keeps_results_and_layout`
- Compact menu bar replaces duplicate heading/settings controls → `MatchingWindowTests.test_analysis_results_share_the_scrollable_setup_workspace`
- Raw Data paste auto-runs after the first manual analysis → `MatchingWindowTests.test_raw_table_paste_auto_runs_after_first_manual_run`
- Raw Data column changes auto-run after the first manual analysis → `MatchingWindowTests.test_raw_mapping_change_auto_runs_and_preserves_layout`
- Reference, Raw Data, and mapping edits auto-refresh without blanking results → `MatchingWindowTests.test_reference_raw_and_mapping_edits_auto_refresh_without_clearing_results`
- One parameter remains top-aligned → `MatchingWindowTests.test_a_single_parameter_plot_card_stays_at_the_top_of_results`
- Trend Card control switches between Raw and Card Value → `MatchingWindowTests.test_trend_card_checkbox_switches_between_raw_and_carded_values`
- Run analysis preserves manually dragged section boundaries → `MatchingWindowTests.test_run_analysis_preserves_the_dragged_setup_splitter_layout`
- Input-table undo → `MatchingWindowTests.test_keyboard_undo_restores_replaced_reference_and_raw_tables` and `MatchingWindowTests.test_keyboard_undo_restores_deleted_reference_and_raw_tables`
- Preserve mappings while Raw Data is missing → `MatchingWindowTests.test_clearing_raw_data_keeps_mappings_and_prompts_for_columns`
- Select every Reference parameter → `MatchingWindowTests.test_select_all_mappings_checks_every_candidate`
- Single-wafer identity and separate results tab → `MatchWorkbookTests.test_wafer_summary_uses_raw_data_measurement_identity` and `MatchingWindowTests.test_nova_shows_single_wafer_slope_and_r_squared_but_tem_does_not`
- Fit-quality threshold warnings → `MatchingWindowTests.test_mapping_results_flag_out_of_range_slope_and_r_squared` and `MatchingWindowTests.test_single_wafer_table_flags_the_same_quality_thresholds`

场景描述保持业务语义，自动化测试通过 `MatchWorkbook` 的稳定 interface 和 `MatchingWindow` 的用户可见状态验证；WKB 兼容测试不依赖 SQLite 的内部表结构。
