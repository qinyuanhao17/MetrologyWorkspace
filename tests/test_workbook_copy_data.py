"""Source removal and explicit Workbook input choice through user workflows."""
import os
import unittest
from time import perf_counter
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLineEdit, QMessageBox, QPushButton

from metrology_app.correlation_window import CorrelationWindow
from metrology_app.matching import ParameterMapping
from metrology_app.matching_window import MatchingWindow
from metrology_app.workspace_store import load_workspace, save_workspace

APP = QApplication.instance() or QApplication([])


class WorkbookCopyDataTests(unittest.TestCase):
    def test_linked_selection_dialog_follows_parent_then_local_edits_switch_to_full_data(self):
        parent = MatchingWindow()
        self.addCleanup(self.close_window, parent)
        reference, raw, mappings = self.sources()
        parent.set_reference_frame(reference)
        parent.set_raw_frame(raw)
        parent._populate_mappings(mappings)
        parent.run_analysis()
        errors = []
        parent_script = []

        def parent_selection():
            dialog = APP.activeModalWidget()
            try:
                import json
                recipe = json.loads(dialog.selection_script())
                recipe.update(filters=[[{"column": "Raw Data / Die Seq", "values": ["002"]},
                                        {"column": "Raw Data / CD", "minimum": 1, "maximum": 1}],
                                       [{"column": "Raw Data / Wafer ID", "query": "001"}]],
                              row_bools=[["or"], []], group_bools=["and"], show="filtered")
                dialog.apply_selection_script(json.dumps(recipe))
                dialog.check_visible(False)
                dialog.hide_excluded.setChecked(True)
                parent_script.append(dialog.selection_script())
                dialog.accept()
            except Exception as error:
                errors.append(error)
                dialog.reject()
        QTimer.singleShot(0, parent_selection)
        parent.data_selection_action.trigger()
        self.assertEqual(errors, [])
        for child in (parent.open_correlation_workspace(), parent.open_stage_workspace("preview")):
            self.addCleanup(self.close_window, child)
            original = child.model.document_frame()
            for change in (False, True):
                def inspect():
                    dialog = APP.activeModalWidget()
                    try:
                        import json
                        self.assertEqual(json.loads(dialog.selection_script()), json.loads(parent_script[0]))
                        self.assertEqual(len(dialog.model.checked), 3)
                        self.assertTrue(dialog.hide_excluded.isChecked())
                        if change:
                            dialog.clear_filters()
                            dialog.search.setText("036")
                            dialog.check_visible(False)
                            dialog.hide_excluded.setChecked(False)
                        dialog.accept()
                    except Exception as error:
                        errors.append(error)
                        dialog.reject()
                QTimer.singleShot(0, inspect)
                child.data_selection_action.trigger()
                self.assertEqual(errors, [])
                self.assertEqual(child.workbook_selection_action.isChecked(), not change)
                self.assertEqual(child.full_data_action.isChecked(), change)
            self.assertEqual(child.participating_positions(child.model.frame()), {2, 3})
            self.assertIs(child.sheet.model(), child.model)
            pd.testing.assert_frame_equal(child.model.document_frame(), original)
            child.workbook_selection_action.trigger()
            self.assertEqual(child.participating_positions(child.model.frame()), {1, 2, 3})
        self.assertEqual(parent.result.source_rows, (1, 2, 3))

    def test_parent_cut_keeps_linked_correlation_until_raw_is_replaced(self):
        from benchmarks.benchmark_memory_storage import settle

        parent = MatchingWindow()
        self.addCleanup(self.close_window, parent)
        reference, raw, mappings = self.sources()
        parent.set_reference_frame(reference)
        parent.set_raw_frame(raw)
        parent._populate_mappings(mappings)
        parent.run_analysis()
        wafer_map = parent.open_stage_workspace("preview")
        self.addCleanup(self.close_window, wafer_map)
        child = parent.open_correlation_workspace()
        self.addCleanup(self.close_window, child)
        child.set_reference_table(reference)
        for page in (child.correlation_page, child.sequence_page):
            page.selector.selectAll()
            page.draw_plot()
        settle(APP, [parent, child, wafer_map])
        saved_reference = child.reference_model.document_frame()
        saved_selection = child.selection_state()
        saved_map = wafer_map.model.document_frame()

        parent.raw_view.selectAll()
        QTest.keyClick(parent.raw_view, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
        settle(APP, [parent, child, wafer_map])
        self.assertTrue(parent.raw_model.document_frame().empty)
        pd.testing.assert_frame_equal(wafer_map.model.document_frame(), saved_map)
        pd.testing.assert_frame_equal(child.raw_model.document_frame(), raw)
        pd.testing.assert_frame_equal(child.reference_model.document_frame(), saved_reference)
        self.assertEqual(child.selection_state(), saved_selection)
        self.assertTrue(child.copy_from_wkb_action.isChecked())
        self.assertTrue(child.correlation_page.ready)
        self.assertTrue(child.sequence_page.ready)

        incoming = raw.copy()
        incoming.loc[0, "CD"] = "1.23456789000001"
        APP.clipboard().setText(incoming.to_csv(sep="\t", index=False))
        parent.raw_view.setCurrentIndex(parent.raw_view.model().index(0, 0))
        QTest.keyClick(parent.raw_view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        settle(APP, [parent, child, wafer_map])
        pd.testing.assert_frame_equal(child.raw_model.document_frame(), incoming)
        pd.testing.assert_frame_equal(child.reference_model.document_frame(), saved_reference)
        self.assertEqual(child.selection_state(), saved_selection)
        self.assertTrue(child.copy_from_wkb_action.isChecked())

        parent.raw_model.undo.undo()  # Undo replacement returns to the temporary blank.
        settle(APP, [parent, child, wafer_map])
        pd.testing.assert_frame_equal(child.raw_model.document_frame(), incoming)
        parent.raw_model.undo.undo()  # Undo cut restores the original source.
        settle(APP, [parent, child, wafer_map])
        pd.testing.assert_frame_equal(child.raw_model.document_frame(), raw)
        self.assertEqual(child.selection_state(), saved_selection)

    def test_manual_raw_saved_before_parent_refresh_keeps_literal_edits_and_detaches_copy(self):
        parent = MatchingWindow()
        self.addCleanup(self.close_window, parent)
        reference, raw, _mappings = self.sources()
        parent.set_reference_frame(reference)
        parent.set_raw_frame(raw)
        parent.run_analysis()
        child = parent.open_correlation_workspace()
        column = child.raw_model.document_frame().columns.get_loc("CD")
        child.raw_model.edit({(1, column): "9.9990000"})
        child.recognize()
        with TemporaryDirectory() as folder:
            path = Path(folder) / "manual-raw-save-first.mwkb"
            parent.save_workbook(path)
            self.assertFalse(child.copy_from_wkb_action.isChecked())
            restored = MatchingWindow()
            self.addCleanup(self.close_window, restored)
            restored.load_workbook(path)
            reopened = restored.open_correlation_workspace()
            self.assertEqual(reopened.raw_model.document_frame()["CD"].iloc[0], "9.9990000")
            self.assertFalse(reopened.copy_from_wkb_action.isChecked())
            pd.testing.assert_frame_equal(parent.raw_model.document_frame(), raw)

    def test_old_nova_and_kla_copy_checked_map_follows_raw_not_saved_snapshot(self):
        for match_type in ("NOVA", "KLA"):
            for override in (False, True):
                with self.subTest(match_type=match_type, old_data_override=override):
                    parent = MatchingWindow()
                    self.addCleanup(self.close_window, parent)
                    reference, raw, _mappings = self.sources()
                    parent.match_type.setCurrentText(match_type)
                    parent.set_reference_frame(reference)
                    parent.set_raw_frame(raw)
                    parent.run_analysis()
                    child = parent.open_stage_workspace("preview")
                    self.addCleanup(self.close_window, child)
                    snapshot = parent.workspace_snapshot(include_drafts=True)
                    # Legacy files could retain a Map snapshot independently
                    # while their visible Copy from WKB checkbox stayed on.
                    snapshot.frames["preview_map"] = child.model.document_frame().assign(CD=["99.0"] * len(raw))
                    snapshot.states["map.preview"]["data_override"] = override
                    self.assertTrue(snapshot.states["map.preview"]["ui"]["copy_from_wkb"])
                    with TemporaryDirectory() as folder:
                        path = Path(folder) / "old-linked-map.mwkb"
                        save_workspace(path, snapshot)
                        restored = MatchingWindow()
                        self.addCleanup(self.close_window, restored)
                        restored.load_workbook(path)
                        reopened = restored.open_stage_workspace("preview")
                        self.addCleanup(self.close_window, reopened)
                        self.assertTrue(reopened.copy_from_wkb_action.isChecked())
                        column = restored.raw_model.document_frame().columns.get_loc("CD")
                        restored.raw_model.edit({(1, column): "0"})
                        restored.run_analysis()
                        APP.processEvents()
                        self.assertTrue(reopened.copy_from_wkb_action.isChecked())
                        self.assertEqual(pd.to_numeric(reopened.model.document_frame()["CD"]).iloc[0], 0.)
                        self.assertEqual(restored.preview_map_frame["CD"].tolist(), ["99.0"] * len(raw),
                                         "Refreshing a linked child must not mutate the accepted Map snapshot")
                        local_column = reopened.model.document_frame().columns.get_loc("CD")
                        reopened.model.edit({(1, local_column): "123.4567000"})
                        restored.raw_model.edit({(1, column): "9.000"})
                        restored.run_analysis()
                        self.assertEqual(reopened.model.document_frame()["CD"].iloc[0], "123.4567000",
                                         "An unsaved local measurement draft must never be overwritten")

    def test_tem_map_with_copy_checked_follows_repeated_workbook_raw_edits(self):
        for stage in ("preview", "final"):
            with self.subTest(stage=stage):
                parent = MatchingWindow()
                self.addCleanup(self.close_window, parent)
                reference, raw, _mappings = self.sources()
                parent.match_type.setCurrentText("TEM")
                parent.result_mode.setCurrentText(stage.title())
                parent.set_reference_frame(reference)
                parent.set_raw_frame(raw)
                parent.run_analysis()
                child = parent.open_stage_workspace(stage)
                self.addCleanup(self.close_window, child)
                child.copy_from_wkb_action.trigger()
                self.assertTrue(child.copy_from_wkb_action.isChecked())
                model = parent.raw_model if stage == "preview" else parent.final_raw_model
                column = model.document_frame().columns.get_loc("CD")
                for value in ("0", "8.12345000"):
                    model.edit({(1, column): value})
                    APP.processEvents()
                    self.assertEqual(child.model.document_frame()["CD"].iloc[0], value)
                    parent.run_analysis()
                    APP.processEvents()
                    self.assertTrue(child.copy_from_wkb_action.isChecked())
                    self.assertEqual(child.model.document_frame()["CD"].iloc[0], value)
                model.edit({(0, column): "CD Updated"})
                parent.run_analysis()
                self.assertIn("CD Updated", child.model.document_frame())
                self.assertNotIn("CD", child.model.document_frame())

    def test_linked_correlation_and_trend_redraw_raw_values_and_renamed_columns(self):
        parent = MatchingWindow()
        self.addCleanup(self.close_window, parent)
        reference, raw, _mappings = self.sources()
        parent.set_reference_frame(reference)
        parent.set_raw_frame(raw)
        parent.run_analysis()
        child = parent.open_correlation_workspace()
        self.addCleanup(self.close_window, child)
        for page in (child.correlation_page, child.sequence_page):
            page.selector.selectAll()
            page.draw_plot()
            self.assertTrue(page.ready, page.status.text())
        column = parent.raw_model.document_frame().columns.get_loc("CD")
        parent.raw_model.edit({(1, column): "1.123456789"})
        parent.run_analysis()
        APP.processEvents()
        fit = child.correlation_page.all_fits[0]
        self.assertEqual(fit.sources[0].fit.x.tolist(), [1.123456789, 2., 3., 4.])
        trend = child.sequence_page
        index = next(i for i, panel in enumerate(trend.panel_specs) if panel["metric"] == "CD")
        self.assertEqual(trend.plot_widgets[index].listDataItems()[0].yData.tolist(), [1.123456789, 2., 3., 4.])
        parent.raw_model.edit({(0, column): "CD Updated"})
        parent.run_analysis()
        APP.processEvents()
        self.assertTrue(child.correlation_page.ready, child.correlation_page.status.text())
        self.assertTrue(child.sequence_page.ready, child.sequence_page.status.text())
        self.assertIn(("Raw Data", "CD Updated"), child.correlation_page.all_fits[0].parameter_keys)
        self.assertEqual({panel["metric"] for panel in child.sequence_page.panel_specs}, {"CD Updated", "Depth"})

    def test_manual_raw_edits_are_preserved_and_stop_the_copy_link(self):
        parent = MatchingWindow()
        self.addCleanup(self.close_window, parent)
        reference, raw, _mappings = self.sources()
        parent.set_reference_frame(reference)
        parent.set_raw_frame(raw)
        parent.run_analysis()
        child = parent.open_correlation_workspace()
        self.addCleanup(self.close_window, child)
        column = child.raw_model.document_frame().columns.get_loc("CD")
        child.raw_model.edit({(1, column): "99.12345000"})
        before = child.raw_model.document_frame().copy()
        parent.set_raw_frame(raw.assign(CD=["9.000", "8.000", "7.000", "6.000"]))
        parent.run_analysis()
        self.assertFalse(child.copy_from_wkb_action.isChecked())
        pd.testing.assert_frame_equal(child.raw_model.document_frame(), before)

    def test_correlation_reference_is_manual_and_raw_copy_does_not_replace_or_clear_it(self):
        parent = MatchingWindow()
        self.addCleanup(self.close_window, parent)
        reference, raw, _mappings = self.sources()
        parent.match_type.setCurrentText("NOVA")
        parent.set_reference_frame(reference)
        parent.set_raw_frame(raw)
        parent.run_analysis()
        child = parent.open_correlation_workspace()
        self.addCleanup(self.close_window, child)
        self.assertTrue(child.copy_from_wkb_action.isChecked())
        self.assertTrue(child.reference_model.document_frame().empty)
        child.set_reference_table(reference, "Manual Reference")
        manual = child.reference_model.document_frame().copy()
        updated = raw.assign(CD=["10.000", "2.000", "3.000", "4.000"])
        parent.set_raw_frame(updated)
        parent.run_analysis()
        pd.testing.assert_frame_equal(child.raw_model.document_frame(), updated)
        pd.testing.assert_frame_equal(child.reference_model.document_frame(), manual)
        self.assertTrue(child.document.baseline.frames["reference_data"].empty,
                        "A Raw refresh must not accept the unsaved manual Reference draft")
        child.copy_from_wkb_action.trigger()
        self.assertTrue(child.raw_model.document_frame().empty)
        pd.testing.assert_frame_equal(child.reference_model.document_frame(), manual)
        child.copy_from_wkb_action.trigger()
        pd.testing.assert_frame_equal(child.raw_model.document_frame(), updated)
        pd.testing.assert_frame_equal(child.reference_model.document_frame(), manual)
        with TemporaryDirectory() as folder:
            path = Path(folder) / "manual-reference-linked-raw.mwkb"
            parent.save_workbook(path)
            restored = MatchingWindow()
            self.addCleanup(self.close_window, restored)
            restored.load_workbook(path)
            reopened = restored.open_correlation_workspace()
            self.addCleanup(self.close_window, reopened)
            pd.testing.assert_frame_equal(reopened.reference_model.document_frame(), manual)
            self.assertTrue(reopened.copy_from_wkb_action.isChecked())
            updated["CD"] = ["20.000", "2.000", "3.000", "4.000"]
            restored.set_raw_frame(updated)
            restored.run_analysis()
            pd.testing.assert_frame_equal(reopened.raw_model.document_frame(), updated)
            pd.testing.assert_frame_equal(reopened.reference_model.document_frame(), manual)

    def test_copy_menu_replaces_the_duplicate_file_command_but_dynamic_keeps_its_only_command(self):
        parent = MatchingWindow()
        self.addCleanup(self.close_window, parent)
        reference, raw, _mappings = self.sources()
        parent.match_type.setCurrentText("NOVA")
        parent.set_reference_frame(reference)
        parent.set_raw_frame(raw)
        parent.run_analysis()
        for child in (parent.open_stage_workspace("preview"), parent.open_correlation_workspace()):
            self.addCleanup(self.close_window, child)
            self.assertNotIn("Use Workbook Data…", [action.text() for action in child.file_menu.actions()])
            self.assertIn(child.copy_from_wkb_action, child.data_menu.actions())
        dynamic = parent.open_dynamic_workspace("preview")
        self.addCleanup(self.close_window, dynamic)
        self.assertIn("Use Workbook Data…", [action.text() for action in dynamic.file_menu.actions()])

    def test_reopened_full_data_scope_loads_all_rows_before_restoring_local_selection(self):
        parent = MatchingWindow()
        self.addCleanup(self.close_window, parent)
        reference, raw, _mappings = self.sources()
        parent.match_type.setCurrentText("NOVA")
        parent.set_reference_frame(reference)
        parent.set_raw_frame(raw)
        parent.run_analysis()
        failures = []

        def exclude_first():
            dialog = APP.activeModalWidget()
            try:
                dialog.findChild(QLineEdit, "dataSelectionSearch").setText("002")
                next(button for button in dialog.findChildren(QPushButton)
                     if button.text() == "Uncheck Visible").click()
                dialog.accept()
            except Exception as error:
                failures.append(error)
                dialog.reject()

        QTimer.singleShot(0, exclude_first)
        parent.data_selection_action.trigger()
        self.assertEqual(failures, [])
        for child in (parent.open_stage_workspace("preview"), parent.open_correlation_workspace()):
            self.addCleanup(self.close_window, child)
            self.assertEqual(len(child.model.document_frame()), 4)
            self.assertEqual(len(child.participating_positions(child.model.frame())), 3)
            child.full_data_action.trigger()
            self.assertEqual(len(child.model.document_frame()), 4)
            if child.workspace_type == "wafer_map":
                QTimer.singleShot(0, exclude_first)
                child.data_selection_action.trigger()
                self.assertEqual(failures, [])
        with TemporaryDirectory() as folder:
            path = Path(folder) / "full-data-scope.mwkb"
            parent.save_workbook(path)
            legacy = Path(folder) / "legacy-full-data-scope.mwkb"
            snapshot = load_workspace(path)
            for scope in ("map.preview", "correlation.preview"):
                snapshot.states[scope]["ui"].pop("copy_from_wkb")
            save_workspace(legacy, snapshot)
            for saved_path in (path, legacy):
                with self.subTest(path=saved_path.name):
                    reopened = MatchingWindow()
                    self.addCleanup(self.close_window, reopened)
                    reopened.load_workbook(saved_path)
                    for child in (reopened.open_stage_workspace("preview"), reopened.open_correlation_workspace()):
                        self.addCleanup(self.close_window, child)
                        self.assertTrue(child.copy_from_wkb_action.isChecked())
                        self.assertTrue(child.full_data_action.isChecked())
                        self.assertFalse(child.workbook_selection_action.isChecked())
                        self.assertEqual(child.model.document_frame()["Die Seq"].tolist(), ["002", "036", "050", "085"])
                        if child.workspace_type == "wafer_map":
                            self.assertEqual(child.participating_positions(child.model.frame()), {1, 2, 3})
                            local_selection = child.workspace_snapshot().states["data_selection"]["excluded"]
                        else:
                            self.assertTrue(child.reference_model.document_frame().empty)
                        child.workbook_selection_action.trigger()
                        self.assertTrue(child.workbook_selection_action.isChecked())
                        self.assertFalse(child.full_data_action.isChecked())
                        self.assertEqual(len(child.model.document_frame()), 4)
                        self.assertEqual(len(child.participating_positions(child.model.frame())), 3)
                        child.full_data_action.trigger()
                        self.assertFalse(child.workbook_selection_action.isChecked())
                        self.assertTrue(child.full_data_action.isChecked())
                        self.assertEqual(len(child.model.document_frame()), 4)
                        if child.workspace_type == "wafer_map":
                            self.assertEqual(child.participating_positions(child.model.frame()), {1, 2, 3})
                            self.assertEqual(child.workspace_snapshot().states["data_selection"]["excluded"],
                                             local_selection)
                    pd.testing.assert_frame_equal(reopened.raw_model.document_frame(), raw)

    def test_map_copy_off_keeps_locked_positions_and_recopy_preserves_them_in_saved_workbook(self):
        parent = MatchingWindow()
        self.addCleanup(self.close_window, parent)
        reference, raw, _mappings = self.sources()
        parent.match_type.setCurrentText("NOVA")
        parent.set_reference_frame(reference)
        parent.set_raw_frame(raw)
        parent.run_analysis()
        child = parent.open_stage_workspace("preview")
        self.addCleanup(self.close_window, child)
        child.model.edit({(0, 2): "X", (0, 3): "Y"})
        child.model.set_clipboard_locks(["X", "Y"])
        locked = child.model.document_frame().iloc[:, 2:4].copy()
        child.copy_from_wkb_action.trigger()
        self.assertFalse(child.copy_from_wkb_action.isChecked())
        self.assertEqual(child.model.clipboard_locks, {"X", "Y"})
        remaining = child.model.document_frame()
        self.assertEqual(remaining.columns.tolist(), ["", "", "X", "Y"])
        self.assertEqual(remaining.iloc[:, :2].values.tolist(), [["", ""]] * 4)
        pd.testing.assert_frame_equal(remaining.iloc[:, 2:], locked)
        updated = raw.copy()
        updated["FIELD X"] = ["99", "98", "97", "96"]
        updated["CD"] = ["9.100", "9.200", "9.300", "9.400"]
        parent.set_raw_frame(updated)
        parent.run_analysis()
        child.copy_from_wkb_action.trigger()
        self.assertTrue(child.copy_from_wkb_action.isChecked())
        copied = child.model.document_frame()
        pd.testing.assert_frame_equal(copied.iloc[:, 2:4], locked)
        # Copying the uncarded source must retain its measurement strings,
        # including precision; only the plotting layer parses numeric values.
        self.assertEqual(copied["CD"].tolist(), ["9.100", "9.200", "9.300", "9.400"])
        source_columns = ["Wafer ID", "Die Seq", "CD", "Depth"]
        pd.testing.assert_frame_equal(copied[source_columns], updated[source_columns])
        self.assertEqual(copied.columns.tolist(), ["Wafer ID", "Die Seq", "X", "Y", "CD", "Depth"])
        with TemporaryDirectory() as folder:
            path = Path(folder) / "protected-copy.mwkb"
            parent.save_workbook(path)
            restored = MatchingWindow()
            self.addCleanup(self.close_window, restored)
            restored.load_workbook(path)
            reopened = restored.open_stage_workspace("preview")
            self.addCleanup(self.close_window, reopened)
            self.assertEqual(reopened.model.clipboard_locks, {"X", "Y"})
            pd.testing.assert_frame_equal(reopened.model.document_frame(), copied)

    def test_locked_map_selection_choices_stay_enabled_without_copy_and_do_not_replace_data(self):
        parent = MatchingWindow()
        self.addCleanup(self.close_window, parent)
        reference, raw, _mappings = self.sources()
        parent.match_type.setCurrentText("NOVA")
        parent.set_reference_frame(reference)
        parent.set_raw_frame(raw)
        parent.run_analysis()
        child = parent.open_stage_workspace("preview")
        self.addCleanup(self.close_window, child)
        child.model.set_clipboard_locks(["FIELD X", "FIELD Y"])
        child.copy_from_wkb_action.trigger()
        self.assertTrue(child.workbook_selection_action.isEnabled())
        self.assertTrue(child.full_data_action.isEnabled())
        child.set_table(raw.assign(CD=["9.100", "9.200", "9.300", "9.400"]), "Manual", report_paste=True)
        before = child.model.document_frame()
        failures = []

        def exclude_first():
            dialog = APP.activeModalWidget()
            try:
                dialog.findChild(QLineEdit, "dataSelectionSearch").setText("002")
                next(button for button in dialog.findChildren(QPushButton)
                     if button.text() == "Uncheck Visible").click()
                dialog.accept()
            except Exception as error:
                failures.append(error)
                dialog.reject()

        QTimer.singleShot(0, exclude_first)
        parent.data_selection_action.trigger()
        self.assertEqual(failures, [])
        with patch.object(QMessageBox, "question", side_effect=AssertionError("Selection cannot replace locked data")):
            child.workbook_selection_action.trigger()
            self.assertEqual(child.participating_positions(child.model.frame()), {1, 2, 3})
            child.full_data_action.trigger()
            self.assertEqual(child.participating_positions(child.model.frame()), {0, 1, 2, 3})
            QTimer.singleShot(0, exclude_first)
            child.data_selection_action.trigger()
            self.assertEqual(failures, [])
            self.assertEqual(child.participating_positions(child.model.frame()), {1, 2, 3})
        self.assertFalse(child.copy_from_wkb_action.isChecked())
        self.assertEqual(child.model.clipboard_locks, {"FIELD X", "FIELD Y"})
        pd.testing.assert_frame_equal(child.model.document_frame(), before)
        # Full data is already selected. Copy must not silently switch scope
        # and attempt a three-row replacement of the four locked row slots.
        child.copy_from_wkb_action.trigger()
        self.assertTrue(child.copy_from_wkb_action.isChecked())
        self.assertTrue(child.full_data_action.isChecked())
        copied = child.model.document_frame()
        self.assertEqual(len(copied), 4)
        pd.testing.assert_frame_equal(copied.iloc[:, 2:4], before.iloc[:, 2:4])
        with patch.object(QMessageBox, "question", side_effect=AssertionError("Selection cannot replace copied locked data")):
            child.workbook_selection_action.trigger()
            self.assertEqual(child.participating_positions(child.model.frame()), {1, 2, 3})
            child.full_data_action.trigger()
        pd.testing.assert_frame_equal(child.model.document_frame(), copied)

    def test_tem_map_menu_can_explicitly_copy_raw_and_protect_locked_coordinates(self):
        parent = MatchingWindow()
        self.addCleanup(self.close_window, parent)
        reference, raw, _mappings = self.sources()
        parent.match_type.setCurrentText("TEM")
        parent.set_reference_frame(reference)
        parent.set_raw_frame(raw)
        parent.run_analysis()
        child = parent.open_stage_workspace("preview")
        self.addCleanup(self.close_window, child)
        self.assertTrue(child.copy_from_wkb_action.isEnabled())
        self.assertTrue(child.workbook_selection_action.isEnabled())
        self.assertTrue(child.full_data_action.isEnabled())
        self.assertFalse(child.copy_from_wkb_action.isChecked())
        self.assertTrue(child.model.document_frame().empty)
        child.data_menu.popup(child.mapToGlobal(QPoint(16, 40)))
        APP.processEvents()
        QTest.mouseClick(child.data_menu, Qt.MouseButton.LeftButton,
                         pos=child.data_menu.actionGeometry(child.copy_from_wkb_action).center())
        self.assertTrue(child.copy_from_wkb_action.isChecked())
        pd.testing.assert_frame_equal(child.model.document_frame(), raw)
        child.model.edit({(0, 2): "X", (0, 3): "Y"})
        child.model.set_clipboard_locks(["X", "Y"])
        before = child.model.document_frame()
        updated = raw.assign(**{"FIELD X": ["99", "98", "97", "96"],
                                 "CD": ["9.100", "9.200", "9.300", "9.400"]})
        parent.set_raw_frame(updated)
        parent.run_analysis()
        pd.testing.assert_frame_equal(child.model.document_frame(), before)
        child.copy_from_wkb_action.trigger()
        child.copy_from_wkb_action.trigger()
        copied = child.model.document_frame()
        pd.testing.assert_frame_equal(copied.iloc[:, 2:4], before.iloc[:, 2:4])
        self.assertEqual(copied["CD"].tolist(), ["9.100", "9.200", "9.300", "9.400"])
        self.assertTrue(child.copy_from_wkb_action.isChecked())
        with patch.object(QMessageBox, "question", side_effect=AssertionError("Selection cannot discard coordinates")):
            for action in (child.full_data_action, child.workbook_selection_action):
                child.data_menu.popup(child.mapToGlobal(QPoint(16, 40)))
                APP.processEvents()
                QTest.mouseClick(child.data_menu, Qt.MouseButton.LeftButton,
                                 pos=child.data_menu.actionGeometry(action).center())
                self.assertTrue(action.isChecked())
        pd.testing.assert_frame_equal(child.model.document_frame(), copied)

    def test_rejected_workbook_copy_or_cancel_keeps_locked_manual_table_and_choices(self):
        parent = MatchingWindow()
        self.addCleanup(self.close_window, parent)
        reference, raw, _mappings = self.sources()
        parent.match_type.setCurrentText("NOVA")
        parent.set_reference_frame(reference)
        parent.set_raw_frame(raw)
        parent.run_analysis()
        child = parent.open_stage_workspace("preview")
        self.addCleanup(self.close_window, child)
        child.model.set_clipboard_locks(["FIELD X", "FIELD Y"])
        child.copy_from_wkb_action.trigger()
        child.set_table(raw, "Manual", report_paste=True)
        before = child.workspace_snapshot()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            child.copy_from_wkb_action.trigger()
        self.assertEqual(child.workspace_snapshot().states, before.states)
        pd.testing.assert_frame_equal(child.model.document_frame(), before.frames["input_data"])
        parent.set_reference_frame(pd.concat([reference, reference.iloc[:1]], ignore_index=True))
        parent.set_raw_frame(pd.concat([raw, raw.iloc[:1]], ignore_index=True))
        parent.run_analysis()
        before = child.workspace_snapshot()
        with patch.object(QMessageBox, "warning") as warning:
            child.copy_from_wkb_action.trigger()
        self.assertTrue(warning.called)
        self.assertIn("different number of rows", str(warning.call_args))
        self.assertFalse(child.copy_from_wkb_action.isChecked())
        self.assertTrue(child.full_data_action.isChecked())
        self.assertEqual(child.model.clipboard_locks, {"FIELD X", "FIELD Y"})
        self.assertEqual(child.workspace_snapshot().states, before.states)
        pd.testing.assert_frame_equal(child.model.document_frame(), before.frames["input_data"])

    @staticmethod
    def sources():
        raw = pd.DataFrame({"Wafer ID": ["001"] * 4, "Die Seq": ["002", "036", "050", "085"],
                            "FIELD X": ["-1", "1", "-1", "1"], "FIELD Y": ["-1", "-1", "1", "1"],
                            "CD": ["1.000", "2.000", "3.000", "4.000"],
                            "Depth": ["3.000", "5.000", "7.000", "9.000"]})
        reference = pd.DataFrame({"CD Reference": ["2.000", "4.000", "6.000", "8.000"],
                                  "Depth Reference": ["7.000", "11.000", "15.000", "19.000"]})
        mappings = (ParameterMapping("CD Reference", "CD Reference", "CD"),
                    ParameterMapping("Depth Reference", "Depth Reference", "Depth"))
        return reference, raw, mappings

    @staticmethod
    def close_window(window):
        window.document.force_close = True
        window.close()
        window.deleteLater()
        APP.processEvents()

    def test_deleting_reference_removes_its_boxes_and_raw_still_draws(self):
        window = CorrelationWindow()
        self.addCleanup(self.close_window, window)
        reference, raw, mappings = self.sources()
        window.set_sources(reference, raw, mappings)
        for page in (window.correlation_page, window.sequence_page):
            page.selector.selectAll()
            page.draw_plot()
            self.assertTrue(page.ready, page.status.text())
        before = window.raw_model.document_frame()
        window.show()
        window.tabs.setCurrentWidget(window.reference_page)
        window.reference_sheet.setFocus()
        QTest.keyClick(window.reference_sheet, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(window.reference_sheet, Qt.Key.Key_Delete)
        self.assertTrue(window.reference_model.frame().empty)
        window.recognize()
        for page in (window.correlation_page, window.sequence_page):
            page.show_selector()
            self.assertTrue(page.selector.wafers)
            self.assertTrue(all(key[0] == "Raw Data" for key in page.selector.wafers))
            page.selector.selectAll()
            page.draw_plot()
            self.assertTrue(page.ready, page.status.text())
        pd.testing.assert_frame_equal(window.raw_model.document_frame(), before)

    def test_one_copy_choice_clears_inputs_allows_manual_draw_and_recopies_current_workbook(self):
        parent = MatchingWindow()
        self.addCleanup(self.close_window, parent)
        reference, raw, _mappings = self.sources()
        parent.match_type.setCurrentText("NOVA")
        parent.set_reference_frame(reference)
        parent.set_raw_frame(raw)
        parent.run_analysis()
        original_parent = parent.workspace_snapshot()
        for kind, child in (("correlation", parent.open_correlation_workspace()),
                            ("map", parent.open_stage_workspace("preview"))):
            self.addCleanup(self.close_window, child)
            with self.subTest(kind=kind):
                copies = [action for action in child.data_menu.actions() if action is child.copy_from_wkb_action]
                self.assertEqual(len(copies), 1, "Data needs one common source checkbox")
                choice = copies[0]
                copied = child.workspace_snapshot()
                self.assertTrue(choice.isCheckable())
                self.assertTrue(choice.isChecked())
                choice.trigger()
                self.assertFalse(choice.isChecked())
                for frame in child.workspace_snapshot().frames.values():
                    self.assertTrue(frame.empty)
                pages = ((child.correlation_page, child.sequence_page) if kind == "correlation"
                         else (child.plot_page,))
                for page in pages:
                    self.assertEqual(page.selector.rowCount(), 0)
                    if kind == "correlation":
                        self.assertFalse(page.ready)
                    else:
                        self.assertIsNone(page.result)
                manual = raw.copy()
                manual["CD"] = ["9.000", "10.000", "11.000", "12.000"]
                child.show()
                child.tabs.setCurrentIndex(1 if kind == "correlation" else 0)
                child.sheet.setCurrentIndex(child.model.index(0, 0))
                child.sheet.setFocus()
                APP.clipboard().setText(manual.to_csv(sep="\t", index=False))
                QTest.keyClick(child.sheet, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
                child.recognize()
                pd.testing.assert_frame_equal(child.model.document_frame(), manual)
                child.check_all(child.parameter_list, True)
                for page in pages:
                    page.selector.selectAll()
                    if kind == "correlation":
                        page.draw_plot()
                        self.assertTrue(page.ready, page.status.text())
                    else:
                        page.draw_maps()
                        deadline = perf_counter() + 5
                        while page.worker is not None and perf_counter() < deadline:
                            QTest.qWait(10)
                        self.assertIsNotNone(page.result, page.status.text())
                self.assertFalse(choice.isChecked())
                choice.trigger()
                self.assertTrue(choice.isChecked())
                input_name = "raw_data" if kind == "correlation" else "input_data"
                pd.testing.assert_frame_equal(child.model.document_frame(), copied.frames[input_name])
                if kind == "correlation":
                    self.assertTrue(child.reference_model.frame().empty)
                    pd.testing.assert_frame_equal(child.reference_model.document_frame(),
                                                  copied.frames["reference_data"])
                    for page in pages:
                        self.assertEqual({key[0] for key in page.selector.wafers}, {"Raw Data"})
                        page.selector.selectAll()
                        page.draw_plot()
                        self.assertTrue(page.ready, page.status.text())
        for name, frame in original_parent.frames.items():
            pd.testing.assert_frame_equal(parent.workspace_snapshot().frames[name], frame)

    def test_cancelled_recopy_keeps_manual_inputs_and_the_unchecked_choice(self):
        parent = MatchingWindow()
        self.addCleanup(self.close_window, parent)
        reference, raw, _mappings = self.sources()
        parent.set_reference_frame(reference)
        parent.set_raw_frame(raw)
        parent.run_analysis()
        child = parent.open_correlation_workspace()
        self.addCleanup(self.close_window, child)
        choice = child.copy_from_wkb_action
        choice.trigger()
        child.set_table(raw, "Manual measurements")
        before = child.workspace_snapshot()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            choice.trigger()
        self.assertFalse(choice.isChecked())
        self.assertEqual(child.workspace_snapshot().states, before.states)
        for name, frame in before.frames.items():
            pd.testing.assert_frame_equal(child.workspace_snapshot().frames[name], frame)

    def test_saved_manual_mode_stays_empty_across_workbook_refresh_and_reopen(self):
        parent = MatchingWindow()
        self.addCleanup(self.close_window, parent)
        reference, raw, _mappings = self.sources()
        parent.match_type.setCurrentText("NOVA")
        parent.set_reference_frame(reference)
        parent.set_raw_frame(raw)
        parent.run_analysis()
        child = parent.open_correlation_workspace()
        self.addCleanup(self.close_window, child)
        choice = child.copy_from_wkb_action
        choice.trigger()
        with TemporaryDirectory() as folder:
            path = Path(folder) / "copy-choice.mwkb"
            parent.save_workbook(path)
            updated = raw.copy()
            updated["CD"] = ["21.000", "22.000", "23.000", "24.000"]
            parent.set_raw_frame(updated)
            parent.run_analysis()
            self.assertFalse(choice.isChecked())
            self.assertTrue(child.raw_model.frame().empty)
            self.assertTrue(child.reference_model.frame().empty)
            parent.save_workbook(path)
            restored = MatchingWindow()
            self.addCleanup(self.close_window, restored)
            restored.load_workbook(path)
            reopened = restored.open_correlation_workspace()
            self.addCleanup(self.close_window, reopened)
            copied = reopened.copy_from_wkb_action
            self.assertFalse(copied.isChecked())
            self.assertTrue(reopened.workbook_selection_action.isVisible())
            self.assertFalse(reopened.workbook_selection_action.isChecked())
            self.assertFalse(reopened.workbook_selection_action.isEnabled())
            self.assertTrue(reopened.raw_model.frame().empty)
            self.assertTrue(reopened.reference_model.frame().empty)
            # Empty input has nothing to discard, so simply checking can copy.
            with patch.object(QMessageBox, "question", side_effect=AssertionError("empty input needs no discard prompt")):
                copied.trigger()
            self.assertTrue(copied.isChecked())
            self.assertEqual(reopened.raw_model.document_frame()["CD"].tolist(), updated["CD"].tolist())

    def test_workbook_selection_stays_available_for_manual_map_input(self):
        parent = MatchingWindow()
        self.addCleanup(self.close_window, parent)
        reference, raw, _mappings = self.sources()
        parent.match_type.setCurrentText("NOVA")
        parent.set_reference_frame(reference)
        parent.set_raw_frame(raw)
        parent.run_analysis()
        for child in (parent.open_stage_workspace("preview"), parent.open_correlation_workspace()):
            self.addCleanup(self.close_window, child)
            choice = child.copy_from_wkb_action
            selection = next(action for action in child.data_menu.actions() if action.text() == "Match Workbook selection")
            self.assertTrue(selection.isVisible())
            self.assertTrue(selection.isChecked())
            self.assertTrue(selection.isEnabled())
            choice.trigger()
            self.assertTrue(selection.isVisible())
            self.assertFalse(selection.isChecked())
            self.assertEqual(selection.isEnabled(), child.workspace_type == "wafer_map")
            self.assertTrue(child.data_selection_action.isEnabled())
            choice.trigger()
            self.assertTrue(selection.isVisible())
            self.assertTrue(selection.isChecked())
            self.assertTrue(selection.isEnabled())
        parent.match_type.setCurrentText("TEM")
        wafer = parent.open_stage_workspace("preview")
        self.assertTrue(wafer.workbook_selection_action.isVisible())
        self.assertTrue(wafer.workbook_selection_action.isEnabled())
        self.assertTrue(wafer.full_data_action.isEnabled())
        self.assertTrue(wafer.copy_from_wkb_action.isEnabled())

    def test_manual_input_ignores_workbook_selection_and_recopy_uses_its_selected_rows(self):
        parent = MatchingWindow()
        self.addCleanup(self.close_window, parent)
        reference, raw, _mappings = self.sources()
        parent.match_type.setCurrentText("NOVA")
        parent.set_reference_frame(reference)
        parent.set_raw_frame(raw)
        parent.run_analysis()
        errors = []

        def exclude_die_002():
            dialog = APP.activeModalWidget()
            try:
                dialog.findChild(QLineEdit, "dataSelectionSearch").setText("002")
                next(button for button in dialog.findChildren(QPushButton)
                     if button.text() == "Uncheck Visible").click()
                dialog.accept()
            except Exception as error:
                errors.append(error)
                dialog.reject()

        QTimer.singleShot(0, exclude_die_002)
        parent.data_selection_action.trigger()
        self.assertEqual(errors, [])
        for child in (parent.open_stage_workspace("preview"), parent.open_correlation_workspace()):
            self.addCleanup(self.close_window, child)
            self.assertEqual(len(child.model.frame()), 4)
            self.assertEqual(len(child.participating_positions(child.model.frame())), 3)
            child.copy_from_wkb_action.trigger()
            child.set_table(raw, "Manual measurements")
            self.assertEqual(set().union(*child.selection["groups"].values()), {0, 1, 2, 3})
            child.copy_from_wkb_action.trigger()
            self.assertTrue(child.workbook_selection_action.isChecked())
            self.assertTrue(child.workbook_selection_action.isEnabled())
            self.assertEqual(len(child.model.frame()), 4)
            self.assertEqual(len(child.participating_positions(child.model.frame())), 3)


if __name__ == "__main__":
    unittest.main()
