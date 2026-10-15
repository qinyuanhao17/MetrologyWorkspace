"""Named analysis drafts through split-button menus and WKB save/reopen."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd
from PyQt6.QtCore import QPoint, QTimer, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox, QMenu
from PyQt6.QtGui import QContextMenuEvent

from metrology_app.matching_window import MatchingWindow
from metrology_app.workspace_document import same_snapshot

APP = QApplication.instance() or QApplication([])


class NamedAnalysisWindowTests(unittest.TestCase):
    def setUp(self):
        self.parent = MatchingWindow()
        self.parent.match_type.setCurrentText("NOVA")
        self.parent.set_reference_frame(pd.DataFrame({"CD Reference": ["2.000", "4.000", "6.000"]}))
        self.parent.set_raw_frame(pd.DataFrame({"Wafer ID": ["W001"] * 3, "Die Seq": ["01", "02", "03"],
                                               "FIELD X": ["-1", "0", "1"], "FIELD Y": ["0"] * 3,
                                               "CD": ["1.000", "2.000", "3.000"]}))
        self.parent.run_analysis()
        self.parent.show()

    def tearDown(self):
        for window in tuple(APP.topLevelWidgets()):
            document = getattr(window, "document", None)
            if document is not None:
                document.force_close = True
                window.close()
                window.deleteLater()
        APP.processEvents()

    def new_window(self, button, name):
        failures = []
        existing = set(APP.topLevelWidgets())

        def name_window():
            dialog = APP.activeModalWidget()
            try:
                self.assertIsInstance(dialog, QInputDialog)
                dialog.setTextValue(name)
                dialog.accept()
            except Exception as error:
                failures.append(error)
                if dialog is not None:
                    dialog.reject()

        menu = button.menu()
        menu.popup(button.mapToGlobal(QPoint(0, button.height())))
        APP.processEvents()
        action = next(action for action in menu.actions() if action.text() == "New window…")
        menu.hide()
        QTimer.singleShot(0, name_window)
        action.trigger()
        self.assertEqual(failures, [])
        APP.processEvents()
        return next(window for window in APP.topLevelWidgets()
                    if window not in existing and name in window.windowTitle()
                    and getattr(window, "workspace_type", "") != "match_workbook")

    def window_choices(self, button):
        menu = button.menu()
        menu.popup(button.mapToGlobal(QPoint(0, button.height())))
        APP.processEvents()
        choices = {action.text(): action for action in menu.actions() if action.isCheckable()}
        menu.hide()
        return choices

    def test_three_split_buttons_open_multiple_named_windows_and_activate_only_checked_ones(self):
        for button, label in ((self.parent.correlation_button, "Correlation"),
                              (self.parent.preview_dynamic_button, "Dynamic"),
                              (self.parent.preview_open_button, "Map")):
            with self.subTest(kind=label):
                first = self.new_window(button, f"{label} baseline")
                second = self.new_window(button, f"{label} adjusted")
                self.assertIsNot(first, second)
                choices = self.window_choices(button)
                self.assertTrue(choices[f"{label} baseline"].isChecked())
                self.assertTrue(choices[f"{label} adjusted"].isChecked())
                choices[f"{label} baseline"].trigger()
                first.hide()
                second.hide()
                button.click()
                self.assertFalse(first.isVisible())
                self.assertTrue(second.isVisible())

    def test_single_click_opens_only_that_window_without_changing_the_checklist(self):
        button = self.parent.preview_open_button
        first = self.new_window(button, "Map baseline")
        second = self.new_window(button, "Map adjusted")
        self.window_choices(button)["Map baseline"].setChecked(False)
        first.hide()
        second.hide()
        menu = button.menu()
        menu.popup(button.mapToGlobal(QPoint(0, button.height())))
        APP.processEvents()
        action = next(item for item in menu.actions() if item.text() == "Map baseline")
        QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())
        QTest.qWait(APP.doubleClickInterval() + 80)
        self.assertTrue(first.isVisible())
        self.assertFalse(second.isVisible())
        self.assertFalse(action.isChecked())
        self.assertFalse(menu.isVisible())

        first.hide()
        menu.popup(button.mapToGlobal(QPoint(0, button.height())))
        APP.processEvents()
        action = next(item for item in menu.actions() if item.text() == "Map baseline")
        rect = menu.actionGeometry(action)
        QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=QPoint(rect.right() - 16, rect.center().y()))
        QTest.qWait(APP.doubleClickInterval() + 80)
        self.assertTrue(action.isChecked())
        self.assertTrue(menu.isVisible())
        self.assertFalse(first.isVisible())
        self.assertFalse(second.isVisible())
        menu.setActiveAction(action)
        QTest.keyClick(menu, Qt.Key.Key_Space)
        self.assertFalse(action.isChecked())
        QTest.keyClick(menu, Qt.Key.Key_Return)
        self.assertTrue(first.isVisible())
        self.assertFalse(action.isChecked())

    def test_context_delete_removes_only_the_chosen_draft_after_confirmation_and_reopen(self):
        button = self.parent.preview_open_button
        keep = self.new_window(button, "Keep Map")
        remove = self.new_window(button, "Delete Map")
        source = self.parent.raw_model.document_frame().copy()
        remove.set_table(source.assign(CD=["9.000", "8.000", "7.000"]), "Independent draft")

        def request_delete(answer, name="Delete Map"):
            menu = button.menu()
            menu.popup(button.mapToGlobal(QPoint(0, button.height())))
            APP.processEvents()
            action = next(item for item in menu.actions() if item.text() == name)
            position = menu.actionGeometry(action).center()
            found = []

            def choose_delete():
                popup = APP.activePopupWidget()
                if isinstance(popup, QMenu) and popup is not menu:
                    delete = next((item for item in popup.actions() if item.text() == "Delete window…"), None)
                    if delete is not None:
                        found.append(True)
                        QTest.mouseClick(popup, Qt.MouseButton.LeftButton, pos=popup.actionGeometry(delete).center())
                    popup.close()
            QTimer.singleShot(0, choose_delete)
            with patch.object(QMessageBox, "question", return_value=answer):
                APP.sendEvent(menu, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, position, menu.mapToGlobal(position)))
            menu.hide()
            APP.processEvents()
            self.assertEqual(found, [True], "Each window needs a right-click Delete action")

        request_delete(QMessageBox.StandardButton.Cancel)
        self.assertIn("Delete Map", self.window_choices(button))
        self.assertTrue(remove.isVisible())
        request_delete(QMessageBox.StandardButton.Yes)
        self.assertNotIn("Delete Map", self.window_choices(button))
        self.assertTrue(keep.isVisible())
        pd.testing.assert_frame_equal(self.parent.raw_model.document_frame(), source)
        with TemporaryDirectory() as folder:
            path = Path(folder) / "deleted-window.wkb"
            self.parent.save_workbook(path)
            restored = MatchingWindow()
            self.addCleanup(lambda: (setattr(restored.document, "force_close", True), restored.close()))
            restored.load_workbook(path)
            choices = self.window_choices(restored.preview_open_button)
            self.assertNotIn("Delete Map", choices)
            self.assertIn("Keep Map", choices)
            snapshot = restored.workspace_snapshot()
            self.assertFalse(any("9.000" in frame.astype(str).values for frame in snapshot.frames.values()))
            for name in ("Keep Map", "Wafer Map / Radius 1"):
                request_delete(QMessageBox.StandardButton.Yes, name)
            self.assertEqual(self.window_choices(button), {})
            self.parent.save_workbook(path)
            empty = MatchingWindow()
            self.addCleanup(lambda: (setattr(empty.document, "force_close", True), empty.close()))
            empty.load_workbook(path)
            self.assertEqual(self.window_choices(empty.preview_open_button), {})
            replacement = self.new_window(empty.preview_open_button, "Fresh Map")
            self.assertTrue(replacement.model.document_frame().empty)
            self.assertEqual(list(self.window_choices(empty.preview_open_button)), ["Fresh Map"])

    def test_new_windows_are_empty_manual_editors_and_remain_empty_after_refresh_and_reopen(self):
        names = ((self.parent.correlation_button, "Blank Correlation"),
                 (self.parent.preview_dynamic_button, "Blank Dynamic"),
                 (self.parent.preview_open_button, "Blank Map"))
        children = []
        raw_before = self.parent.raw_model.document_frame().copy()
        for button, name in names:
            child = self.new_window(button, name)
            children.append(child)
            self.assertTrue(child.sheet.isEnabled())
            self.assertTrue(all(frame.empty for frame in child.workspace_snapshot().frames.values()))
            if hasattr(child, "copy_from_wkb_action"):
                self.assertTrue(child.copy_from_wkb_action.isEnabled())
                self.assertFalse(child.copy_from_wkb_action.isChecked())
            if name == "Blank Correlation":
                self.assertNotIn("match_groups", child.workspace_snapshot().states)
        pd.testing.assert_frame_equal(self.parent.raw_model.document_frame(), raw_before)
        self.parent.raw_model.edit({(1, 5): "9.000"})
        self.parent.run_analysis()
        APP.processEvents()
        self.assertTrue(all(all(frame.empty for frame in child.workspace_snapshot().frames.values())
                            for child in children))
        with TemporaryDirectory() as folder:
            path = Path(folder) / "blank-windows.wkb"
            self.parent.save_workbook(path)
            self.parent.document.force_close = True
            self.parent.close()
            APP.processEvents()
            self.parent = MatchingWindow()
            self.parent.load_workbook(path)
            self.parent.show()
            for button, name in ((self.parent.correlation_button, "Blank Correlation"),
                                 (self.parent.preview_dynamic_button, "Blank Dynamic"),
                                 (self.parent.preview_open_button, "Blank Map")):
                button.click()
                reopened = next(window for window in APP.topLevelWidgets()
                                if name in window.windowTitle() and window.isVisible())
                self.assertTrue(all(frame.empty for frame in reopened.workspace_snapshot().frames.values()))
                if hasattr(reopened, "copy_from_wkb_action"):
                    self.assertFalse(reopened.copy_from_wkb_action.isChecked())

    def test_default_map_is_listed_first_and_copies_raw_while_new_starts_empty(self):
        for match_type in ("NOVA", "KLA"):
            with self.subTest(match_type=match_type):
                self.parent.match_type.setCurrentText(match_type)
                self.parent.run_analysis()
                button = self.parent.preview_open_button
                choices = self.window_choices(button)
                self.assertEqual(next(iter(choices)), "Wafer Map / Radius 1")
                menu = button.menu()
                menu.popup(button.mapToGlobal(QPoint(0, button.height())))
                APP.processEvents()
                action = next(item for item in menu.actions() if item.text() == "Wafer Map / Radius 1")
                QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())
                QTest.qWait(APP.doubleClickInterval() + 80)
                primary = next(window for window in APP.topLevelWidgets()
                               if "Wafer Map / Radius 1" in window.windowTitle() and window.isVisible())
                self.assertTrue(primary.copy_from_wkb_action.isChecked())
                self.assertEqual(pd.to_numeric(primary.model.document_frame()["CD"]).tolist(), [1., 2., 3.])
                new = self.new_window(button, f"{match_type} new")
                self.assertTrue(new.model.document_frame().empty)
                self.assertFalse(new.copy_from_wkb_action.isChecked())
                self.assertTrue(new.copy_from_wkb_action.isEnabled())
                new.copy_from_wkb_action.trigger()
                self.assertTrue(new.copy_from_wkb_action.isChecked())
                self.assertEqual(pd.to_numeric(new.model.document_frame()["CD"]).tolist(), [1., 2., 3.])

    def test_new_windows_are_enabled_without_parent_data_in_preview_and_final(self):
        self.parent.document.force_close = True
        self.parent.close()
        self.parent.deleteLater()
        APP.processEvents()
        self.parent = MatchingWindow()
        self.parent.match_type.setCurrentText("NOVA")
        self.parent.show()
        for stage in ("Preview", "Final"):
            self.parent.result_mode.setCurrentText(stage)
            buttons = ((self.parent.correlation_button, "Correlation"),
                       (self.parent.preview_dynamic_button if stage == "Preview" else self.parent.final_dynamic_button, "Dynamic"),
                       (self.parent.preview_open_button if stage == "Preview" else self.parent.final_open_button, "Map"))
            for button, kind in buttons:
                with self.subTest(stage=stage, kind=kind):
                    self.assertTrue(button.isEnabled())
                    child = self.new_window(button, f"{stage} blank {kind}")
                    self.assertTrue(child.sheet.isEnabled())
                    self.assertTrue(all(frame.empty for frame in child.workspace_snapshot().frames.values()))
                    child.set_table(pd.DataFrame({"Wafer ID": ["MANUAL"], "Die Seq": ["1"], "CD": ["9.000"]}), "Manual measurements")
                    self.assertEqual(child.model.document_frame()["CD"].tolist(), ["9.000"])
        self.assertTrue(self.parent.raw_model.document_frame().empty)
        self.assertTrue(self.parent.reference_model.document_frame().empty)

    def test_named_data_tabs_and_checked_windows_survive_wkb_save_and_reopen_without_cross_overwrite(self):
        expected = {}
        for button, label in ((self.parent.correlation_button, "Correlation"),
                              (self.parent.preview_dynamic_button, "Dynamic"),
                              (self.parent.preview_open_button, "Map")):
            for index, suffix in enumerate(("baseline", "adjusted")):
                name = f"{label} {suffix}"
                child = self.new_window(button, name)
                if hasattr(child, "copy_from_wkb_action") and child.copy_from_wkb_action.isChecked():
                    child.copy_from_wkb_action.trigger()
                source = self.parent.raw_model.document_frame().copy()
                source["CD"] = [f"{index + 7}.123456789010000", "2.000", "3.000"]
                child.set_table(source, "Independent measurements")
                child.tabs.setCurrentIndex(index)
                page = (child.correlation_page if label == "Correlation" else
                        child.dynamic_trend if label == "Dynamic" else child.plot_page)
                page.font_size.setCurrentText(str(8 + index * 4))
                expected[name] = child.model.document_frame().copy(), index, page.font_size.currentText()
            self.window_choices(button)[f"{label} baseline"].trigger()
        raw_before = self.parent.raw_model.document_frame().copy()
        with TemporaryDirectory() as folder:
            path = Path(folder) / "named-analysis.wkb"
            self.parent.save_workbook(path)
            self.parent.document.force_close = True
            self.parent.close()
            APP.processEvents()
            self.parent = MatchingWindow()
            self.parent.load_workbook(path)
            self.parent.show()
            for button, label in ((self.parent.correlation_button, "Correlation"),
                                  (self.parent.preview_dynamic_button, "Dynamic"),
                                  (self.parent.preview_open_button, "Map")):
                choices = self.window_choices(button)
                self.assertFalse(choices[f"{label} baseline"].isChecked())
                self.assertTrue(choices[f"{label} adjusted"].isChecked())
                button.click()
                adjusted = next(window for window in APP.topLevelWidgets()
                                if f"{label} adjusted" in window.windowTitle() and window.isVisible())
                pd.testing.assert_frame_equal(adjusted.model.document_frame(), expected[f"{label} adjusted"][0])
                self.assertEqual(adjusted.tabs.currentIndex(), 1)
                page = (adjusted.correlation_page if label == "Correlation" else
                        adjusted.dynamic_trend if label == "Dynamic" else adjusted.plot_page)
                self.assertEqual(page.font_size.currentText(), expected[f"{label} adjusted"][2])
                choices[f"{label} baseline"].trigger()
                button.click()
                baseline = next(window for window in APP.topLevelWidgets()
                                if f"{label} baseline" in window.windowTitle() and window.isVisible())
                pd.testing.assert_frame_equal(baseline.model.document_frame(), expected[f"{label} baseline"][0])
                self.assertEqual(baseline.tabs.currentIndex(), 0)
                page = (baseline.correlation_page if label == "Correlation" else
                        baseline.dynamic_trend if label == "Dynamic" else baseline.plot_page)
                self.assertEqual(page.font_size.currentText(), expected[f"{label} baseline"][2])
                pd.testing.assert_frame_equal(adjusted.model.document_frame(), expected[f"{label} adjusted"][0])
            pd.testing.assert_frame_equal(self.parent.raw_model.document_frame(), raw_before)

    def test_recovery_and_save_without_opening_children_keep_each_named_draft(self):
        first = self.new_window(self.parent.preview_open_button, "Map baseline")
        second = self.new_window(self.parent.preview_open_button, "Map adjusted")
        for child in (first, second):
            child.set_table(self.parent.raw_model.document_frame(), "Manual measurements")
        with TemporaryDirectory() as folder:
            accepted = Path(folder) / "accepted.wkb"
            self.parent.save_workbook(accepted)
            original = accepted.read_bytes()
            first.model.edit({(1, 5): "7.123456789010000"})
            second.model.edit({(1, 5): "8.123456789010000"})
            expected = {"Map baseline": first.model.document_frame().copy(),
                        "Map adjusted": second.model.document_frame().copy()}
            recovery = Path(folder) / "recovered.wkb"
            self.parent.document.recovery_path = recovery
            self.parent.document.write_recovery()
            restored = MatchingWindow()
            restored.document.recover(recovery)
            saved = Path(folder) / "recovery-saved.wkb"
            restored.save_workbook(saved)
            restored.document.force_close = True
            restored.close()
            restored.deleteLater()
            reopened = MatchingWindow()
            self.addCleanup(lambda: (setattr(reopened.document, "force_close", True), reopened.close()))
            reopened.load_workbook(saved)
            reopened.preview_open_button.click()
            for name, frame in expected.items():
                child = next(window for window in APP.topLevelWidgets()
                             if name in window.windowTitle() and window.isVisible())
                pd.testing.assert_frame_equal(child.model.document_frame(), frame)
            self.assertEqual(accepted.read_bytes(), original)

    def test_manual_named_correlation_does_not_regain_workbook_groups_after_reopen(self):
        self.parent.match_type.setCurrentText("TEM")
        child = self.new_window(self.parent.correlation_button, "Independent correlation")
        self.assertFalse(child.copy_from_wkb_action.isChecked())
        child.set_table(self.parent.raw_model.document_frame(), "Manual Raw")
        expected = child.workspace_snapshot()
        self.assertNotIn("match_groups", expected.states)
        with TemporaryDirectory() as folder:
            path = Path(folder) / "independent-correlation.wkb"
            self.parent.save_workbook(path)
            restored = MatchingWindow()
            self.addCleanup(lambda: (setattr(restored.document, "force_close", True), restored.close()))
            restored.load_workbook(path)
            restored.correlation_button.click()
            reopened = next(window for window in restored._stage_windows
                            if "Independent correlation" in window.windowTitle())
            self.assertTrue(same_snapshot(expected, reopened.workspace_snapshot()))

    def test_child_save_accepts_only_that_named_draft_and_discard_reopens_its_saved_values(self):
        first = self.new_window(self.parent.preview_open_button, "Map baseline")
        second = self.new_window(self.parent.preview_open_button, "Map adjusted")
        for child in (first, second):
            child.set_table(self.parent.raw_model.document_frame(), "Manual measurements")
        with TemporaryDirectory() as folder:
            path = Path(folder) / "selective-save.wkb"
            self.parent.save_workbook(path)
            baseline = first.model.document_frame().copy()
            first.model.edit({(1, 5): "7.123456789010000"})
            second.model.edit({(1, 5): "8.123456789010000"})
            saved_first = first.model.document_frame().copy()
            first.save_wkb()
            self.assertFalse(first.document.is_dirty())
            self.assertTrue(second.document.is_dirty())
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
                self.assertFalse(second.close())
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                self.assertTrue(second.close())
            self.parent.preview_open_button.click()
            reopened = next(window for window in APP.topLevelWidgets()
                            if "Map adjusted" in window.windowTitle() and window.isVisible())
            pd.testing.assert_frame_equal(reopened.model.document_frame(), baseline)
            pd.testing.assert_frame_equal(first.model.document_frame(), saved_first)

    def test_rename_preserves_the_open_draft_and_identity_and_final_has_separate_choices(self):
        child = self.new_window(self.parent.preview_open_button, "Map baseline")
        child.set_table(self.parent.raw_model.document_frame(), "Manual measurements")
        child.model.edit({(1, 5): "7.123456789010000"})
        source = child.model.document_frame().copy()
        identities = set(self.parent.workspace_snapshot().states)
        failures = []

        def rename():
            dialog = APP.activeModalWidget()
            try:
                self.assertIsInstance(dialog, QInputDialog)
                self.assertEqual(dialog.labelText(), "Window name:")
                self.assertEqual(dialog.textValue(), "Map baseline")
                dialog.setTextValue("Map tuned")
                dialog.accept()
            except Exception as error:
                failures.append(error)
                if dialog is not None:
                    dialog.reject()

        menu = self.parent.preview_open_button.menu()
        menu.popup(self.parent.preview_open_button.mapToGlobal(QPoint(0, self.parent.preview_open_button.height())))
        APP.processEvents()
        action = next(action for action in menu.actions() if action.text() == "Map baseline")
        position = menu.actionGeometry(action).center()
        # A real double click includes a complete first click. A lone synthetic
        # double-click event would miss the menu closing/toggling on that click.
        QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=position, delay=0)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(rename)
        timer.start(10)
        QTest.mouseDClick(menu, Qt.MouseButton.LeftButton, pos=position, delay=0)
        QTest.mouseRelease(menu, Qt.MouseButton.LeftButton, pos=position, delay=0)
        timer.stop()
        self.assertEqual(failures, [])
        self.assertIn("Map tuned", child.windowTitle())
        self.assertNotIn("Rename window…", [action.text() for action in menu.actions()])
        self.assertTrue(self.window_choices(self.parent.preview_open_button)["Map tuned"].isChecked())
        self.assertEqual(set(self.parent.workspace_snapshot().states), identities)
        pd.testing.assert_frame_equal(child.model.document_frame(), source)
        self.parent.result_mode.setCurrentText("Final")
        final = self.new_window(self.parent.final_open_button, "Map tuned")
        self.assertIsNot(final, child)
        self.assertIn("Final", final.windowTitle())
        self.assertEqual(set(self.window_choices(self.parent.final_open_button)), {"Wafer Map / Radius 1", "Map tuned"})
        with TemporaryDirectory() as folder:
            path = Path(folder) / "renamed-analysis.wkb"
            self.parent.save_workbook(path)
            restored = MatchingWindow()
            self.addCleanup(lambda: (setattr(restored.document, "force_close", True), restored.close()))
            restored.load_workbook(path)
            self.assertEqual(set(self.window_choices(restored.preview_open_button)), {"Wafer Map / Radius 1", "Map tuned"})
            restored.preview_open_button.click()
            reopened = next(window for window in APP.topLevelWidgets()
                            if "Map tuned" in window.windowTitle() and "Preview" in window.windowTitle()
                            and window is not child)
            pd.testing.assert_frame_equal(reopened.model.document_frame(), source)

    def test_double_click_cancel_preserves_check_state_and_f2_keeps_name_validation_for_each_tool(self):
        for button, label in ((self.parent.correlation_button, "Correlation"),
                              (self.parent.preview_dynamic_button, "Dynamic"),
                              (self.parent.preview_open_button, "Map")):
            with self.subTest(tool=label):
                name = f"{label} baseline"
                child = self.new_window(button, name)
                self.new_window(button, f"{label} taken")
                before = child.workspace_snapshot()
                failures = []

                def edit_name(replacement=None):
                    dialog = APP.activeModalWidget()
                    try:
                        self.assertIsInstance(dialog, QInputDialog)
                        self.assertEqual(dialog.labelText(), "Window name:")
                        self.assertEqual(dialog.textValue(), name)
                        if replacement is None:
                            dialog.reject()
                        else:
                            dialog.setTextValue(replacement)
                            dialog.accept()
                    except Exception as error:
                        failures.append(error)
                        if dialog is not None:
                            dialog.reject()

                def show_item():
                    menu = button.menu()
                    menu.popup(button.mapToGlobal(QPoint(0, button.height())))
                    APP.processEvents()
                    action = next(action for action in menu.actions() if action.text() == name)
                    self.assertNotIn("Rename window…", [item.text() for item in menu.actions()])
                    return menu, action, menu.actionGeometry(action).center()

                menu, action, position = show_item()
                rect = menu.actionGeometry(action)
                QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=QPoint(rect.right() - 16, rect.center().y()), delay=0)
                self.assertFalse(action.isChecked())
                self.assertTrue(menu.isVisible())
                menu.hide()
                for checked in (False, True):
                    menu, action, position = show_item()
                    if action.isChecked() != checked:
                        rect = menu.actionGeometry(action)
                        QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=QPoint(rect.right() - 16, rect.center().y()), delay=0)
                    QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=position, delay=0)
                    timer = QTimer()
                    timer.setSingleShot(True)
                    timer.timeout.connect(edit_name)
                    timer.start(10)
                    QTest.mouseDClick(menu, Qt.MouseButton.LeftButton, pos=position, delay=0)
                    QTest.mouseRelease(menu, Qt.MouseButton.LeftButton, pos=position, delay=0)
                    timer.stop()
                    self.assertEqual(failures, [])
                    self.assertEqual(self.window_choices(button)[name].isChecked(), checked)
                    self.assertTrue(same_snapshot(before, child.workspace_snapshot()))
                for replacement in ("", f"{label} taken", f"{label} tuned"):
                    menu, action, _position = show_item()
                    menu.setActiveAction(action)
                    timer = QTimer()
                    timer.setSingleShot(True)
                    timer.timeout.connect(lambda value=replacement: edit_name(value))
                    timer.start(10)
                    QTest.keyClick(menu, Qt.Key.Key_F2, delay=0)
                    timer.stop()
                    self.assertEqual(failures, [])
                    current = name if replacement != f"{label} tuned" else replacement
                    self.assertIn(current, child.windowTitle())
                    self.assertTrue(self.window_choices(button)[current].isChecked())
                    self.assertTrue(same_snapshot(before, child.workspace_snapshot()))


if __name__ == "__main__":
    unittest.main()
