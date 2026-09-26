# Card Matching executable scenario map

`card_matching.feature` 保存业务语言；项目不额外引入 Cucumber 运行时。相同场景由现有 `unittest` 公共接口测试执行：

- Preview two mapped parameters → `MatchWorkbookTests.test_preview_generates_one_card_per_parameter_and_applies_it_lazily`
- Manually map a numeric Reference column without a suffix → `MatchingWindowTests.test_numeric_reference_columns_without_suffix_can_be_mapped_manually`
- Final data is not carded a second time → `MatchingWindowTests.test_final_mode_keeps_evaluated_values_equal_to_raw_data`
- Reopen a saved matching workbook → `MatchWorkbookTests.test_wkb_round_trip_preserves_source_tables_and_settings`
- Load an older schema 1 workbook → `MatchWorkbookTests.test_schema_one_wkb_still_opens_without_fullmap_stage_tables`
- Apply a TEM Card to a later Preview FullMap → `MatchWorkbookTests.test_preview_stage_applies_the_match_card_to_separate_fullmap_rows`
- Open Final FullMap without applying Card again → `MatchWorkbookTests.test_final_stage_uses_separate_already_carded_fullmap_without_reapplying_card` and `MatchingWindowTests.test_preview_and_final_fullmap_open_in_the_existing_wafer_workspace`
- Export a customer-facing result → `MatchingWindowTests.test_exports_excel_and_separate_plot_images_after_analysis`
- Reference-first state → `MatchingWindowTests.test_reference_is_loaded_before_raw_data_and_enables_analysis`
- Editable Reference/Raw spreadsheet grids → `MatchingWindowTests.test_reference_and_raw_inputs_are_editable_spreadsheet_grids`
- Options invalidate stale results → `MatchingWindowTests.test_changing_analysis_options_invalidates_the_displayed_result`

场景描述保持业务语义，自动化测试通过 `MatchWorkbook` 和 `MatchingWindow` 的公开行为验证，不依赖 SQLite 表结构或 Qt 私有方法。
