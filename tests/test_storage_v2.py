"""Accepted design scenarios through file and document/window operations."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import os
import sqlite3
from contextlib import closing

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog, QLineEdit, QMessageBox
from metrology_app.matching_window import MatchingWindow
from metrology_app.workspace_store import EXTENSIONS, WorkspaceSnapshot, load_workspace, save_workspace
from metrology_app.window import MainWindow

APP = QApplication.instance() or QApplication([])


class StorageV2Tests(unittest.TestCase):
    def test_background_recovery_preserves_each_child_draft_and_its_accepted_basis(self):
        from time import monotonic
        self.match.preview_dynamic_frame = self.match.raw_frame.copy()
        wafer = self.match.open_stage_workspace("preview")
        dynamic = self.match.open_dynamic_workspace("preview")
        self.match.save_workbook(self.folder / "project.wkb")
        column = dynamic.model.document_frame().columns.get_loc("CD")
        original_value = dynamic.model.document_frame().iloc[0, column]
        dynamic.model.edit({(1, column): "99.0000"})
        wafer.plot_page.font_size.setCurrentText("12")
        self.match.document.recovery_path = self.folder / "draft.wkb"
        self.match.document.request_recovery()
        deadline = monotonic() + 5
        while self.match.document.recovery_pending and monotonic() < deadline:
            QTest.qWait(10)
        self.assertFalse(self.match.document.recovery_pending)
        restored = MatchingWindow()
        try:
            restored.document.recover(self.match.document.recovery_path)
            reopened = restored.open_dynamic_workspace("preview")
            self.assertEqual(reopened.model.document_frame().iloc[0, column], "99.0000")
            recovered_wafer = restored.open_stage_workspace("preview")
            self.assertEqual(recovered_wafer.plot_page.font_size.currentText(), "12")
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                reopened.close()
            reopened = restored.open_dynamic_workspace("preview")
            self.assertEqual(reopened.model.document_frame().iloc[0, column], original_value)
            self.assertTrue(recovered_wafer.document.is_dirty(), "Discarding Dynamic must keep the Map draft")
        finally:
            restored.document.force_close = True
            restored.close()
            restored.deleteLater()
            APP.processEvents()

    def test_recovery_interval_updates_managed_and_independent_windows_without_starting_child_writers(self):
        from metrology_app.settings import get_settings, save_settings
        from metrology_app.settings_dialog import SettingsDialog
        before = get_settings()
        child = self.match.open_stage_workspace("preview")
        independent = MainWindow()
        dialog = SettingsDialog()
        try:
            self.match.save_workbook(self.folder / "project.wkb")
            dialog.recovery_interval.setValue(180)
            dialog.save()
            self.assertEqual(self.match.document.timer.interval(), 180_000)
            self.assertEqual(independent.document.timer.interval(), 180_000)
            self.assertEqual(child.document.timer.interval(), 180_000)
            self.assertTrue(self.match.document.timer.isActive())
            self.assertTrue(independent.document.timer.isActive())
            self.assertFalse(child.document.timer.isActive(), "Only the Workbook owner may write aggregate recovery")
            self.assertFalse(self.match.document.is_dirty(), "Global recovery settings are not document edits")
            self.assertFalse(child.document.is_dirty())
            reopened = MainWindow()
            try:
                self.assertEqual(reopened.document.timer.interval(), 180_000)
            finally:
                reopened.document.force_close = True
                reopened.close()
                reopened.deleteLater()
        finally:
            save_settings(before)
            from metrology_app.workspace_document import apply_recovery_settings
            apply_recovery_settings()
            dialog.deleteLater()
            independent.document.force_close = True
            independent.close()
            independent.deleteLater()
            APP.processEvents()

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.folder = Path(self.scratch.name).resolve()
        self.match = MatchingWindow()
        self.match.set_reference_frame(pd.DataFrame({"CD Reference": [2., 4., 6.]}), "Ref")
        self.match.set_raw_frame(pd.DataFrame({"Wafer ID": ["001"] * 3,
                                             "Die Seq": [1, 2, 3], "CD": [1., 2., 3.]}), "Raw")
        self.match.run_analysis()

    def tearDown(self):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.match.close()
        self.match.deleteLater()
        APP.processEvents()
        self.scratch.cleanup()

    def test_copy_contains_current_child_draft_without_saving_match(self):
        child = self.match.open_stage_workspace("preview")
        original = self.match.save_workbook(self.folder / "project.wkb")
        accepted = original.read_bytes()
        column = child.model.document_frame().columns.get_loc("CD")
        child.model.edit({(1, column): "9.999"})
        saved = child.export_standalone_copy(self.folder / "copy.wmap")
        copy = load_workspace(saved)
        self.assertEqual(copy.frames["input_data"].iloc[0, column], "9.999")
        self.assertTrue(child.document.is_dirty())
        self.assertEqual(original.read_bytes(), accepted)
        self.assertEqual(self.match.workbook_path, original)
        self.assertNotIn("recovery", copy.states)

    def test_subwindow_has_no_hidden_save_as_shortcut(self):
        child = self.match.open_stage_workspace("preview")
        child.show()
        child.activateWindow()
        APP.processEvents()
        self.assertEqual(child.save_workspace_action.text(), "Save Changes to Workbook")
        self.assertNotIn(child.save_as_workspace_action, child.file_menu.actions())
        self.assertTrue(child.save_as_workspace_action.shortcut().isEmpty())
        with patch.object(QFileDialog, "getSaveFileName") as dialog:
            QTest.keyClick(child, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
            APP.processEvents()
            dialog.assert_not_called()
        self.assertIn("Unsaved Match Workbook", child.ownership_label.text())

    def test_export_keeps_active_cell_input_without_forcing_draw(self):
        child = self.match.open_stage_workspace("preview")
        child.show()
        child.activateWindow()
        APP.processEvents()
        col = child.model.document_frame().columns.get_loc("CD")
        child.sheet.setCurrentIndex(child.model.index(1, col))
        child.sheet.edit(child.model.index(1, col))
        editor = child.sheet.findChild(QLineEdit)
        self.assertIsNotNone(editor)
        editor.setText("2.1000")
        editor.setFocus()
        saved = child.export_standalone_copy(self.folder / "typed.wmap")
        self.assertEqual(load_workspace(saved).frames["input_data"].iloc[0, col], "2.1000")
        self.assertTrue(child.document.is_dirty())
        self.assertFalse(child.plot_page.has_drawn_once)

    def test_copy_cannot_overwrite_owner_or_samefile_alias(self):
        child = self.match.open_stage_workspace("preview")
        original = self.match.save_workbook(self.folder / "project.wkb")
        before = original.read_bytes()
        alias = self.folder / "alias.wmap"
        os.link(original, alias)
        with patch.object(QMessageBox, "warning") as warning:
            self.assertIsNone(child.export_standalone_copy(alias))
            warning.assert_called_once()
        self.assertEqual(original.read_bytes(), before)

    def test_reopen_same_scope_only_activates_existing_draft(self):
        child = self.match.open_stage_workspace("preview")
        col = child.model.document_frame().columns.get_loc("CD")
        child.model.edit({(1, col): "9.999"})
        child.plot_page.font_size.setCurrentText("14")
        self.assertIs(self.match.open_stage_workspace("preview"), child)
        self.assertEqual(child.model.document_frame().iloc[0, col], "9.999")
        self.assertEqual(child.plot_page.font_size.currentText(), "14")

    def test_shared_axis_change_is_parent_dirty_not_child_local_edit(self):
        child = self.match.open_correlation_workspace()
        self.match.save_workbook(self.folder / "project.wkb")
        self.match.set_second_axis_ratio(2.75)
        self.match.set_trend_axis_mode("dual")
        self.assertTrue(self.match.document.is_dirty())
        self.assertFalse(child.document.is_dirty())
        with patch.object(QMessageBox, "question") as question:
            self.assertTrue(child.close())
            question.assert_not_called()
        self.assertEqual(self.match.second_axis_ratio, 2.75)

    def test_failed_child_save_keeps_file_and_discard_baseline(self):
        child = self.match.open_stage_workspace("preview")
        path = self.match.save_workbook(self.folder / "project.wkb")
        accepted = path.read_bytes()
        old = child.model.document_frame().copy()
        col = old.columns.get_loc("CD")
        child.model.edit({(1, col): "99"})
        real_replace = os.replace
        def fail_formal(source, target):
            if Path(target).resolve() == path:
                raise PermissionError("target in use")
            return real_replace(source, target)
        with patch.object(os, "replace", side_effect=fail_formal), patch.object(QMessageBox, "warning"):
            self.assertIsNone(child.save_wkb())
        self.assertEqual(path.read_bytes(), accepted)
        self.assertTrue(child.document.is_dirty())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            child.close()
        pd.testing.assert_frame_equal(self.match.open_stage_workspace("preview").model.document_frame(), old)

    def test_new_edit_during_atomic_write_is_not_marked_saved(self):
        child = self.match.open_stage_workspace("preview")
        path = self.match.save_workbook(self.folder / "project.wkb")
        col = child.model.document_frame().columns.get_loc("CD")
        child.model.edit({(1, col): "10"})
        real_replace = os.replace
        def edit_during_replace(source, target):
            if Path(target).resolve() == path:
                child.model.edit({(1, col): "11"})
            return real_replace(source, target)
        with patch.object(os, "replace", side_effect=edit_during_replace):
            self.assertTrue(child.save_wkb())
        self.assertEqual(load_workspace(path).frames["preview_map"].iloc[0, col], "10")
        self.assertEqual(child.model.document_frame().iloc[0, col], "11")
        self.assertTrue(child.document.is_dirty())

    def test_old_tool_wkb_requires_explicit_typed_save_as(self):
        snapshot = WorkspaceSnapshot("wafer_map", {"input_data": pd.DataFrame({"CD": ["2.1000"]})}, {"ui": {}})
        old = save_workspace(self.folder / "old.wmap", snapshot).rename(self.folder / "old.wkb")
        original = old.read_bytes()
        window = MainWindow()
        try:
            window.load_workspace(old)
            window.model.edit({(1, 0): "3.00"})
            with patch.object(QFileDialog, "getSaveFileName", return_value=("", "")):
                self.assertIsNone(window.save_wkb())
            self.assertEqual(window.workspace_path, old)
            self.assertTrue(window.document.is_dirty())
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(self.folder / "new.wmap"), "")):
                self.assertEqual(window.save_wkb(), self.folder / "new.wmap")
            self.assertEqual(old.read_bytes(), original)
            self.assertEqual(load_workspace(self.folder / "new.wmap").frames["input_data"].iloc[0, 0], "3.00")
        finally:
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_recovery_uses_version_gate_and_formal_save_removes_recovery_tables(self):
        child = self.match.open_stage_workspace("preview")
        self.match.save_workbook(self.folder / "project.wkb")
        child.model.edit({(1, child.model.document_frame().columns.get_loc("CD")): "10"})
        self.match.document.recovery_path = self.folder / "recovery.wkb"
        self.match.document.write_recovery()
        recovery = self.match.document.recovery_path
        with closing(sqlite3.connect(recovery)) as connection:
            self.assertEqual(connection.execute("SELECT state_version FROM workspace_state WHERE scope='recovery'").fetchone()[0], 2)
        restored = MatchingWindow()
        try:
            restored.load_workbook(recovery)
            saved = restored.save_workbook(self.folder / "restored.wkb")
            snapshot = load_workspace(saved)
            self.assertNotIn("recovery", snapshot.states)
            self.assertFalse(any(name.startswith("__recovery__.") for name in snapshot.frames))
        finally:
            restored.close()
            restored.deleteLater()
            APP.processEvents()

    def test_application_exit_preserves_discard_edits_when_later_save_fails(self):
        from metrology_app.shell import MainWindow as Shell
        shell = Shell()
        try:
            first = shell.open_component("wafer_map")
            second = shell.open_component("dynamic_analysis")
            first.set_table(pd.DataFrame({"CD": ["1"]}), "Raw")
            second.set_table(pd.DataFrame({"Die Seq": [1], "CD": ["2"]}), "Raw")
            with patch.object(QMessageBox, "question", side_effect=[QMessageBox.StandardButton.Discard,
                                                                    QMessageBox.StandardButton.Save]), \
                    patch.object(QFileDialog, "getSaveFileName", return_value=("", "")):
                self.assertFalse(shell.close())
            self.assertTrue(first.isVisible())
            self.assertTrue(second.isVisible())
            self.assertEqual(first.model.document_frame().iloc[0, 0], "1")
            self.assertTrue(first.document.is_dirty())
        finally:
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                shell.close()
            shell.deleteLater()
            APP.processEvents()

    def test_all_child_copies_are_editable_and_include_full_actual_sources(self):
        from metrology_app.dynamic_window import DynamicWindow
        self.match.preview_dynamic_frame = self.match.raw_frame.copy()
        from metrology_app.correlation_window import CorrelationWindow
        for kind, child, factory in (
            ("wafer_map", self.match.open_stage_workspace("preview"), MainWindow),
            ("dynamic", self.match.open_dynamic_workspace("preview"), DynamicWindow),
            ("correlation_trend", self.match.open_correlation_workspace(), CorrelationWindow),
        ):
            with self.subTest(kind=kind):
                restored = factory()
                try:
                    if kind == "correlation_trend":
                        self.match.set_second_axis_ratio(2.75)
                        self.match.set_trend_axis_mode("dual")
                        child.sequence_page.set_overlay("CD", "CD", "Reference", "Raw Data")
                    snapshot = child.workspace_snapshot()
                    saved = child.export_standalone_copy(self.folder / (kind + EXTENSIONS[kind]))
                    restored.load_workspace(saved)
                    for name, frame in snapshot.frames.items():
                        pd.testing.assert_frame_equal(restored.workspace_snapshot().frames[name], frame)
                    if kind == "correlation_trend":
                        self.assertEqual(restored.sequence_page.source_overlay, child.sequence_page.source_overlay)
                        self.assertEqual(restored.sequence_page.axis_ratio_limit(), 2.75)
                        self.assertEqual(restored.sequence_page.axis_mode_value(), "dual")
                    restored.model.edit({(1, restored.model.document_frame().columns.get_loc("CD")): "123"})
                    self.assertTrue(restored.save_wkb())
                    self.assertNotEqual(child.model.document_frame().iloc[0, child.model.document_frame().columns.get_loc("CD")], "123")
                finally:
                    restored.close()
                    restored.deleteLater()
                    APP.processEvents()

    def test_independent_readonly_document_save_requests_new_path(self):
        window = MainWindow()
        try:
            window.set_table(pd.DataFrame({"CD": ["1"]}), "Raw")
            original = window.document.save(self.folder / "readonly.wmap")
            old = original.read_bytes()
            original.chmod(0o444)
            try:
                window.model.edit({(1, 0): "2"})
                with patch.object(QFileDialog, "getSaveFileName", return_value=(str(self.folder / "writable.wmap"), "")) as dialog:
                    self.assertTrue(window.save_wkb())
                    dialog.assert_called_once()
                self.assertEqual(original.read_bytes(), old)
            finally:
                original.chmod(0o666)
        finally:
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_untrusted_old_recovery_requires_whole_save_as_for_local_discard(self):
        child = self.match.open_stage_workspace("preview")
        child.model.edit({(1, child.model.document_frame().columns.get_loc("CD")): "99"})
        flat = self.match.workspace_snapshot(include_drafts=True)
        flat.states["recovery"] = {"original_path": "", "revision": None}
        path = save_workspace(self.folder / "old-recovery.wkb", flat)
        restored = MatchingWindow()
        try:
            restored.load_workbook(path)
            reopened = restored.open_stage_workspace("preview")
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard), \
                    patch.object(QMessageBox, "warning"):
                self.assertFalse(reopened.close())
            saved = restored.save_workbook(self.folder / "new-baseline.wkb")
            self.assertFalse(restored.document.untrusted_recovery)
            self.assertTrue(saved.exists())
            reopened.model.edit({(1, reopened.model.document_frame().columns.get_loc("CD")): "100"})
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                self.assertTrue(reopened.close())
        finally:
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                restored.close()
            restored.deleteLater()
            APP.processEvents()

    def test_future_recovery_version_is_rejected_before_changing_window(self):
        self.match.document.recovery_path = self.folder / "recovery.wkb"
        self.match.document.write_recovery()
        path = self.match.document.recovery_path
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("UPDATE workspace_state SET state_version=3 WHERE scope='recovery'")
        before = self.match.raw_model.document_frame().copy()
        with self.assertRaisesRegex(ValueError, "version"):
            self.match.load_workbook(path)
        pd.testing.assert_frame_equal(self.match.raw_model.document_frame(), before)

    def test_successful_file_is_accepted_even_if_title_update_fails(self):
        child = self.match.open_stage_workspace("preview")
        path = self.match.save_workbook(self.folder / "project.wkb")
        child.model.edit({(1, child.model.document_frame().columns.get_loc("CD")): "10"})
        with patch.object(child, "setWindowTitle", side_effect=RuntimeError("display unavailable")):
            self.assertTrue(child.save_wkb())
        self.assertFalse(child.document.is_dirty())
        self.assertEqual(load_workspace(path).frames["preview_map"].iloc[0, child.model.document_frame().columns.get_loc("CD")], "10")

    def test_explicit_workbook_data_reset_is_confirmed_and_remains_a_draft(self):
        child = self.match.open_stage_workspace("preview")
        path = self.match.save_workbook(self.folder / "project.wkb")
        col = child.model.document_frame().columns.get_loc("CD")
        child.model.edit({(1, col): "99"})
        self.assertTrue(child.save_wkb())
        self.match.raw_model.edit({(1, self.match.raw_model.document_frame().columns.get_loc("CD")): "8"})
        self.match.raw_frame = self.match.raw_model.frame()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.match.reset_child_to_workbook(child))
        self.assertEqual(child.model.document_frame().iloc[0, col], "99")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(self.match.reset_child_to_workbook(child))
        self.assertEqual(float(child.model.document_frame().iloc[0, col]), 8.)
        self.assertTrue(child.document.is_dirty())
        self.assertTrue(child.save_wkb())
        self.assertFalse(load_workspace(path).states["map.preview"]["data_override"])

    def test_tem_independent_analyses_cannot_reset_to_workbook_data(self):
        self.match.match_type.setCurrentText("TEM")
        for stage in ("preview", "final"):
            for opener in (self.match.open_stage_workspace, self.match.open_dynamic_workspace):
                with self.subTest(stage=stage, opener=opener.__name__):
                    child = opener(stage)
                    action = next(action for action in child.file_menu.actions()
                                  if action.text() == "Use Workbook Data…")
                    self.assertFalse(action.isVisible())
                    self.assertFalse(action.isEnabled())
                    child.set_table(pd.DataFrame({"Wafer ID": ["001", "001"], "Die Seq": [1, 2],
                                                  "CD": ["9.999", "2.1000"]}), "Independent TEM")
                    before = child.workspace_snapshot()
                    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard) as question:
                        self.assertFalse(self.match.reset_child_to_workbook(child))
                        question.assert_not_called()
                    after = child.workspace_snapshot()
                    self.assertEqual(after.states, before.states)
                    for name, frame in before.frames.items():
                        pd.testing.assert_frame_equal(after.frames[name], frame)

    def test_workbook_data_menu_tracks_match_type_without_reopening_children(self):
        children = [self.match.open_stage_workspace(stage) for stage in ("preview", "final")]
        children += [self.match.open_dynamic_workspace(stage) for stage in ("preview", "final")]
        correlation = self.match.open_correlation_workspace()
        for mode in ("TEM", "NOVA", "KLA", "TEM"):
            self.match.match_type.setCurrentText(mode)
            for child in children + [correlation]:
                with self.subTest(mode=mode, title=child.windowTitle()):
                    actions = [action for action in child.file_menu.actions()
                               if action.text() == "Use Workbook Data…"]
                    self.assertEqual(len(actions), 1)
                    self.assertEqual(actions[0].isVisible(), mode != "TEM" or child is correlation)
                    self.assertEqual(actions[0].isEnabled(), mode != "TEM" or child is correlation)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as question:
            self.assertFalse(self.match.reset_child_to_workbook(correlation))
            question.assert_called_once()

    def test_save_as_cancel_then_success_changes_only_current_path(self):
        window = MainWindow()
        try:
            window.set_table(pd.DataFrame({"CD": ["1"]}), "Raw")
            original = window.document.save(self.folder / "original.wmap")
            old = original.read_bytes()
            window.model.edit({(1, 0): "2"})
            with patch.object(QFileDialog, "getSaveFileName", return_value=("", "")):
                self.assertIsNone(window.save_wkb_as())
            self.assertEqual(window.workspace_path, original)
            self.assertTrue(window.document.is_dirty())
            target = self.folder / "renamed.wmap"
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")):
                self.assertEqual(window.save_wkb_as(), target)
            self.assertFalse(window.document.is_dirty())
            self.assertEqual(original.read_bytes(), old)
        finally:
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_parent_close_prompts_for_child_editor_that_has_not_lost_focus(self):
        child = self.match.open_stage_workspace("preview")
        self.match.save_workbook(self.folder / "project.wkb")
        child.show()
        child.activateWindow()
        APP.processEvents()
        col = child.model.document_frame().columns.get_loc("CD")
        child.sheet.setCurrentIndex(child.model.index(1, col))
        child.sheet.edit(child.model.index(1, col))
        editor = child.sheet.findChild(QLineEdit)
        editor.setText("9.99")
        editor.setFocus()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as question:
            self.assertFalse(self.match.close())
            question.assert_called_once()
        self.assertEqual(child.model.document_frame().iloc[0, col], "9.99")

    def test_importing_an_independent_workspace_into_child_keeps_match_ownership(self):
        child = self.match.open_stage_workspace("preview")
        original = self.match.save_workbook(self.folder / "project.wkb")
        imported = save_workspace(self.folder / "import.wmap", WorkspaceSnapshot("wafer_map", {
            "input_data": pd.DataFrame({"Wafer ID": ["001"], "Die Seq": [1], "CD": ["7.00"]})}, {"ui": {}}))
        imported_bytes = imported.read_bytes()
        child.show()
        child.activateWindow()
        APP.processEvents()
        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(imported), "")) as dialog:
            QTest.keyClick(child, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
            APP.processEvents()
            dialog.assert_called_once()
        self.assertTrue(child.document.is_dirty())
        self.assertIsNone(child.document.path)
        self.assertIn(original.name, child.ownership_label.text())
        self.assertTrue(child.save_wkb())
        self.assertEqual(imported.read_bytes(), imported_bytes)
        self.assertEqual(load_workspace(original).frames["preview_map"].iloc[0, 2], "7.00")

    def test_recovery_keeps_other_child_draft_and_its_discard_baseline(self):
        self.match.preview_dynamic_frame = self.match.raw_frame.copy()
        wafer = self.match.open_stage_workspace("preview")
        dynamic = self.match.open_dynamic_workspace("preview")
        original = self.match.save_workbook(self.folder / "project.wkb")
        col = dynamic.model.document_frame().columns.get_loc("CD")
        before = dynamic.model.document_frame().copy()
        dynamic.model.edit({(1, col): "99"})
        wafer.plot_page.font_size.setCurrentText("12")
        self.match.document.recovery_path = self.folder / "recovery.wkb"
        self.assertTrue(wafer.save_wkb())
        self.assertTrue(dynamic.document.is_dirty())
        self.assertTrue(self.match.document.recovery_path.exists())
        restored = MatchingWindow()
        try:
            restored.load_workbook(self.match.document.recovery_path)
            reopened = restored.open_dynamic_workspace("preview")
            self.assertEqual(reopened.model.document_frame().iloc[0, col], "99")
            self.assertTrue(reopened.document.is_dirty())
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                reopened.close()
            reopened = restored.open_dynamic_workspace("preview")
            pd.testing.assert_frame_equal(reopened.model.document_frame(), before)
            self.assertEqual(restored.workbook_path, original)
        finally:
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                restored.close()
            restored.deleteLater()
            APP.processEvents()

