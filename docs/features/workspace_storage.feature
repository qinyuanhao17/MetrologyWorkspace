Feature: Durable metrology workspaces
  Engineers keep source measurements and analysis choices in one portable document
  so that analysis can resume without the original CSV or Excel files.

  # Automation: tests.test_storage_v2.StorageV2Tests, tests.test_workspace_store.WorkspaceStoreTests,
  # and tests.test_workbook_startup.WorkbookStartupTests
  Rule: Workbook settings are confirmed before opening the analysis

    # test_cancelled_launch_does_not_leave_a_workbook_window
    Scenario: Cancel creating or opening a Workbook
      Given the engineer launched Match Workbook from the main window
      When the engineer cancels the startup choice
      Then no empty Workbook window remains open

    # test_new_workbook_uses_confirmed_settings_before_the_window_opens
    Scenario: Create a Workbook with initial analysis choices
      Given the engineer selects New Workbook
      When the engineer confirms TEM and an automatic axis ratio of 3.125
      Then the new Workbook uses those choices and awaits measurement input

    # test_open_dialog_prefills_and_restores_the_files_analysis_settings
    Scenario: Review a saved Workbook's settings
      Given the engineer selected an existing Match Workbook
      When the engineer reviews its Analysis settings
      Then the settings initially match the file
      And the engineer can restore saved choices after changing them
      And at least one Bias view is required to confirm

    # test_open_settings_are_unsaved_until_the_workbook_is_saved
    Scenario: Open with revised Analysis settings
      Given an accepted KLA Workbook exists
      When the engineer opens it with TEM, Bias percent and a dual-axis ratio of 2.75
      Then the revised settings are used immediately and remain unsaved
      And the original file changes only after Save Workbook

    # test_cancelled_open_settings_preserve_the_current_workbook
    Scenario: Cancel reviewing another Workbook
      Given the current Workbook has unsaved choices
      When the engineer cancels the open settings dialog
      Then the current document and its edits remain intact

    # test_saved_choices_open_clean_and_missing_final_inputs_open_as_a_draft
    Scenario: Open a stage that still needs measurements
      Given a Workbook has Preview measurements but no Final Raw Data
      When the engineer opens it on the Final tab
      Then the Final tab awaits input without using Preview results
      And Preview measurements remain available

  Rule: Independent analyses can resume from their own documents

    # test_independent_tool_file_open_restores_document_for_all_three_tools
    Scenario: Resume a saved independent analysis
      Given an engineer saved an independent analysis containing measurement "2.1000"
      When the engineer opens that document from the same analysis tool
      Then the saved measurement and document path are restored

    # test_independent_tool_recent_menu_filters_by_type_and_reopens_the_selected_document
    Scenario: Resume an analysis from recent documents
      Given an engineer recently saved wafer, Dynamic and Correlation analyses
      When the engineer resumes a recent Dynamic analysis
      Then only compatible saved analyses are offered
      And the chosen document is restored in the Dynamic tool

    # test_cancelled_tool_open_keeps_current_document_and_unsaved_edits
    Scenario: Keep edits when opening another analysis is cancelled
      Given a saved independent analysis has unsaved measurement "9.99"
      When the engineer cancels replacing it with another document
      Then the current document and unsaved measurement are unchanged

    # test_recent_reopen_current_document_after_save_loads_the_just_saved_measurements
    # test_match_reopen_current_document_after_save_uses_the_new_saved_data
    Scenario: Reopen the current analysis after saving its edits
      Given the current analysis has an unsaved measurement "9.99"
      When the engineer reopens its document and chooses to save the changes first
      Then the reopened analysis contains the just saved measurement "9.99"

  Rule: File types identify their document ownership

    # test_each_document_uses_its_own_extension; test_independent_tools_save_data_and_plot_configuration_to_wkb
    Scenario: Save an independent wafer analysis
      Given an engineer has an independent wafer analysis with measurement "2.1000"
      When the engineer saves the document
      Then it is a .wmap file containing all measurements and analysis choices

  Rule: A standalone copy does not accept the original draft

    # test_copy_contains_current_child_draft_without_saving_match
    Scenario: Share a draft wafer analysis from a Match Workbook
      Given Project A contains an unsaved wafer measurement "9.999"
      When the engineer exports a standalone wafer copy
      Then the copy contains the current measurement and is independently editable
      And Project A still has its unsaved changes

  Rule: Recovery preserves the accepted basis of each analysis

    # test_unchanged_recovery_is_not_rewritten_and_new_edits_remain_recoverable
    Scenario: Keep an unchanged recovery draft while protecting later edits
      Given an engineer has a recovery draft containing unsaved measurement "9.9900"
      When another recovery check runs without a new edit
      Then the existing recovery file is retained without rewriting
      When the engineer changes the measurement to "11.5000"
      Then the next recovery check protects that new draft and its accepted baseline

    # test_recovery_keeps_other_child_draft_and_its_discard_baseline
    Scenario: Recover another analysis after saving the wafer map
      Given Project A has saved wafer choices and an unsaved Dynamic measurement "99"
      When the engineer recovers Project A after an abnormal exit
      Then the Dynamic measurement is still an unsaved draft
      And discarding Dynamic restores its previously saved measurements

  Rule: An abandoned exit does not discard other documents

    # test_application_exit_preserves_discard_edits_when_later_save_fails
    Scenario: A later save cannot finish during exit
      Given the engineer chooses to discard edits in one analysis and save another
      When that save cannot finish
      Then both analyses remain open
      And the first analysis still retains its edits

  Rule: Saved measurements retain their original identity and formatting

    # test_round_trip_keeps_measurement_text_duplicate_headers_and_state
    Scenario: Reopen a wafer workspace with formatted measurement strings
      Given a wafer workspace contains wafer "001" and measurement "2.1000"
      And its measurement columns include repeated names awaiting repair
      When the engineer saves and reopens the workspace
      Then the wafer identity, measurement text and column order are unchanged

  Rule: Closing a modified workspace requires an explicit decision

    # test_standalone_dirty_workspace_still_confirms_before_closing
    Scenario: Cancel closing an edited analysis workspace
      Given a saved analysis workspace has unsaved measurements
      When the engineer cancels the close request
      Then the workspace remains open with those edits intact

    # test_match_child_discard_leaves_accepted_data_unchanged
    Scenario: Discard a Match child draft
      Given a Match Workbook contains a saved Preview Dynamic workspace
      And the engineer edits its Dynamic measurements
      When the engineer closes that child and discards the changes
      Then reopening Preview Dynamic uses the previously accepted measurements

  Rule: A failed or conflicting save must not replace accepted measurements

    # test_backup_and_conflict_keep_the_latest_accepted_file
    Scenario: Another window has saved the same wafer workspace
      Given two windows opened the same wafer workspace
      And the first window saved updated measurements
      When the second window saves its older draft to that workspace
      Then the save is refused and the first window's measurements remain saved

    # test_match_recovery_saves_to_original_not_the_previously_open_file
    Scenario: Recover a Match draft while another document was open
      Given an accepted Match WKB has a separate recovery draft
      And another Match WKB is open
      When the engineer opens the recovery draft and saves it
      Then the recovered values are saved to the original WKB
      And the other WKB is unchanged

  Rule: TEM wafer and Dynamic measurements remain independent of Workbook data

    # test_tem_independent_analyses_cannot_reset_to_workbook_data
    Scenario: Protect independent TEM measurements from a Workbook reset
      Given a TEM Workbook has independent Preview and Final wafer and Dynamic measurements
      When a Workbook data reset is requested for these analyses
      Then their measurements and choices remain unchanged
      And no destructive replacement is offered

    # test_workbook_data_menu_tracks_match_type_without_reopening_children
    Scenario: Change match type with analysis windows already open
      Given the Workbook's wafer, Dynamic and Correlation analyses are open
      When the engineer switches between TEM, KLA and NOVA
      Then using Workbook data is offered for wafer and Dynamic only outside TEM
      And Correlation and Trend can still use Workbook data in every match type

  Rule: Unconfirmed plot box selections remain unconfirmed after reopening

    # test_unconfirmed_radius_box_changes_reopen_waiting_for_draw
    Scenario: Change a Radius selection after an earlier draw
      Given a Radius plot was drawn with parameter "CD"
      And the engineer changes its box selection to "SWA" without drawing
      When the engineer saves and reopens the workspace
      Then "SWA" remains selected and waiting for Draw selected
