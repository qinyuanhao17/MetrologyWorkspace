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
    def test_checked_row_modes_retain_filters_and_refresh_after_bulk_edits(self):
        frame = pd.DataFrame({"Wafer ID": ["W1", "W2", "W3"]})
        filters = [[{"column": "Wafer ID", "values": ["W1"]}]]
        dialog = FrameSelectionDialog(frame, filters=filters, row_bools=[[]])
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        dialog.apply_selection_script(export_script(frame, {"checked": [0, 2], "filters": filters,
                                                            "row_bools": [[]], "show": "unchecked"}))
        self.assertEqual(dialog.model.rows, [1])
        dialog.check_visible(True)
        self.assertEqual(dialog.model.rows, [])
        self.assertTrue(all(row["use"] for row in json.loads(dialog.selection_script())["records"]))
        dialog.show_rows.setCurrentIndex(dialog.show_rows.findData("checked"))
        self.assertEqual(dialog.model.rows, [0, 1, 2])
        dialog.search.setText("W3")
        self.assertEqual(dialog.model.rows, [2])
        dialog.search.clear()
        dialog.show_rows.setCurrentIndex(dialog.show_rows.findData("filtered"))
        self.assertEqual(dialog.model.rows, [0])
        self.assertEqual(json.loads(dialog.selection_script())["filters"], filters)

    def test_script_search_retains_values_from_source_columns_missing_in_target(self):
        source = pd.DataFrame({"Raw Data / Wafer ID": ["W1", "W2"], "Reference / CD": ["851.195", "840.921"]})
        target = FrameSelectionDialog(source[["Raw Data / Wafer ID"]])
        self.addCleanup(target.close)
        self.addCleanup(target.deleteLater)
        target.apply_selection_script(export_script(source, {"checked": [0, 1], "show": "filtered", "search": "851.195"}))
        self.assertEqual(target.model.rows, [0])
        self.assertEqual(target.model.frame["Reference / CD"].tolist(), ["851.195", "840.921"])

    def test_copied_filter_alias_does_not_replace_the_targets_source_identity(self):
        from metrology_app.selection_script import context_frame
        source = pd.DataFrame({"Raw Data / Wafer": ["W1", "W2"]})
        target = pd.DataFrame({"Raw Data / Wafer ID": ["W1", "W9"]})
        text = export_script(source, {"checked": [0], "filters": [[{"column": "Raw Data / Wafer", "query": "W"}]],
                                      "row_bools": [[]]})
        copied = import_script(target, text, allow_partial=True, current_checked={1})
        exported = json.loads(export_script(context_frame(target, copied), copied))
        self.assertEqual([record["wafer_id"] for record in exported["records"]], ["W1", "W9"])

    def test_all_workbook_child_types_copy_the_complete_script_as_independent_selection(self):
        from copy import deepcopy
        from PyQt6.QtCore import QTimer
        from metrology_app.matching_window import MatchingWindow
        from metrology_app.match_groups import row_ids
        from tests.test_case_switching import paste_case
        owner = MatchingWindow()
        owner.document.force_close = True
        try:
            owner.match_type.setCurrentText("NOVA")
            paste_case(owner, "CD", 6)
            children = (owner.open_stage_workspace("preview"), owner.open_correlation_workspace(),
                        owner.open_dynamic_workspace("preview"))
            children[-1].set_table(owner.raw_frame.copy(), "Independent Dynamic measurements")
            view = {"filters": [[{"column": "Reference / CD Reference", "minimum": 11}],
                                [{"column": "Raw Data / Wafer ID", "query": "CD"}]],
                    "row_bools": [[], []], "group_bools": ["or"],
                    "show": "filtered", "search": "CD", "hide_excluded": True}
            selection = {"records": [{"key": key, "id": str(i)} for i, key in enumerate(row_ids(owner.raw_frame))],
                         "excluded": ["1", "4"], "view_filter_groups": view["filters"],
                         "view_filter_row_bools": view["row_bools"], "view_filter_group_bools": view["group_bools"],
                         "view_show": view["show"], "view_search": view["search"], "hide_excluded": True}
            for state in (owner.group_controls.state, owner.group_controls.state["applied"]):
                state["data_selection"] = deepcopy(selection)
            for child in children:
                with self.subTest(workspace=child.workspace_type):
                    before = child.model.frame().copy()
                    action = next(a for a in child.data_menu.actions() if a.text() == "Copy WKB Selection")
                    from unittest.mock import patch
                    with patch("metrology_app.window.QMessageBox.warning") as warning:
                        action.trigger()
                    self.assertFalse(warning.called, str(warning.call_args))
                    pd.testing.assert_frame_equal(child.model.frame(), before)
                    self.assertEqual(child.participating_positions(child.model.frame()), {0, 2, 3, 5},
                                     f"{child.model.frame().to_dict('list')} / {child._local_selection_excluded} / {child._workbook_selection_applies}")
                    self.assertFalse(child._workbook_selection_applies)
                    self.assertTrue(child.full_data_action.isChecked())
                    for name, value in view.items():
                        self.assertEqual(child._local_view[name], value)
                    errors = []
                    def inspect():
                        dialog = APP.activeModalWidget()
                        try:
                            self.assertEqual(dialog.filter_groups, view["filters"])
                            self.assertTrue(dialog.hide_excluded.isChecked())
                            self.assertEqual(json.loads(dialog.selection_script())["filters"], view["filters"])
                        except Exception as error:
                            errors.append(error)
                        finally:
                            dialog.reject()
                    QTimer.singleShot(0, inspect)
                    child.data_selection_action.trigger()
                    self.assertEqual(errors, [])
            self.assertEqual(owner.group_controls.state["data_selection"], selection)
        finally:
            owner.close()
            owner.deleteLater()
            APP.processEvents()

    def test_script_application_updates_filter_controls_and_copied_reference_values(self):
        frame = pd.DataFrame({"Raw Data / Wafer ID": ["W1", "W2"], "Reference / CD": ["1.200", "2.300"]})
        view = {"filters": [[{"column": "Reference / CD", "minimum": 2}]],
                "row_bools": [[]], "group_bools": [], "show": "filtered", "search": "W", "hide_excluded": True}
        text = export_script(frame, {"checked": [1], **view})
        dialog = FrameSelectionDialog(frame[["Raw Data / Wafer ID"]].iloc[::-1].reset_index(drop=True))
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        dialog.apply_selection_script(text)
        self.assertEqual(dialog.filter_groups, view["filters"])
        self.assertEqual(dialog.show_rows.currentData(), "filtered")
        self.assertTrue(dialog.hide_excluded.isChecked())
        self.assertEqual(dialog.search.text(), "W")
        self.assertEqual(dialog.model.frame["Reference / CD"].tolist(), ["2.300", "1.200"])
        self.assertEqual(dialog.model.rows, [0])
        self.assertTrue(dialog.view_state()["context"])
        frame["Reference / CD"] = ["9.900", "0.100"]
        dialog.apply_selection_script(export_script(frame, {"checked": [1], **view}))
        self.assertEqual(dialog.model.frame["Reference / CD"].tolist(), ["0.100", "9.900"])
        self.assertEqual(dialog.model.rows, [1])

    def test_script_copies_conditions_and_missing_filter_data_by_identity(self):
        from metrology_app.selection_script import context_frame
        source = pd.DataFrame({"Raw Data / Wafer ID": ["W1", "W2", "W3"],
                               "Reference / CD": ["1.200", "2.300", "3.400"]})
        view = {"filters": [[{"column": "Reference / CD", "minimum": 2}],
                            [{"column": "Raw Data / Wafer ID", "values": ["W2"]}]],
                "row_bools": [[], []], "group_bools": ["or"],
                "show": "filtered", "search": "W", "hide_excluded": True}
        text = export_script(source, {"checked": [0, 2], **view})
        target = pd.DataFrame({"Raw Data / Wafer ID": ["W3", "W1", "W9"]})
        copied = import_script(target, text, allow_partial=True, current_checked={2})
        self.assertEqual(copied["checked"], [0, 1, 2])
        self.assertEqual((copied["matched"], copied["unmatched"]), (2, 1))
        for name, value in view.items():
            self.assertEqual(copied[name], value)
        self.assertEqual(context_frame(target, copied)["Reference / CD"].tolist(), ["3.400", "1.200", ""])
        self.assertNotIn("Reference / CD", target)

    def test_copy_workbook_checks_matches_four_fields_and_keeps_unmatched_spectra(self):
        source = pd.DataFrame({"Wafer ID": ["W1", "W1", "W1"], "Lot ID": ["L1"] * 3,
                               "PAD Name": ["P1"] * 3, "Die Seq": ["001", "002", "001"],
                               "Cur SME File Path": ["old1.sme", "old2.sme", "old3.sme"]})
        target = pd.DataFrame({"Wafer ID": ["W1", "W1", "W9"], "Lot ID": ["L1"] * 3,
                               "PAD Name": ["P1"] * 3, "Die Seq": [2., 1., 1.],
                               "SME Name": ["new1.sme", "new2.sme", "new3.sme"]})
        state = import_script(target, export_script(source, {"checked": [0, 2]}),
                              allow_partial=True, current_checked={0, 2})
        self.assertEqual(state["checked"], [1, 2])
        self.assertEqual((state["matched"], state["unmatched"]), (2, 1))
        with self.assertRaisesRegex(ValueError, "conflicting"):
            export_script(source, {"checked": [0]})
        with self.assertRaisesRegex(ValueError, "No .*match"):
            import_script(target, export_script(source.iloc[:0], {"checked": []}), allow_partial=True)

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
                {"filters": None},
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
