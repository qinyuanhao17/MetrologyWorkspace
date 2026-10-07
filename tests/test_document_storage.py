"""Document behavior through the same window actions used by engineers."""
from pathlib import Path
import tempfile
from time import monotonic
import unittest
from unittest.mock import patch

import pandas as pd
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
from PyQt6.QtCore import QTimer
from PyQt6.QtTest import QTest

from metrology_app.window import MainWindow
from metrology_app.correlation_window import CorrelationWindow
from metrology_app.dynamic_window import DynamicWindow


APP = QApplication.instance() or QApplication([])


class DocumentStorageTests(unittest.TestCase):
    def test_cancelled_save_as_suspends_recovery_publication_and_then_resumes_the_draft(self):
        import os
        import threading
        from metrology_app.workspace_store import load_workspace
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        gui_thread = threading.get_ident()
        real_fsync, real_replace = os.fsync, os.replace
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow()

            def slow_disk(descriptor):
                if threading.get_ident() != gui_thread:
                    entered.set()
                    if not release.wait(5):
                        raise OSError("test disk wait expired")
                return real_fsync(descriptor)

            def record_commit(source, target):
                result = real_replace(source, target)
                if threading.get_ident() != gui_thread:
                    finished.set()
                return result

            def choose_and_cancel(*args, **kwargs):
                release.set()
                deadline = monotonic() + 5
                while not finished.is_set() and monotonic() < deadline:
                    QTest.qWait(10)
                self.assertTrue(finished.is_set())
                QTest.qWait(60)  # Allow the completed result through the nested dialog event loop.
                self.assertFalse(window.document.recovery_path.exists(), "A pending result published during the Save decision")
                return "", ""

            try:
                window.set_table(pd.DataFrame({"CD": ["2.1000"]}), "Measurements")
                window.document.save(Path(directory) / "accepted.wmap")
                window.document.recovery_path = Path(directory) / "draft.wmap"
                window.model.edit({(1, 0): "9.9900"})
                with patch.object(os, "fsync", side_effect=slow_disk), patch.object(os, "replace", side_effect=record_commit):
                    window.document.request_recovery()
                    deadline = monotonic() + 5
                    while not entered.is_set() and monotonic() < deadline:
                        QTest.qWait(10)
                    self.assertTrue(entered.is_set())
                    with patch.object(QFileDialog, "getSaveFileName", side_effect=choose_and_cancel):
                        self.assertIsNone(window.document.save(save_as=True))
                    deadline = monotonic() + 5
                    while window.document.recovery_pending and monotonic() < deadline:
                        QTest.qWait(10)
                    self.assertFalse(window.document.recovery_pending)
                self.assertEqual(load_workspace(window.document.recovery_path).frames["input_data"].iloc[0, 0], "9.9900")
                self.assertTrue(window.document.is_dirty())
            finally:
                release.set()
                window.document.force_close = True
                window.close()
                window.deleteLater()
                APP.processEvents()

    def test_background_recovery_failed_publication_keeps_the_last_valid_draft_and_retries(self):
        import os
        from metrology_app.workspace_store import file_revision, load_workspace

        def finish(document):
            deadline = monotonic() + 5
            while document.recovery_pending and monotonic() < deadline:
                QTest.qWait(10)
            self.assertFalse(document.recovery_pending)

        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow()
            try:
                window.set_table(pd.DataFrame({"CD": ["2.1000"]}), "Measurements")
                original = window.document.save(Path(directory) / "accepted.wmap")
                original_revision = file_revision(original)
                path = window.document.recovery_path = Path(directory) / "draft.wmap"
                window.model.edit({(1, 0): "9.9900"})
                window.document.request_recovery()
                finish(window.document)
                previous = file_revision(path)
                window.model.edit({(1, 0): "11.5000"})
                real_replace = os.replace

                def fail_publication(source, target):
                    if Path(target).resolve() == path:
                        raise PermissionError("recovery target in use")
                    return real_replace(source, target)

                with patch.object(os, "replace", side_effect=fail_publication):
                    window.document.request_recovery()
                    finish(window.document)
                self.assertIn("recovery target in use", window.document.last_warning)
                self.assertEqual(file_revision(path), previous)
                self.assertEqual(load_workspace(path).frames["input_data"].iloc[0, 0], "9.9900")
                window.document.request_recovery()
                finish(window.document)
                self.assertEqual(load_workspace(path).frames["input_data"].iloc[0, 0], "11.5000")
                path.unlink()
                window.document.request_recovery()
                finish(window.document)
                self.assertEqual(load_workspace(path).frames["input_data"].iloc[0, 0], "11.5000")
                self.assertEqual(file_revision(original), original_revision)
            finally:
                window.document.force_close = True
                window.close()
                window.deleteLater()
                APP.processEvents()

    def test_discard_and_close_cancel_a_disk_waiting_recovery_without_recreating_the_draft(self):
        import os
        import threading
        from metrology_app.workspace_store import load_workspace
        gui_thread = threading.get_ident()
        real_fsync, real_replace = os.fsync, os.replace
        for choice in ("discard", "save", "close"):
            with self.subTest(choice=choice), tempfile.TemporaryDirectory() as directory:
                entered, release, finished = threading.Event(), threading.Event(), threading.Event()
                root = Path(directory)
                window = MainWindow()

                def slow_disk(descriptor):
                    if threading.get_ident() != gui_thread:
                        entered.set()
                        if not release.wait(5):
                            raise OSError("test disk wait expired")
                    return real_fsync(descriptor)

                def record_private_commit(source, target):
                    result = real_replace(source, target)
                    if threading.get_ident() != gui_thread:
                        finished.set()
                    return result

                def wait_for(condition):
                    deadline = monotonic() + 5
                    while not condition() and monotonic() < deadline:
                        QTest.qWait(10)
                    self.assertTrue(condition())

                try:
                    window.set_table(pd.DataFrame({"CD": ["2.1000"]}), "Measurements")
                    original = window.document.save(root / "accepted.wmap")
                    window.document.recovery_path = root / "draft.wmap"
                    window.model.edit({(1, 0): "9.9900"})
                    with patch.object(os, "fsync", side_effect=slow_disk), patch.object(os, "replace", side_effect=record_private_commit):
                        window.document.request_recovery()
                        wait_for(entered.is_set)
                        if choice == "save":
                            window.document.save()
                        elif choice == "discard":
                            window.document.discard()
                        else:
                            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                                self.assertTrue(window.close())
                        release.set()
                        retained = {original, Path(str(original) + ".bak")} if choice == "save" else {original}
                        wait_for(lambda: finished.is_set() and set(root.iterdir()) == retained)
                        self.assertFalse(window.document.recovery_path.exists())
                    expected = "9.9900" if choice == "save" else "2.1000"
                    self.assertEqual(load_workspace(original).frames["input_data"].iloc[0, 0], expected)
                finally:
                    release.set()
                    window.document.force_close = True
                    window.close()
                    window.deleteLater()
                    APP.processEvents()

    def test_background_recovery_keeps_the_interface_responsive_and_the_latest_requested_edit(self):
        import os
        import threading
        from metrology_app.workspace_store import load_workspace
        entered, release = threading.Event(), threading.Event()
        gui_thread = threading.get_ident()
        real_fsync = os.fsync

        def slow_disk(descriptor):
            if threading.get_ident() != gui_thread:
                entered.set()
                if not release.wait(5):
                    raise OSError("test disk wait expired")
            return real_fsync(descriptor)

        def wait_for(condition):
            deadline = monotonic() + 5
            while not condition() and monotonic() < deadline:
                QTest.qWait(10)
            self.assertTrue(condition(), "Recovery did not reach the expected state")

        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow()
            try:
                window.set_table(pd.DataFrame({"CD": ["2.1000"]}), "Measurements")
                window.document.save(Path(directory) / "accepted.wmap")
                window.document.recovery_path = Path(directory) / "draft.wmap"
                window.model.edit({(1, 0): "9.9900"})
                with patch.object(os, "fsync", side_effect=slow_disk):
                    start = monotonic()
                    window.document.request_recovery()
                    self.assertLess(monotonic() - start, .1)
                    wait_for(entered.is_set)
                    window.model.edit({(1, 0): "11.5000"})
                    window.document.request_recovery()
                    release.set()
                    wait_for(lambda: not window.document.recovery_pending)
                self.assertEqual(load_workspace(window.document.recovery_path).frames["input_data"].iloc[0, 0], "11.5000")
                self.assertTrue(window.document.is_dirty(), "Recovery must not accept edits as a formal Save")
            finally:
                release.set()
                window.document.force_close = True
                window.close()
                window.deleteLater()
                APP.processEvents()

    def test_settings_save_updates_open_recovery_intervals_and_cancel_keeps_the_saved_interval(self):
        from metrology_app.settings import get_settings, save_settings
        from metrology_app.settings_dialog import SettingsDialog
        before = get_settings()
        save_settings({"recovery_interval_seconds": 120})
        window = MainWindow()
        dialog = SettingsDialog()
        try:
            self.assertEqual(window.document.timer.interval(), 120_000)
            dialog.recovery_interval.setValue(300)
            dialog.save()
            self.assertEqual(window.document.timer.interval(), 300_000)
            self.assertEqual(get_settings()["recovery_interval_seconds"], 300)
            dialog.deleteLater()
            dialog = SettingsDialog()
            dialog.recovery_interval.setValue(600)
            dialog.reject()
            self.assertEqual(window.document.timer.interval(), 300_000)
            self.assertEqual(get_settings()["recovery_interval_seconds"], 300)
        finally:
            dialog.deleteLater()
            save_settings(before)
            window.document.force_close = True
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_cached_recovery_recreates_missing_or_replaced_files_and_cleans_after_undo(self):
        from metrology_app.workspace_store import WorkspaceSnapshot, file_revision, load_workspace, save_workspace
        window = MainWindow()
        try:
            with tempfile.TemporaryDirectory() as directory:
                window.set_table(pd.DataFrame({"CD": ["2.1000"]}), "Measurements")
                original = window.document.save(Path(directory) / "accepted.wmap")
                accepted_revision = file_revision(original)
                path = Path(directory) / "draft.wmap"
                window.document.recovery_path = path
                window.model.edit({(1, 0): "9.9900"})
                window.document.write_recovery()
                path.unlink()
                window.document.write_recovery()
                self.assertEqual(load_workspace(path).frames["input_data"].iloc[0, 0], "9.9900")
                save_workspace(path, WorkspaceSnapshot("wafer_map", {"input_data": pd.DataFrame({"CD": ["0"]})},
                                                      {"ui": {}}), backup=False)
                window.document.write_recovery()
                self.assertEqual(load_workspace(path).frames["input_data"].iloc[0, 0], "9.9900")
                window.model.undo.undo()
                window.document.write_recovery()
                self.assertFalse(path.exists(), "Returning to accepted data must remove the obsolete recovery")
                window.model.edit({(1, 0): "9.9900"})
                window.document.write_recovery()
                self.assertEqual(load_workspace(path).frames["input_data"].iloc[0, 0], "9.9900")
                self.assertEqual(file_revision(original), accepted_revision)
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_failed_recovery_commit_keeps_the_previous_draft_and_retries_new_edits(self):
        import os
        from metrology_app.workspace_store import file_revision, load_workspace
        window = MainWindow()
        try:
            with tempfile.TemporaryDirectory() as directory:
                window.set_table(pd.DataFrame({"CD": ["2.1000"]}), "Measurements")
                original = window.document.save(Path(directory) / "accepted.wmap")
                accepted_revision = file_revision(original)
                window.document.recovery_path = Path(directory) / "draft.wmap"
                window.model.edit({(1, 0): "9.9900"})
                window.document.write_recovery()
                path = window.document.recovery_path
                previous_revision = file_revision(path)
                window.model.edit({(1, 0): "11.5000"})
                real_replace = os.replace
                def fail_recovery(source, target):
                    if Path(target).resolve() == path:
                        raise PermissionError("recovery target in use")
                    return real_replace(source, target)
                with patch.object(os, "replace", side_effect=fail_recovery):
                    window.document.write_recovery()
                self.assertIn("recovery target in use", window.document.last_warning)
                self.assertEqual(file_revision(path), previous_revision)
                self.assertEqual(load_workspace(path).frames["input_data"].iloc[0, 0], "9.9900")
                self.assertEqual(window.model.document_frame().iloc[0, 0], "11.5000")
                self.assertTrue(window.document.is_dirty())
                window.document.write_recovery()
                self.assertEqual(load_workspace(path).frames["input_data"].iloc[0, 0], "11.5000")
                self.assertEqual(file_revision(original), accepted_revision)
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_unchanged_recovery_is_not_rewritten_and_new_edits_remain_recoverable(self):
        from metrology_app.workspace_store import file_revision, load_workspace
        window, restored = MainWindow(), MainWindow()
        try:
            with tempfile.TemporaryDirectory() as directory:
                window.set_table(pd.DataFrame({"Wafer ID": ["001"], "CD": ["2.1000"]}), "Measurements")
                original = window.document.save(Path(directory) / "accepted.wmap")
                original_revision = file_revision(original)
                window.document.recovery_path = Path(directory) / "draft.wmap"
                window.model.edit({(1, 1): "9.9900"})
                window.document.write_recovery()
                path = window.document.recovery_path
                first_revision, first_stamp = file_revision(path), path.stat().st_mtime_ns
                window.document.write_recovery()
                window.document.write_recovery()
                self.assertEqual(file_revision(path), first_revision, "An unchanged draft was rewritten")
                self.assertEqual(path.stat().st_mtime_ns, first_stamp)
                from metrology_app.settings import get_settings
                self.assertEqual(window.document.timer.interval(), get_settings()["recovery_interval_seconds"] * 1000)
                window.model.edit({(1, 1): "11.5000"})
                window.document.write_recovery()
                self.assertNotEqual(file_revision(path), first_revision)
                self.assertEqual(load_workspace(path).frames["input_data"].iloc[0, 1], "11.5000")
                restored.document.recover(path)
                self.assertEqual(restored.model.document_frame().iloc[0, 1], "11.5000")
                self.assertTrue(restored.document.is_dirty())
                with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                    self.assertTrue(restored.close())
                    restored.load_workspace(original)
                self.assertEqual(restored.model.document_frame().iloc[0, 1], "2.1000")
                self.assertEqual(file_revision(original), original_revision)
        finally:
            for widget in (window, restored):
                widget.document.force_close = True
                widget.close()
                widget.deleteLater()
            APP.processEvents()

    def test_match_reopen_current_document_after_save_uses_the_new_saved_data(self):
        from metrology_app.matching_window import MatchingWindow
        window = MatchingWindow()
        try:
            with tempfile.TemporaryDirectory() as directory:
                window.set_reference_frame(pd.DataFrame({"CD Reference": ["4.2"]}), "Ref")
                window.set_raw_frame(pd.DataFrame({"CD": ["2.1000"]}), "Raw")
                path = window.save_workbook(Path(directory) / "current.wkb")
                window.raw_model.edit({(1, 0): "9.99"})
                with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save):
                    window.load_workbook(path)
                self.assertEqual(window.raw_model.document_frame().iloc[0, 0], "9.99")
                self.assertFalse(window.document.is_dirty())
                window.close()
        finally:
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_recent_reopen_current_document_after_save_loads_the_just_saved_measurements(self):
        from metrology_app.workspace_store import EXTENSIONS, WorkspaceSnapshot, file_revision
        for factory in (MainWindow, DynamicWindow, CorrelationWindow):
            with self.subTest(tool=factory.__name__), tempfile.TemporaryDirectory() as directory:
                window = factory()
                try:
                    data = pd.DataFrame({"Wafer ID": ["001"], "CD": ["2.1000"]})
                    frames = ({"raw_data": data, "reference_data": data.copy()}
                              if window.workspace_type == "correlation_trend" else {"input_data": data})
                    window.restore_workspace(WorkspaceSnapshot(window.workspace_type, frames, {"ui": {}}))
                    original = window.document.save(Path(directory) / ("current" + EXTENSIONS[window.workspace_type]))
                    window.model.edit({(1, 1): "9.99"})
                    window.recent_workspace_menu.aboutToShow.emit()
                    action = next(action for action in window.recent_workspace_menu.actions()
                                  if action.toolTip() == str(original))
                    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save):
                        action.trigger()
                    self.assertEqual(window.model.document_frame().iloc[0, 1], "9.99")
                    self.assertEqual(window.document.revision, file_revision(original))
                    self.assertFalse(window.document.is_dirty())
                finally:
                    window.close()
                    window.deleteLater()
                    APP.processEvents()

    def test_cancelled_tool_open_keeps_current_document_and_unsaved_edits(self):
        from metrology_app.workspace_store import EXTENSIONS, WorkspaceSnapshot, save_workspace
        for factory in (MainWindow, DynamicWindow, CorrelationWindow):
            with self.subTest(tool=factory.__name__), tempfile.TemporaryDirectory() as directory:
                window = factory()
                try:
                    data = pd.DataFrame({"Wafer ID": ["001"], "CD": ["2.1000"]})
                    frames = ({"raw_data": data, "reference_data": data.copy()}
                              if window.workspace_type == "correlation_trend" else {"input_data": data})
                    snapshot = WorkspaceSnapshot(window.workspace_type, frames, {"ui": {}})
                    window.restore_workspace(snapshot)
                    original = window.document.save(Path(directory) / ("original" + EXTENSIONS[window.workspace_type]))
                    window.model.edit({(1, 1): "9.99"})
                    other = save_workspace(Path(directory) / ("other" + EXTENSIONS[window.workspace_type]), snapshot)
                    open_action = next(action for action in window.file_menu.actions() if action.text() == "Open…")
                    with patch.object(QFileDialog, "getOpenFileName", return_value=(str(other), "")), \
                            patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as question:
                        open_action.trigger()
                        question.assert_called_once()
                    self.assertEqual(window.workspace_path, original)
                    self.assertEqual(window.model.document_frame().iloc[0, 1], "9.99")
                    self.assertTrue(window.document.is_dirty())
                    with patch.object(QFileDialog, "getOpenFileName", return_value=("", "")), \
                            patch.object(QMessageBox, "question") as question:
                        open_action.trigger()
                        question.assert_not_called()
                    self.assertEqual(window.model.document_frame().iloc[0, 1], "9.99")
                finally:
                    window.close()
                    window.deleteLater()
                    APP.processEvents()

    def test_recent_file_removed_after_menu_opens_reports_error_without_replacing_data(self):
        from metrology_app.settings import load_settings, save_settings
        from metrology_app.workspace_store import save_workspace
        before = load_settings()
        window = MainWindow()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = save_workspace(Path(directory) / "removed.wmap", window.workspace_snapshot())
                save_settings({"recent_wkbs": [str(path)]})
                window.recent_workspace_menu.aboutToShow.emit()
                action = window.recent_workspace_menu.actions()[0]
                self.assertTrue(action.isEnabled())
                path.unlink()
                with patch.object(QMessageBox, "warning") as warning:
                    action.trigger()
                    warning.assert_called_once()
                self.assertIsNone(window.workspace_path)
                self.assertFalse(window.document.is_dirty())
                window.recent_workspace_menu.aboutToShow.emit()
                self.assertFalse(window.recent_workspace_menu.actions()[0].isEnabled())
        finally:
            window.close()
            window.deleteLater()
            APP.processEvents()
            save_settings(before)

    def test_independent_tool_recent_menu_filters_by_type_and_reopens_the_selected_document(self):
        from metrology_app.settings import load_settings, save_settings
        from metrology_app.workspace_store import WorkspaceSnapshot, save_workspace
        before = load_settings()
        try:
            with tempfile.TemporaryDirectory() as directory:
                folder = Path(directory).resolve()
                data = pd.DataFrame({"Wafer ID": ["001"], "CD": ["2.1000"]})
                wafer = save_workspace(folder / "wafer.wmap", WorkspaceSnapshot("wafer_map", {"input_data": data}, {"ui": {}}))
                dynamic = save_workspace(folder / "dynamic.wdyn", WorkspaceSnapshot("dynamic", {"input_data": data}, {"ui": {}}))
                correlation = save_workspace(folder / "correlation.wct", WorkspaceSnapshot("correlation_trend",
                    {"reference_data": data.copy(), "raw_data": data}, {"ui": {}}))
                match = save_workspace(folder / "match.wkb", WorkspaceSnapshot("match_workbook",
                    {"reference": data.copy(), "raw": data}, {"match": {"draft": True}}))
                legacy = save_workspace(folder / "legacy.wmap", WorkspaceSnapshot("wafer_map", {"input_data": data}, {"ui": {}}))
                legacy = legacy.rename(folder / "legacy.wkb")
                recovery = save_workspace(folder / "recovery.wmap", WorkspaceSnapshot("wafer_map", {"input_data": data},
                    {"ui": {}, "recovery": {"original_path": "", "revision": None}}))
                corrupt = folder / "invalid.wmap"
                corrupt.write_text("not a workspace", encoding="utf-8")
                save_settings({"recent_wkbs": [str(path) for path in (
                    folder / "missing.wmap", corrupt, recovery, legacy, correlation, match, dynamic, wafer)]})
                for factory, expected in ((MainWindow, [legacy, wafer]), (DynamicWindow, [dynamic]),
                                          (CorrelationWindow, [correlation])):
                    with self.subTest(tool=factory.__name__):
                        window = factory()
                        try:
                            menus = [action.menu() for action in window.file_menu.actions() if action.text() == "Open Recent"]
                            self.assertEqual(len(menus), 1)
                            menus[0].aboutToShow.emit()
                            entries = [action for action in menus[0].actions() if action.isEnabled()]
                            self.assertEqual([Path(action.toolTip()) for action in entries], expected)
                            entries[0].trigger()
                            self.assertEqual(window.workspace_path, expected[0])
                            self.assertEqual(window.model.document_frame().iloc[0, 1], "2.1000")
                        finally:
                            window.close()
                            window.deleteLater()
                            APP.processEvents()
        finally:
            save_settings(before)

    def test_independent_tool_file_open_restores_document_for_all_three_tools(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from metrology_app.workspace_store import EXTENSIONS, WorkspaceSnapshot, save_workspace
        for factory in (MainWindow, DynamicWindow, CorrelationWindow):
            with self.subTest(tool=factory.__name__), tempfile.TemporaryDirectory() as directory:
                window = factory()
                try:
                    data = pd.DataFrame({"Wafer ID": ["001"], "CD": ["2.1000"]})
                    frames = ({"raw_data": data, "reference_data": data.copy()}
                              if window.workspace_type == "correlation_trend" else {"input_data": data})
                    path = save_workspace(Path(directory) / ("analysis" + EXTENSIONS[window.workspace_type]),
                                          WorkspaceSnapshot(window.workspace_type, frames, {"ui": {}}))
                    actions = [action for action in window.file_menu.actions() if action.text() == "Open…"]
                    self.assertEqual(len(actions), 1)
                    self.assertEqual(actions[0].shortcut().toString(), "Ctrl+O")
                    window.show()
                    window.activateWindow()
                    APP.processEvents()
                    with patch.object(QFileDialog, "getOpenFileName", return_value=(str(path), "")) as dialog:
                        QTest.keyClick(window, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
                        APP.processEvents()
                        dialog.assert_called_once()
                        self.assertIn(EXTENSIONS[window.workspace_type], dialog.call_args.args[3])
                    self.assertEqual(window.workspace_path, path.resolve())
                    self.assertEqual(window.model.document_frame().iloc[0, 1], "2.1000")
                    self.assertFalse(window.document.is_dirty())
                finally:
                    window.close()
                    window.deleteLater()
                    APP.processEvents()

    def test_opening_formal_file_after_old_recovery_replaces_the_recovery_restriction(self):
        from copy import deepcopy
        from metrology_app.matching_window import MatchingWindow
        from metrology_app.workspace_store import save_workspace
        for factory, suffix in ((MainWindow, ".wmap"), (MatchingWindow, ".wkb")):
            with self.subTest(kind=factory.__name__), tempfile.TemporaryDirectory() as directory:
                window = factory()
                try:
                    formal = save_workspace(Path(directory) / ("formal" + suffix), window.workspace_snapshot())
                    recovery = deepcopy(window.workspace_snapshot())
                    recovery.states["recovery"] = {"original_path": "", "revision": None}
                    draft = save_workspace(Path(directory) / ("recovery" + suffix), recovery)
                    window.document.recover(draft)
                    self.assertTrue(window.document.untrusted_recovery)
                    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                        if suffix == ".wkb":
                            window.load_workbook(formal)
                        else:
                            window.load_workspace(formal)
                    self.assertFalse(window.document.untrusted_recovery)
                    with patch.object(QFileDialog, "getSaveFileName") as dialog:
                        self.assertTrue(window.save_wkb())
                        dialog.assert_not_called()
                finally:
                    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                        window.close()
                    window.deleteLater()
                    APP.processEvents()

    def test_first_show_does_not_mark_empty_match_dirty_or_accept_measurement_edits(self):
        from metrology_app.matching_window import MatchingWindow
        empty, edited = MatchingWindow(), MatchingWindow()
        try:
            edited.set_reference_frame(pd.DataFrame({"CD": [1., 2.]}), "Ref")
            empty.show()
            edited.show()
            APP.processEvents()
            self.assertFalse(empty.document.is_dirty())
            self.assertTrue(edited.document.is_dirty())
            with patch.object(QMessageBox, "question") as question:
                self.assertTrue(empty.close())
                question.assert_not_called()
        finally:
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                empty.close()
                edited.close()
            empty.deleteLater()
            edited.deleteLater()
            APP.processEvents()

    def test_recovery_cleanup_error_does_not_block_a_clean_window_close(self):
        window = MainWindow()
        try:
            with patch.object(Path, "unlink", side_effect=PermissionError("draft is in use")), \
                    patch.object(QMessageBox, "question") as question:
                self.assertTrue(window.close())
                question.assert_not_called()
        finally:
            window.deleteLater()
            APP.processEvents()

    def test_match_recovery_saves_to_original_not_the_previously_open_file(self):
        from metrology_app.matching_window import MatchingWindow
        first, restored = MatchingWindow(), MatchingWindow()
        with tempfile.TemporaryDirectory() as directory:
            try:
                first.set_reference_frame(pd.DataFrame({"CD Reference": [2., 4., 6.]}), "Ref")
                first.set_raw_frame(pd.DataFrame({"CD": [1., 2., 3.]}), "Raw")
                first.run_analysis()
                original = first.save_workbook(Path(directory) / "original.wkb")
                first.raw_model.edit({(1, 0): "9.999"})
                first.document.recovery_path = Path(directory) / "recovery.wkb"
                first.document.write_recovery()
                other = restored.save_workbook(Path(directory) / "other.wkb")
                other_bytes = other.read_bytes()
                # Even Open (rather than Recover draft) must identify a recovery.
                restored.load_workbook(first.document.recovery_path)
                self.assertTrue(restored.document.is_dirty())
                self.assertEqual(restored.workbook_path, original.resolve())
                self.assertEqual(restored.save_wkb(), original.resolve())
                self.assertEqual(other.read_bytes(), other_bytes)
            finally:
                first.close()
                restored.close()
                first.deleteLater()
                restored.deleteLater()
                APP.processEvents()

    def test_unconfirmed_radius_box_changes_reopen_waiting_for_draw(self):
        first, restored = MainWindow(), MainWindow()
        with tempfile.TemporaryDirectory() as directory:
            try:
                first.set_table(pd.DataFrame({"Wafer ID": ["W1"] * 4,
                                               "FIELD X": [-1, 1, -1, 1], "FIELD Y": [-1, -1, 1, 1],
                                               "CD": [1, 2, 3, 4], "SWA": [80, 81, 82, 83]}), "Data")
                from PyQt6.QtCore import Qt
                for i in range(first.parameter_list.topLevelItemCount()):
                    item = first.parameter_list.topLevelItem(i)
                    if item.text(0) in ("CD", "SWA"):
                        item.setCheckState(0, Qt.CheckState.Checked)
                page = first.radius_page
                wafer = page.selector.wafers[0]
                page.selector.set_selected_cells({(wafer, "CD")})
                page.draw_plot()
                self.assertTrue(page.ready)
                page.selector.set_selected_cells({(wafer, "SWA")})
                self.assertTrue(page.selector.pending_draw)
                path = first.document.save(Path(directory) / "radius.wkb")
                restored.load_workspace(path)
                self.assertEqual(restored.radius_page.selector.selected_cells(), {(wafer, "SWA")})
                self.assertTrue(restored.radius_page.selector.pending_draw)
                self.assertFalse(restored.radius_page.ready)
                restored.radius_page.draw_plot()
                self.assertTrue(restored.radius_page.ready)
                self.assertEqual(restored.radius_page.drawn_cells, {(wafer, "SWA")})
            finally:
                first.close()
                restored.close()
                first.deleteLater()
                restored.deleteLater()
                APP.processEvents()

    def test_shell_opens_each_wkb_in_its_own_tool(self):
        from metrology_app.shell import MainWindow as ShellWindow
        from metrology_app.matching_window import MatchingWindow
        from metrology_app.workspace_store import save_workspace
        shell = ShellWindow()
        with tempfile.TemporaryDirectory() as directory:
            try:
                for factory in (MainWindow, DynamicWindow, CorrelationWindow, MatchingWindow):
                    with self.subTest(tool=factory.__name__):
                        window = factory()
                        snapshot = window.workspace_snapshot()
                        window.close()
                        window.deleteLater()
                        path = save_workspace(Path(directory) / (snapshot.workspace_type + ".wkb"), snapshot)
                        if factory is MatchingWindow:
                            QTimer.singleShot(0, lambda: APP.activeModalWidget().confirm_button.click())
                        opened = shell.load_path(path)
                        self.assertIsInstance(opened, factory)
                        self.assertFalse(opened.document.is_dirty())
            finally:
                shell.close()
                shell.deleteLater()
                APP.processEvents()

    def test_saving_one_child_does_not_accept_another_child_draft(self):
        from metrology_app.matching_window import MatchingWindow
        from metrology_app.workspace_store import load_workspace
        window = MatchingWindow()
        with tempfile.TemporaryDirectory() as directory:
            try:
                window.set_reference_frame(pd.DataFrame({"CD Reference": [2., 4., 6.]}), "Ref")
                window.set_raw_frame(pd.DataFrame({"Wafer ID": ["W1"] * 3,
                                                  "Die Seq": [1, 2, 3], "CD": [1., 2., 3.]}), "Raw")
                window.run_analysis()
                window.preview_dynamic_frame = window.raw_frame.copy()
                dynamic = window.open_dynamic_workspace("preview")
                correlation = window.open_correlation_workspace()
                path = window.save_workbook(Path(directory) / "match.wkb")
                column = dynamic.model.document_frame().columns.get_loc("CD")
                dynamic.model.edit({(1, column): "99"})
                correlation.correlation_page.min_rsq.setValue(.88)
                self.assertTrue(correlation.save_wkb())
                saved = load_workspace(path)
                self.assertNotEqual(saved.frames["preview_dynamic"].iloc[0, column], "99")
                self.assertEqual(saved.states["correlation.preview"]["ui"]["pages"]["correlation_page"]["controls"]["min_rsq"], .88)
                self.assertTrue(dynamic.document.is_dirty())
                self.assertFalse(correlation.document.is_dirty())
            finally:
                window.close()
                window.deleteLater()
                APP.processEvents()

    def test_match_saves_mismatched_row_draft_after_an_earlier_analysis(self):
        from metrology_app.matching_window import MatchingWindow
        first, restored = MatchingWindow(), MatchingWindow()
        with tempfile.TemporaryDirectory() as directory:
            try:
                first.set_reference_frame(pd.DataFrame({"CD Reference": [2., 4., 6.]}), "Ref")
                first.set_raw_frame(pd.DataFrame({"CD": [1., 2., 3.]}), "Raw")
                first.run_analysis()
                first.raw_model.load(pd.DataFrame({"CD": ["1.00", "2.00"]}))
                path = first.save_workbook(Path(directory) / "draft.wkb")
                restored.load_workbook(path)
                self.assertEqual(restored.raw_model.document_frame()["CD"].tolist(), ["1.00", "2.00"])
                self.assertIsNone(restored.result)
                self.assertFalse(restored.document.is_dirty())
            finally:
                first.close()
                restored.close()
                first.deleteLater()
                restored.deleteLater()
                APP.processEvents()

    def test_match_child_duplicate_header_draft_does_not_block_parent_reopen(self):
        from metrology_app.matching_window import MatchingWindow
        first, restored = MatchingWindow(), MatchingWindow()
        with tempfile.TemporaryDirectory() as directory:
            try:
                first.set_reference_frame(pd.DataFrame({"CD Reference": [2., 4., 6.]}), "Ref")
                first.set_raw_frame(pd.DataFrame({"CD": [1., 2., 3.]}), "Raw")
                first.run_analysis()
                child = first.open_stage_workspace("preview")
                frame = pd.DataFrame([["2.1000", "NA"]], columns=["CD", "CD"])
                child.model.load(frame)
                path = first.save_workbook(Path(directory) / "match.wkb")
                restored.load_workbook(path)
                self.assertIsNotNone(restored.result)
                reopened = restored.open_stage_workspace("preview")
                pd.testing.assert_frame_equal(reopened.model.document_frame(), frame)
            finally:
                first.close()
                restored.close()
                first.deleteLater()
                restored.deleteLater()
                APP.processEvents()

    def test_invalid_analysis_drafts_reopen_without_rewriting_measurements(self):
        for factory in (DynamicWindow, CorrelationWindow):
            with self.subTest(tool=factory.__name__), tempfile.TemporaryDirectory() as directory:
                first, restored = factory(), factory()
                try:
                    frame = pd.DataFrame([["2.1000", "NA"]], columns=["CD", "CD"])
                    first.model.load(frame)
                    if isinstance(first, CorrelationWindow):
                        first.reference_model.load(pd.DataFrame({"CD": ["1.0"]}))
                    path = first.document.save(Path(directory) / "draft.wkb")
                    restored.load_workspace(path)
                    pd.testing.assert_frame_equal(restored.model.document_frame(), frame)
                finally:
                    first.close()
                    restored.close()
                    first.deleteLater()
                    restored.deleteLater()
                    APP.processEvents()

    def test_dynamic_die_picker_and_plot_settings_reopen_on_the_saved_die(self):
        first, restored = DynamicWindow(), DynamicWindow()
        with tempfile.TemporaryDirectory() as directory:
            try:
                first.set_table(pd.DataFrame({"Wafer ID": ["W1"] * 6, "Die Seq": [1, 2] * 3,
                                               "CD": [1, 10, 2, 20, 3, 30]}), "Dynamic")
                from PyQt6.QtCore import Qt
                item = next(first.parameter_list.topLevelItem(i) for i in range(first.parameter_list.topLevelItemCount())
                            if first.parameter_list.topLevelItem(i).text(0) == "CD")
                item.setCheckState(0, Qt.CheckState.Checked)
                first.dynamic_trend.die_pickers["CD"].setCurrentIndex(1)
                first.dynamic_trend.font_size.setCurrentText("12")
                path = first.document.save(Path(directory) / "dynamic.wkb")
                restored.load_workspace(path)
                self.assertEqual(str(restored.dynamic_trend.die_pickers["CD"].currentData()), "2")
                self.assertEqual(restored.dynamic_trend.font_size.currentText(), "12")
                self.assertEqual(restored.dynamic_trend.panel_widgets["CD"].listDataItems()[0].yData.tolist(), [10, 20, 30])
            finally:
                first.close()
                restored.close()
                first.deleteLater()
                restored.deleteLater()
                APP.processEvents()

    def test_cancelled_save_as_keeps_unsaved_match_child_open(self):
        from metrology_app.matching_window import MatchingWindow
        window = MatchingWindow()
        try:
            window.set_reference_frame(pd.DataFrame({"CD Reference": [2., 4., 6.]}), "Ref")
            window.set_raw_frame(pd.DataFrame({"Wafer ID": ["W1"] * 3, "Die Seq": [1, 2, 3],
                                               "CD": [1., 2., 3.]}), "Raw")
            window.run_analysis()
            window.preview_dynamic_frame = window.raw_frame.copy()
            child = window.open_dynamic_workspace("preview")
            column = child.model.frame().columns.get_loc("CD")
            original = window.preview_dynamic_frame.copy()
            child.model.edit({(1, column): "99"})
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save), \
                    patch.object(QFileDialog, "getSaveFileName", return_value=("", "")):
                self.assertFalse(child.close())
            self.assertTrue(child.document.is_dirty())
            pd.testing.assert_frame_equal(window.preview_dynamic_frame, original)
            self.assertEqual(child.model.frame().iloc[0, column], "99")
        finally:
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_match_draft_with_duplicate_headers_can_save_without_analysis(self):
        from metrology_app.matching_window import MatchingWindow
        first, second = MatchingWindow(), MatchingWindow()
        with tempfile.TemporaryDirectory() as directory:
            try:
                frame = pd.DataFrame([["001", "2.1000", "NA"]], columns=["Wafer ID", "CD", "CD"])
                first.reference_model.load(frame)
                first.raw_model.load(frame)
                first.final_raw_model.load(pd.DataFrame(columns=["Wafer ID", "CD"]))
                path = first.save_workbook(Path(directory) / "draft.wkb")
                second.load_workbook(path)
                pd.testing.assert_frame_equal(second.raw_model.document_frame(), frame)
                self.assertEqual(second.final_raw_model.document_frame().columns.tolist(), ["Wafer ID", "CD"])
                self.assertIsNone(second.result)
                self.assertFalse(second.document.is_dirty())
            finally:
                first.close()
                second.close()
                first.deleteLater()
                second.deleteLater()
                APP.processEvents()

    def test_recovery_preserves_draft_without_overwriting_accepted_wkb(self):
        first, restored = MainWindow(), MainWindow()
        with tempfile.TemporaryDirectory() as directory:
            try:
                first.set_table(pd.DataFrame({"CD": ["2.1000"]}), "CSV")
                path = Path(directory) / "accepted.wkb"
                path = first.document.save(path)
                original = path.read_bytes()
                first.model.edit({(1, 0): "9.99"})
                first.document.recovery_path = Path(directory) / "recovery.wkb"
                first.document.write_recovery()
                restored.document.recover(first.document.recovery_path)
                self.assertEqual(restored.model.document_frame().iloc[0, 0], "9.99")
                self.assertTrue(restored.document.is_dirty())
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(restored.workspace_path, path.resolve())
            finally:
                with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                    first.close()
                    restored.close()
                first.deleteLater()
                restored.deleteLater()
                APP.processEvents()

    def test_match_correlation_child_saves_its_own_ref_raw_data_and_overlay(self):
        from metrology_app.matching_window import MatchingWindow
        first, restored = MatchingWindow(), MatchingWindow()
        with tempfile.TemporaryDirectory() as directory:
            try:
                first.set_reference_frame(pd.DataFrame({"CD Reference": [2., 4., 6.]}), "Ref")
                first.set_raw_frame(pd.DataFrame({"Wafer ID": ["W1"] * 3,
                                                  "Die Seq": [1, 2, 3], "CD": [1., 2., 3.]}), "Raw")
                first.run_analysis()
                child = first.open_correlation_workspace()
                column = child.model.document_frame().columns.get_loc("CD")
                child.model.edit({(1, column): "9.999"})
                child.correlation_page.min_rsq.setValue(.77)
                child.recognize()
                child.sequence_page.set_overlay("CD", "CD", "Reference", "Raw Data")
                child.sequence_page.draw_plot()
                self.assertTrue(child.sequence_page.ready)
                path = first.save_workbook(Path(directory) / "match.wkb")
                restored.load_workbook(path)
                reopened = restored.open_correlation_workspace()
                self.assertEqual(reopened.model.document_frame().iloc[0, column], "9.999")
                self.assertEqual(reopened.correlation_page.min_rsq.value(), .77)
                self.assertEqual(reopened.sequence_page.source_overlay, child.sequence_page.source_overlay)
                self.assertTrue(reopened.sequence_page.ready)
            finally:
                with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                    first.close()
                    restored.close()
                first.deleteLater()
                restored.deleteLater()
                APP.processEvents()

    def test_match_child_discard_leaves_accepted_data_unchanged(self):
        from metrology_app.matching_window import MatchingWindow
        window = MatchingWindow()
        with tempfile.TemporaryDirectory() as directory:
            try:
                window.set_reference_frame(pd.DataFrame({"CD Reference": [2., 4., 6.]}), "Reference")
                window.set_raw_frame(pd.DataFrame({"Wafer ID": ["W1"] * 3,
                                                    "Die Seq": [1, 2, 3], "CD": [1., 2., 3.]}), "Raw")
                window.run_analysis()
                window.preview_dynamic_frame = window.raw_frame.copy()
                child = window.open_dynamic_workspace("preview")
                window.save_workbook(Path(directory) / "match.wkb")
                original = child.model.frame().copy()
                column = original.columns.get_loc("CD")
                child.model.edit({(1, column): "9.999"})
                with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
                    self.assertFalse(child.close())
                self.assertEqual(child.model.frame().iloc[0, column], "9.999")
                with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                    self.assertTrue(child.close())
                reopened = window.open_dynamic_workspace("preview")
                pd.testing.assert_frame_equal(reopened.model.frame(), original)
            finally:
                with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                    window.close()
                window.deleteLater()
                APP.processEvents()

    def test_independent_tools_save_data_and_plot_configuration_to_wkb(self):
        frame = pd.DataFrame({"Wafer ID": ["001"] * 4, "Die Seq": [1, 2, 3, 4],
                              "FIELD X": [-1, 1, -1, 1], "FIELD Y": [-1, -1, 1, 1],
                              "Cycle": [1, 1, 1, 1], "CD": ["2.1000", "3.2000", "4.3", "5.4"]})
        for factory in (MainWindow, DynamicWindow, CorrelationWindow):
            with self.subTest(tool=factory.__name__), tempfile.TemporaryDirectory() as directory:
                window, restored = factory(), factory()
                try:
                    window.set_table(frame, "original.csv")
                    if isinstance(window, CorrelationWindow):
                        window.set_reference_table(frame.assign(CD=["4.2", "6.4", "8.6", "10.8"]))
                        window.correlation_page.min_rsq.setValue(.72)
                    else:
                        window.card_check.setChecked(False)
                    window.check_all(window.parameter_list, False)
                    item = next(window.parameter_list.topLevelItem(i)
                                for i in range(window.parameter_list.topLevelItemCount())
                                if window.parameter_list.topLevelItem(i).text(0) == "CD")
                    from PyQt6.QtCore import Qt
                    item.setCheckState(0, Qt.CheckState.Checked)
                    from metrology_app.workspace_store import EXTENSIONS
                    path = Path(directory) / ("document" + EXTENSIONS[window.workspace_type])
                    with patch.object(QFileDialog, "getSaveFileName", return_value=(str(path), "")):
                        self.assertEqual(window.save_wkb(), path.resolve())
                    self.assertFalse(window.document.is_dirty())
                    self.assertEqual(window.workspace_path, path.resolve())
                    restored.load_workspace(path)
                    self.assertEqual(restored.model.frame()["CD"].tolist(), frame["CD"].tolist())
                    self.assertEqual(restored.selection_state(), window.selection_state())
                    if isinstance(window, CorrelationWindow):
                        self.assertEqual(restored.correlation_page.min_rsq.value(), .72)
                        self.assertEqual(restored.reference_model.frame()["CD"].tolist(),
                                         ["4.2", "6.4", "8.6", "10.8"])
                finally:
                    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                        window.close()
                        restored.close()
                    window.deleteLater()
                    restored.deleteLater()
                    APP.processEvents()
