# Each scenario is connected to executable public-seam tests, not documentation alone.
Feature: Prepare AutoWeighting tables from local screenshots
  Scenario: Local recognition needs no network or model download
    Given the complete pinned local OCR package
    When the application recognizes a generated numeric text crop with networking forbidden
    Then it returns the numeric text without downloading a model
    # tests.test_auto_weighting_ocr.GridTests.test_real_bundled_recognizer_works_with_network_and_downloads_forbidden

  Scenario: Pasted screenshots are recognized in the application
    Given a screenshot pasted into AutoWeighting Writer
    When local background recognition finishes and I accept its review dialog
    Then recognized fields appear in the appropriate editable table
    # tests.test_auto_weighting_window.WriterWindowTests.test_clipboard_paste_keeps_image_as_source_without_recognizing_manually
    # tests.test_auto_weighting_window.WriterWindowTests.test_background_ocr_applies_only_after_review_dialog_acceptance

  Scenario: Scrolling screenshots overlap and disagree
    Given Step rows with consistent exact-name anchors
    When another capture disagrees on a name or value in the overlap
    Then rows are not duplicated and both candidates remain for explicit review
    # tests.test_auto_weighting.WriterDataTests.test_merge_overlapping_rows_and_keep_conflicting_candidates
    # tests.test_auto_weighting.WriterDataTests.test_overlap_anchors_keep_name_ocr_disagreement_as_conflict_not_duplicate_row

  Scenario: Blank, missing and constrained fields are not invented
    Given high precision numbers, an observed empty Fix cell and an uncollected step
    When I save or export the transcriptions
    Then precision, visible blank and uncollected states stay distinct
    And constraint text is never executed or made into an Excel formula
    # tests.test_auto_weighting.WriterDataTests.test_preserves_precision_minus_and_visible_blank
    # tests.test_auto_weighting.WriterDataTests.test_validation_never_executes_or_repairs_expression
    # tests.test_auto_weighting.WriterDataTests.test_excel_preserves_literal_formula_and_marks_missing_collection

  Scenario: Corrections are reversible and survive reopening
    Given screenshots and reviewed corrections in the two tables
    When I save and reopen a Writer project
    Then source evidence and literal values are unchanged
    And cancelling a close preserves unsaved edits
    # tests.test_auto_weighting_window.WriterWindowTests.test_workspace_roundtrip_keeps_screenshot_and_literal_strings
    # tests.test_auto_weighting_window.WriterWindowTests.test_cancel_close_keeps_edited_table
    # tests.test_auto_weighting_window.WriterWindowTests.test_edit_copy_undo_and_review_preserve_decimal_text

  Scenario: Cancelling recognition cannot partially change a table
    Given local OCR is running in the background
    When I cancel or close its window
    Then recognition cooperatively stops without applying a partial result
    # tests.test_auto_weighting_window.WriterWindowTests.test_cancelling_background_ocr_preserves_sources_and_existing_table
    # tests.test_auto_weighting_window.WriterWindowTests.test_close_during_ocr_waits_for_cooperative_cancellation
    # tests.test_auto_weighting_window.WriterWindowTests.test_failed_batch_merge_does_not_partially_apply
