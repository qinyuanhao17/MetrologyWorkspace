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
            self.assertEqual(len(child.model.document_frame()), 3)
            child.full_data_action.trigger()
            self.assertEqual(len(child.model.document_frame()), 4)
            if child.workspace_type == "wafer_map":
                QTimer.singleShot(0, exclude_first)
                child.data_selection_action.trigger()
                self.assertEqual(failures, [])
        with TemporaryDirectory() as folder:
            path = Path(folder) / "full-data-scope.wkb"
            parent.save_workbook(path)
            legacy = Path(folder) / "legacy-full-data-scope.wkb"
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
                            self.assertEqual(len(child.reference_model.document_frame()), 4)
                        child.workbook_selection_action.trigger()
                        self.assertTrue(child.workbook_selection_action.isChecked())
                        self.assertFalse(child.full_data_action.isChecked())
                        self.assertEqual(len(child.model.document_frame()), 3)
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
        self.assertEqual(copied["CD"].tolist(), ["9.1", "9.2", "9.3", "9.4"])
        self.assertEqual(copied.columns.tolist(), ["Wafer ID", "Die Seq", "X", "Y", "CD", "Depth"])
        with TemporaryDirectory() as folder:
            path = Path(folder) / "protected-copy.wkb"
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
                copies = [action for action in child.data_menu.actions() if action.text() == "Copy from WKB"]
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
                    self.assertFalse(child.reference_model.frame().empty)
                    pd.testing.assert_frame_equal(child.reference_model.document_frame(),
                                                  copied.frames["reference_data"])
                    for page in pages:
                        self.assertEqual({key[0] for key in page.selector.wafers}, {"Reference", "Raw Data"})
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
        choice = next(action for action in child.data_menu.actions() if action.text() == "Copy from WKB")
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
        choice = next(action for action in child.data_menu.actions() if action.text() == "Copy from WKB")
        choice.trigger()
        with TemporaryDirectory() as folder:
            path = Path(folder) / "copy-choice.wkb"
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
            copied = next(action for action in reopened.data_menu.actions() if action.text() == "Copy from WKB")
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
            choice = next(action for action in child.data_menu.actions() if action.text() == "Copy from WKB")
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
            self.assertEqual(len(child.model.frame()), 3)
            child.copy_from_wkb_action.trigger()
            child.set_table(raw, "Manual measurements")
            self.assertEqual(set().union(*child.selection["groups"].values()), {0, 1, 2, 3})
            child.copy_from_wkb_action.trigger()
            self.assertTrue(child.workbook_selection_action.isChecked())
            self.assertTrue(child.workbook_selection_action.isEnabled())
            self.assertEqual(len(child.model.frame()), 3)


if __name__ == "__main__":
    unittest.main()
