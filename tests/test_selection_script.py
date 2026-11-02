"""Portable selection recipes retain conditions and source participation."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from metrology_app.selection_script import export_script, import_script
from metrology_app.data_selection import FrameSelectionDialog
from metrology_app.spectra_export import export_spectra

APP = QApplication.instance() or QApplication([])


class SelectionScriptTests(unittest.TestCase):
    def test_live_conflict_is_reported_without_copying_a_stale_script(self):
        frame = pd.DataFrame({"Wafer ID": ["W1", "W1"], "Die Seq": [1, 1]})
        dialog = FrameSelectionDialog(frame)
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        dialog.show()
        dialog.selection_script_button.click()
        QApplication.clipboard().setText("retain clipboard")
        dialog.model.setData(dialog.model.index(0, 0), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
        panel = dialog.script_dialog
        self.assertIn("conflicting", panel.message.text())
        self.assertFalse(panel.copy_button.isEnabled())
        self.assertEqual(panel.editor.toPlainText(), "")
        panel.copy_button.click()
        self.assertEqual(QApplication.clipboard().text(), "retain clipboard")
        dialog.check_visible(False)
        self.assertTrue(panel.copy_button.isEnabled())
        self.assertFalse(json.loads(panel.editor.toPlainText())["records"][0]["use"])

    def test_selection_matches_four_fields_despite_changed_names_paths_and_die_format(self):
        source = pd.DataFrame({"Raw Data / Cur SME File Path": [
            "C:/OldComputer/measurements/W1_Die1.sme", "C:/OldComputer/measurements/W1_Die2.sme"],
            "Raw Data / Wafer ID": ["W1", "W1"], "Raw Data / Lot ID": ["L1"] * 2,
            "Raw Data / PAD Name": ["P1"] * 2, "Raw Data / Die Seq": ["001", "002"]})
        target = pd.DataFrame({"Raw Data / Cur SME File Path": [
            "D:/Current/renamedA.sme", "D:/Current/renamedB.sme"],
            "Raw Data / Wafer ID": ["W1", "W1"], "Raw Data / Lot ID": ["L1"] * 2,
            "Raw Data / PAD Name": ["P1"] * 2, "Raw Data / Die Seq": [2.0, 1.0]})
        script = export_script(source, {"checked": [1]})
        self.assertEqual(import_script(target, script)["checked"], [0])
        self.assertTrue(source.iloc[0, 0].startswith("C:/OldComputer"))
        self.assertTrue(target.iloc[0, 0].startswith("D:/Current"))

    def test_repeated_measurement_identity_shares_one_state_and_rejects_conflicts(self):
        source = pd.DataFrame({"Wafer ID": ["W1", "W1"], "Die Seq": [1, 1]})
        with self.assertRaisesRegex(ValueError, "conflicting"):
            export_script(source, {"checked": [0]})
        script = export_script(source, {"checked": []})
        self.assertEqual(len(json.loads(script)["records"]), 1)
        self.assertEqual(import_script(source, script)["checked"], [])

    def test_recipe_transfers_all_conditions_and_checks_after_source_reordering(self):
        frame = pd.DataFrame({"Raw Data / Wafer ID": ["W1", "W1", "W2"],
                              "Raw Data / Die Seq": ["001", "002", "001"],
                              "Raw Data / CD": ["1.200", "2.300", "3.400"]})
        view = {"filters": [[{"column": "Raw Data / Wafer ID", "values": ["W1"]},
                              {"column": "Raw Data / CD", "minimum": 1.2, "maximum": 3.0}],
                             [{"column": "Raw Data / Die Seq", "query": "001"}]],
                "row_bools": [["or"], []], "group_bools": ["and"],
                "show": "unchecked", "search": "W1", "hide_excluded": True}
        script = export_script(frame, {"checked": [0, 2], **view})
        self.assertEqual(json.loads(script)["version"], 2)
        target = frame.iloc[[2, 0, 1]].reset_index(drop=True)
        restored = import_script(target, script)
        self.assertEqual(restored, {"checked": [0, 1], **view})
        self.assertEqual(frame.iloc[0, 2], "1.200")

    def test_selection_script_button_copies_live_edits_and_pastes_into_another_dialog(self):
        frame = pd.DataFrame({"Wafer ID": ["W1", "W2"], "Die Seq": ["001", "002"]})
        source = FrameSelectionDialog(frame)
        target = FrameSelectionDialog(frame.iloc[::-1].reset_index(drop=True))
        for dialog in (source, target):
            self.addCleanup(dialog.deleteLater)
            self.addCleanup(dialog.close)
        source.show()
        source.selection_script_button.click()
        editor = source.script_dialog
        source.search.setText("W1")
        source.check_visible(False)
        source.hide_excluded.setChecked(True)
        recipe = json.loads(editor.editor.toPlainText())
        self.assertEqual([r["use"] for r in recipe["records"]], [False, True])
        self.assertEqual(recipe["search"], "W1")
        self.assertTrue(recipe["hide_excluded"])
        editor.copy_button.click()
        target.selection_script_button.click()
        target.script_dialog.paste_button.click()
        target.script_dialog.apply_button.click()
        self.assertEqual(target.model.checked, {target.model.ids[0]})
        self.assertEqual(target.search.text(), "W1")
        self.assertTrue(target.hide_excluded.isChecked())
        before = target.selection_script()
        target.script_dialog.editor.setPlainText('{"version":999}')
        target.script_dialog.apply_button.click()
        self.assertEqual(target.selection_script(), before)
        self.assertIn("Unsupported", target.script_dialog.message.text())

    def test_invalid_recipes_are_rejected_before_selection_is_changed(self):
        frame = pd.DataFrame({"Wafer ID": ["W1", "W2"]})
        script = export_script(frame, {"checked": [1]})
        for change in (
                {"version": 1}, {"hide_excluded": "true"},
                {"records": [{"key": "unknown", "use": False}]},
                {"filters": [[{"column": "Missing", "values": ["W1"]}]], "row_bools": [[]]},
                {"filters": [[{"column": "Wafer ID", "minimum": float("inf")}]], "row_bools": [[]]},
                {"filters": [[{"column": "Wafer ID"}]], "row_bools": [["xor"]]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                import_script(frame, json.dumps({**json.loads(script), **change}))
        self.assertEqual(import_script(frame, script)["checked"], [1])

    def test_export_preflight_and_cancellation_keep_existing_files_and_sources(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            paths = [root / "sources" / folder / "same.sme" for folder in ("A", "B")]
            for index, path in enumerate(paths):
                path.parent.mkdir(parents=True)
                path.write_bytes(bytes([index]) * 1024)
            target = root / "export"
            outputs = export_spectra(paths, target)
            self.assertEqual([p.relative_to(target).as_posix() for p in outputs],
                             ["sources/A/same.sme", "sources/B/same.sme"])
            with self.assertRaisesRegex(ValueError, "overwrite"):
                export_spectra(paths, target)
            self.assertEqual(outputs[0].read_bytes(), paths[0].read_bytes())
            with self.assertRaisesRegex(ValueError, "unavailable"):
                export_spectra([paths[0], root / "missing.sme"], root / "missing-output")
            self.assertFalse((root / "missing-output").exists())
            cancelled = []
            with self.assertRaises(InterruptedError):
                export_spectra(paths, root / "cancelled", cancelled=lambda: bool(cancelled),
                               progress=lambda *_: cancelled.append(True))
            self.assertEqual(list((root / "cancelled").rglob("*.sme")), [])
            self.assertTrue(all(p.exists() for p in paths))
