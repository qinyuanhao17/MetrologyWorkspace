"""Workbook launch choices and Analysis settings before the first draw."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from PyQt6.QtWidgets import QApplication, QFileDialog, QLabel, QMessageBox
from PyQt6.QtCore import Qt, QTimer

from metrology_app.matching_window import MatchingWindow
from metrology_app.workspace_store import load_workspace

APP = QApplication.instance() or QApplication([])


class WorkbookStartupTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.path = Path(self.scratch.name) / "project.wkb"
        self.windows = []
        source = self.window()
        source.set_reference_frame(pd.DataFrame({"CD Reference": [2., 4., 6.]}), "Ref")
        source.set_raw_frame(pd.DataFrame({"Wafer ID": ["001"] * 3,
                                          "Die Seq": [1, 2, 3], "CD": [1., 2., 3.]}), "Raw")
        source.run_analysis()
        source.save_workbook(self.path)

    def window(self):
        window = MatchingWindow()
        self.windows.append(window)
        return window

    def tearDown(self):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            for window in self.windows:
                window.close()
                window.deleteLater()
        APP.processEvents()
        self.scratch.cleanup()

    def test_open_settings_are_unsaved_until_the_workbook_is_saved(self):
        original = self.path.read_bytes()
        window = self.window()
        window.load_workbook(self.path, analysis_settings={
            "match_type": "TEM", "bias_views": ["percent"], "bias_mode": "percent",
            "trend_axis_settings": {"mode": "dual", "ratio": 2.75}, "result_mode": "preview",
        })
        APP.processEvents()
        self.assertEqual(window.workbook.match_type, "TEM")
        self.assertEqual(window.workbook.bias_views, ("percent",))
        self.assertEqual(window.second_axis_ratio, 2.75)
        self.assertEqual(window.trend_axis_mode, "dual")
        self.assertTrue(window.document.is_dirty())
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(window.document.baseline.states["match"]["match_type"], "KLA")
        window.save_workbook(self.path)
        self.assertFalse(window.document.is_dirty())
        self.assertEqual(load_workspace(self.path).states["match"]["match_type"], "TEM")

    def test_new_workbook_settings_page_starts_from_the_saved_defaults(self):
        """Only New asks for launch settings, and it validates them first."""
        from metrology_app.workbook_startup import WorkbookStartupDialog
        dialog = WorkbookStartupDialog(new=True)
        try:
            self.assertIsNone(dialog.path)
            self.assertEqual(dialog.stack.currentIndex(), 1)
            self.assertEqual(dialog.confirm_button.text(), "Create Workbook")
            self.assertEqual(dialog.settings()["match_type"], "KLA")
            self.assertEqual(dialog.axis_ratio.value(), 10.)
            dialog.match_type.setCurrentText("TEM")
            dialog.axis_mode.setCurrentIndex(dialog.axis_mode.findData("dual"))
            dialog.axis_ratio.setValue(2.75)
            self.assertFalse(dialog.axis_ratio.isEnabled())
            dialog.absolute_bias.setChecked(False)
            self.assertFalse(dialog.confirm_button.isEnabled())
            self.assertIn("Bias", dialog.error.text())
            dialog.percent_bias.setChecked(True)
            self.assertTrue(dialog.confirm_button.isEnabled())
            dialog.confirm_button.click()
            self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
            self.assertEqual(dialog.settings()["bias_views"], ["percent"])
        finally:
            dialog.deleteLater()
            APP.processEvents()

    def test_cancelled_launch_does_not_leave_a_workbook_window(self):
        from metrology_app.shell import MainWindow
        from metrology_app.workbook_startup import WorkbookStartupDialog
        shell = MainWindow()
        self.windows.append(shell)

        def cancel():
            dialog = APP.activeModalWidget()
            if isinstance(dialog, WorkbookStartupDialog):
                dialog.cancel_button.click()

        QTimer.singleShot(0, cancel)
        shell.module_buttons["card_matching"].click()
        APP.processEvents()
        self.assertEqual(shell.loaded_component_ids, ())

    def test_opening_a_workbook_skips_the_settings_page(self):
        """Open WKB loads the file's own choices; no launch page appears."""
        window = self.windows[0]
        window.match_type.setCurrentText("TEM")
        APP.processEvents()

        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(self.path), "")):
            window.open_wkb_dialog()
        APP.processEvents()
        self.assertEqual(window.workbook_path, self.path.resolve())
        self.assertEqual(window.match_type.currentText(), "KLA")
        self.assertFalse(window.document.is_dirty())

        # Cancelling the unsaved-draft prompt keeps the workbook untouched.
        window.match_type.setCurrentText("TEM")
        APP.processEvents()
        before = window.workspace_snapshot()
        self.assertTrue(window.document.is_dirty())
        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(self.path), "")), \
                patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            window.open_wkb_dialog()
        APP.processEvents()
        self.assertEqual(window.match_type.currentText(), "TEM")
        self.assertTrue(window.document.is_dirty())
        for name, frame in before.frames.items():
            pd.testing.assert_frame_equal(window.workspace_snapshot().frames[name], frame)

    def test_saved_choices_open_clean_and_missing_final_inputs_open_as_a_draft(self):
        window = self.window()
        saved = load_workspace(self.path).states["match"]
        window.load_workbook(self.path, analysis_settings=saved)
        APP.processEvents()
        self.assertFalse(window.document.is_dirty())
        window.load_workbook(self.path, analysis_settings={**saved, "result_mode": "final"})
        APP.processEvents()
        self.assertEqual(window.mode_tabs.currentIndex(), 1)
        self.assertIsNone(window.result)
        self.assertFalse(window.run_action.isEnabled())
        self.assertTrue(window.document.is_dirty())
        self.assertEqual(window.raw_model.document_frame().shape[0], 3)

    def test_new_workbook_uses_confirmed_settings_before_the_window_opens(self):
        from metrology_app.shell import MainWindow
        from metrology_app.workbook_startup import WorkbookStartupDialog
        shell = MainWindow()
        self.windows.append(shell)

        def create():
            dialog = APP.activeModalWidget()
            if isinstance(dialog, WorkbookStartupDialog):
                dialog.new_button.click()
                dialog.match_type.setCurrentText("TEM")
                dialog.axis_ratio.setValue(3.125)
                dialog.confirm_button.click()

        QTimer.singleShot(0, create)
        shell.module_buttons["card_matching"].click()
        APP.processEvents()
        child = shell.loaded_components["card_matching"][0]
        self.assertEqual(child.match_type.currentText(), "TEM")
        self.assertEqual(child.second_axis_ratio, 3.125)
        self.assertIsNone(child.workbook_path)
        self.assertTrue(child.reference_frame.empty)

    def test_shell_open_uses_the_saved_choices_without_a_settings_page(self):
        from metrology_app.shell import MainWindow
        shell = MainWindow()
        self.windows.append(shell)
        child = shell.load_path(self.path)
        APP.processEvents()
        self.assertIsNone(APP.activeModalWidget())
        self.assertEqual(child.workbook_path, self.path.resolve())
        self.assertFalse(child.document.is_dirty())
        self.assertEqual(child.match_type.currentText(), "KLA")

    def test_shell_recent_choice_opens_the_workbook_straight_away(self):
        """Picking a recent workbook never shows the settings page again."""
        from metrology_app.settings import remember_recent_wkb
        from metrology_app.shell import MainWindow
        from metrology_app.workbook_startup import WorkbookStartupDialog
        remember_recent_wkb(self.path)
        shell = MainWindow()
        self.windows.append(shell)
        observed = {}

        def choose_recent():
            dialog = APP.activeModalWidget()
            if isinstance(dialog, WorkbookStartupDialog):
                item = dialog.recent_list.item(0)
                dialog.recent_list.itemClicked.emit(item)
                observed["result"] = dialog.result()
                observed["page"] = dialog.stack.currentIndex()

        QTimer.singleShot(0, choose_recent)
        shell.module_buttons["card_matching"].click()
        APP.processEvents()
        child = shell.loaded_components["card_matching"][0]
        self.assertEqual(observed["result"], WorkbookStartupDialog.DialogCode.Accepted)
        self.assertEqual(observed["page"], 0)
        self.assertEqual(child.workbook_path, self.path.resolve())
        self.assertFalse(child.document.is_dirty())
        self.assertEqual(child.match_type.currentText(), "KLA")

    def test_new_cancel_and_unsaved_prompt_cancel_keep_the_active_document(self):
        from metrology_app.workbook_startup import WorkbookStartupDialog
        window = self.windows[0]
        window.raw_model.edit({(1, 2): "9.999"})
        APP.processEvents()
        before = window.raw_model.document_frame().copy()

        def new():
            dialog = APP.activeModalWidget()
            if isinstance(dialog, WorkbookStartupDialog):
                dialog.match_type.setCurrentText("NOVA")
                dialog.confirm_button.click()

        QTimer.singleShot(0, new)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            window.new_action.trigger()
        pd.testing.assert_frame_equal(window.raw_model.document_frame(), before)
        self.assertEqual(window.workbook_path, self.path.resolve())
        self.assertTrue(window.document.is_dirty())

    def test_existing_no_bias_draft_opens_clean_and_can_add_a_view_after(self):
        source = self.windows[0]
        source.absolute_bias.setChecked(False)
        source.percent_bias.setChecked(False)
        source.save_workbook(self.path)
        window = self.window()
        window.load_workbook(self.path)
        APP.processEvents()
        self.assertFalse(window.absolute_bias.isChecked())
        self.assertFalse(window.percent_bias.isChecked())
        self.assertFalse(window.document.is_dirty())
        window.percent_bias_action.trigger()
        APP.processEvents()
        self.assertTrue(window.percent_bias.isChecked())
        self.assertTrue(window.document.is_dirty())

    def test_saved_bias_choices_are_reflected_in_the_analysis_menu(self):
        source = self.windows[0]
        source.apply_analysis_settings({"match_type": "NOVA", "bias_views": ["percent"],
                                        "bias_mode": "percent", "result_mode": "preview",
                                        "trend_axis_settings": {"mode": "auto", "ratio": 3.125}})
        source.save_workbook(self.path)
        window = self.window()
        window.load_workbook(self.path, analysis_settings=load_workspace(self.path).states["match"])
        self.assertFalse(window.absolute_bias_action.isChecked())
        self.assertTrue(window.percent_bias_action.isChecked())
        self.assertFalse(window.document.is_dirty())

    def test_recent_list_only_offers_match_workbooks_and_opens_the_clicked_one(self):
        from metrology_app.settings import remember_recent_wkb
        from metrology_app.workspace_store import WorkspaceSnapshot, save_workspace
        from metrology_app.workbook_startup import (
            WorkbookStartupDialog, saved_time_text,
        )
        tool = save_workspace(self.path.parent / "tool.wmap", WorkspaceSnapshot(
            "wafer_map", {"input_data": pd.DataFrame({"CD": ["1"]})}, {"ui": {}}))
        legacy_tool = self.path.parent / "tool.wkb"
        tool.rename(legacy_tool)
        remember_recent_wkb(legacy_tool)
        remember_recent_wkb(self.path)
        dialog = WorkbookStartupDialog()
        try:
            self.assertEqual(dialog.recent_list.count(), 1)
            item = dialog.recent_list.item(0)
            self.assertEqual(
                Path(item.data(Qt.ItemDataRole.UserRole)).resolve(),
                self.path.resolve(),
            )
            self.assertEqual(Path(item.toolTip()).resolve(), self.path.resolve())
            row = dialog.recent_list.itemWidget(item)
            texts = [label.text() for label in row.findChildren(QLabel)]
            self.assertIn(self.path.name, texts)
            self.assertIn(saved_time_text(self.path), texts)
            folders = {
                Path(label.toolTip()).resolve()
                for label in row.findChildren(QLabel) if label.toolTip()
            }
            self.assertIn(self.path.parent.resolve(), folders)
            dialog.recent_list.itemClicked.emit(item)
            self.assertEqual(dialog.path, self.path.resolve())
            self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
        finally:
            dialog.deleteLater()
            APP.processEvents()

    def test_confirmed_new_workbook_resets_the_window_without_rewriting_its_old_file(self):
        from metrology_app.workbook_startup import WorkbookStartupDialog
        window = self.windows[0]
        old = self.path.read_bytes()

        def new():
            dialog = APP.activeModalWidget()
            if isinstance(dialog, WorkbookStartupDialog):
                dialog.match_type.setCurrentText("NOVA")
                dialog.confirm_button.click()

        QTimer.singleShot(0, new)
        window.new_action.trigger()
        APP.processEvents()
        self.assertIsNone(window.workbook_path)
        self.assertTrue(window.reference_frame.empty)
        self.assertTrue(window.raw_frame.empty)
        self.assertEqual(window.match_type.currentText(), "NOVA")
        self.assertEqual(self.path.read_bytes(), old)
