"""Workbook variants through creation, document persistence and recovery."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from metrology_app.matching import MatchWorkbook, ParameterMapping
from metrology_app.matching_window import MatchingWindow
from metrology_app.workbook_startup import WorkbookStartupDialog, analysis_settings
from metrology_app.workspace_store import load_workspace, save_workspace
from tests.legacy_wkb import save_legacy

APP = QApplication.instance() or QApplication([])


def workbook(**settings):
    if settings.get("workbook_type") == "type2":
        settings.setdefault("matching_keys", {"reference": ["Die Seq"], "raw": ["Die Seq"]})
    return MatchWorkbook(
        pd.DataFrame({"Die Seq": ["1", "2", "3"], "CD Reference": ["2.1000", "4.1000", "6.1000"]}),
        pd.DataFrame({"Wafer ID": ["001"] * 3, "Die Seq": ["1", "2", "3"],
                      "CD": ["1.0000", "2.0000", "3.0000"]}),
        [ParameterMapping("CD", "CD Reference", "CD")], **settings,
    )


class WorkbookTypeModelTests(unittest.TestCase):
    def test_types_round_trip_and_share_preview_and_final_calculations(self):
        with tempfile.TemporaryDirectory() as folder:
            for stage in ("preview", "final"):
                original = workbook(result_mode=stage)
                for kind in ("type1", "type2"):
                    with self.subTest(stage=stage, kind=kind):
                        book = workbook(workbook_type=kind, result_mode=stage)
                        saved = book.save(Path(folder) / f"{kind}-{stage}.mwkb")
                        restored = MatchWorkbook.load(saved)
                        self.assertEqual(restored.workbook_type, kind)
                        self.assertEqual(load_workspace(saved).states["match"]["workbook_type"], kind)
                        pd.testing.assert_frame_equal(restored.raw, book.raw)
                        pd.testing.assert_frame_equal(restored.reference, book.reference)
                        pd.testing.assert_frame_equal(restored.analyze().summary.drop(columns="Match type"),
                                                      original.analyze().summary.drop(columns="Match type"))
                        pd.testing.assert_frame_equal(restored.analyze().series("CD"), original.analyze().series("CD"))

    def test_old_containers_and_legacy_wkb_default_to_type1(self):
        with tempfile.TemporaryDirectory() as folder:
            snapshot = workbook().to_snapshot()
            snapshot.states["match"].pop("workbook_type", None)
            old = save_workspace(Path(folder) / "old.mwkb", snapshot)
            legacy = save_legacy(workbook(), Path(folder) / "legacy.wkb")
            for path in (old, legacy):
                before = path.read_bytes()
                restored = MatchWorkbook.load(path)
                self.assertEqual(restored.workbook_type, "type1")
                self.assertEqual(restored.to_snapshot().states["match"]["workbook_type"], "type1")
                self.assertEqual(path.read_bytes(), before)

    def test_explicit_invalid_types_are_rejected(self):
        for value in ("type3", "", None, 1, []):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "Workbook Type"):
                    workbook(workbook_type=value)
                with self.assertRaisesRegex(ValueError, "Workbook Type"):
                    analysis_settings({"workbook_type": value})


class WorkbookTypeWindowTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.folder = Path(self.scratch.name)
        self.windows = []

    def window(self, kind="type1"):
        window = MatchingWindow()
        self.windows.append(window)
        window.apply_analysis_settings({"workbook_type": kind}, refresh=False)
        if kind == "type2":
            window.set_matching_keys({"reference": ["Die Seq"], "raw": ["Die Seq"]})
        window.document.mark_clean()
        return window

    def tearDown(self):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            for window in reversed(self.windows):
                if hasattr(window, "document"):
                    window.document.force_close = True
                window.close()
                window.deleteLater()
        APP.processEvents()
        self.scratch.cleanup()

    def test_new_dialog_defaults_to_type1_and_keeps_match_type_independent(self):
        dialog = WorkbookStartupDialog(new=True)
        try:
            self.assertEqual(dialog.settings()["workbook_type"], "type1")
            self.assertEqual([dialog.workbook_type.itemText(i) for i in range(dialog.workbook_type.count())],
                             ["Type1", "Type2"])
            dialog.workbook_type.setCurrentIndex(dialog.workbook_type.findData("type2"))
            dialog.match_type.setCurrentText("NOVA")
            self.assertEqual(dialog.settings()["workbook_type"], "type2")
            self.assertEqual(dialog.settings()["match_type"], "Reference")
            dialog.select_new()
            self.assertEqual(dialog.settings()["workbook_type"], "type1")
        finally:
            dialog.deleteLater()
            APP.processEvents()

    def test_shell_creates_the_selected_type_with_a_clean_title(self):
        from metrology_app.shell import MainWindow
        self.assertIn("workbook_type", analysis_settings())
        shell = MainWindow()
        self.windows.append(shell)

        def create():
            dialog = APP.activeModalWidget()
            if isinstance(dialog, WorkbookStartupDialog):
                dialog.select_new()
                dialog.workbook_type.setCurrentIndex(dialog.workbook_type.findData("type2"))
                dialog.confirm_button.click()

        QTimer.singleShot(0, create)
        child = shell.launch_match_workbook()
        self.assertIsNotNone(child)
        self.assertEqual(child.workbook_type, "type2")
        self.assertIn("Type2", child.windowTitle())
        self.assertFalse(child.document.is_dirty())

    def test_analyzed_type2_survives_stage_changes_and_save_as(self):
        window = self.window("type2")
        book = workbook()
        window.set_reference_frame(book.reference)
        window.set_raw_frame(book.raw)
        window.run_analysis()
        self.assertEqual(window.current_workbook().workbook_type, "type2")
        # Other Analysis settings must not reset a fixed Workbook Type.
        window.apply_analysis_settings({"match_type": "NOVA"}, refresh=False)
        self.assertEqual(window.workbook_type, "type2")
        path = window.save_workbook(self.folder / "type2.mwkb")
        reopened = self.window()
        reopened.load_workbook(path)
        self.assertEqual(reopened.workbook.workbook_type, "type2")
        self.assertIn("Type2", reopened.windowTitle())
        self.assertFalse(reopened.document.is_dirty())
        reopened.load_workbook(path, analysis_settings={"match_type": "TEM"})
        self.assertEqual(reopened.workbook_type, "type2")
        self.assertEqual(reopened.match_type.currentText(), "Reference")
        reopened.result_mode.setCurrentText("Final")
        reopened.set_raw_frame(book.raw)
        reopened.run_analysis()
        other = reopened.save_workbook(self.folder / "type2-copy.mwkb")
        self.assertEqual(MatchWorkbook.load(other).workbook_type, "type2")
        self.assertEqual(MatchWorkbook.load(path).result_mode, "preview")

    def test_draft_save_and_recovery_retain_type2(self):
        window = self.window("type2")
        path = window.save_workbook(self.folder / "draft.mwkb")
        reopened = self.window()
        reopened.load_workbook(path)
        self.assertEqual(reopened.workbook_type, "type2")
        self.assertTrue(reopened.workspace_snapshot().states["match"]["draft"])
        self.assertFalse(reopened.document.is_dirty())
        reopened.set_raw_frame(workbook().raw)
        reopened.document.recovery_path = self.folder / "recovery.mwkb"
        reopened.document.write_recovery()
        self.assertTrue(reopened.document.recovery_path.is_file(), reopened.document.last_warning)
        recovered = self.window()
        recovered.document.recover(reopened.document.recovery_path)
        self.assertEqual(recovered.workbook_type, "type2")
        self.assertIn("Type2", recovered.windowTitle())
        self.assertTrue(recovered.document.is_dirty())

    def test_old_analyzed_and_draft_files_open_as_clean_type1(self):
        for draft in (False, True):
            with self.subTest(draft=draft):
                snapshot = workbook(match_type="NOVA").to_snapshot()
                snapshot.states["match"].pop("workbook_type", None)
                snapshot.states["match"]["draft"] = draft
                path = save_workspace(self.folder / f"old-{draft}.mwkb", snapshot)
                original = path.read_bytes()
                window = self.window("type2")
                window.load_workbook(path)
                self.assertEqual(window.workbook_type, "type1")
                self.assertEqual(window.match_type.currentText(), "NOVA")
                self.assertIn("Type1", window.windowTitle())
                self.assertFalse(window.document.is_dirty())
                self.assertEqual(path.read_bytes(), original)
                window.save_workbook(path)
                self.assertEqual(load_workspace(path).states["match"]["workbook_type"], "type1")

    def test_invalid_draft_type_is_rejected_before_replacing_the_current_document(self):
        window = self.window("type2")
        snapshot = deepcopy(window.workspace_snapshot())
        snapshot.states["match"]["workbook_type"] = "type3"
        with self.assertRaisesRegex(ValueError, "Workbook Type"):
            window.restore_workspace(snapshot)
        self.assertEqual(window.workbook_type, "type2")
        self.assertFalse(window.document.is_dirty())

    def test_new_workbook_resets_a_type2_document_to_the_new_selection(self):
        window = self.window("type2")
        path = window.save_workbook(self.folder / "original.mwkb")
        original = path.read_bytes()

        def create():
            dialog = APP.activeModalWidget()
            if isinstance(dialog, WorkbookStartupDialog):
                dialog.confirm_button.click()  # Default Type1.

        QTimer.singleShot(0, create)
        window.start_workbook(new=True)
        self.assertEqual(window.workbook_type, "type1")
        self.assertIn("Type1", window.windowTitle())
        self.assertFalse(window.document.is_dirty())
        self.assertEqual(path.read_bytes(), original)
