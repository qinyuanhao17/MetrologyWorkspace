"""Incomplete matching input does not prevent independent analysis editing."""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from metrology_app.matching_window import MatchingWindow

APP = QApplication.instance() or QApplication([])


class IncompleteWorkbookWorkspaceTests(unittest.TestCase):
    @staticmethod
    def close_window(window):
        window.document.force_close = True
        window.close()
        window.deleteLater()
        APP.processEvents()

    def test_cleared_edge_columns_and_named_empty_fields_are_not_analysis_data(self):
        window = MatchingWindow()
        self.addCleanup(self.close_window, window)
        window.set_reference_frame(pd.DataFrame({"CD Reference": ["2.000", "4.000", "6.000"]}))
        raw = pd.DataFrame({"Cur SME File Path": ["source"] * 3, "Wafer ID": ["001"] * 3,
                            "Lot ID": ["Lot-01"] * 3, "CD": ["1.000", "2.000", "3.000"],
                            "Empty": ["", "", ""]})
        window.set_raw_frame(raw)
        state = dict(window.group_controls.state)
        state["mark_enabled"] = True
        window.group_controls.restore(state)
        window.raw_model.edit({(row, column): "" for row in range(4) for column in (0, 1)})
        self.assertEqual(window.raw_frame.columns.tolist(), ["Lot ID", "CD"])
        self.assertEqual(window.raw_frame.CD.tolist(), ["1.000", "2.000", "3.000"])
        self.assertNotIn("must be unique", window.raw_source.text())
        self.assertEqual(window.raw_model.document_frame().columns.tolist(), ["", "", "Lot ID", "CD", "Empty"])
        self.assertTrue(window.run_action.isEnabled())
        self.assertAlmostEqual(window.run_analysis().card("CD").slope, 2)

    def test_pasted_empty_columns_do_not_become_mapping_candidates_or_duplicate_names(self):
        window = MatchingWindow()
        self.addCleanup(self.close_window, window)
        reference = pd.DataFrame({"CD Reference": ["2.000", "4.000", "6.000"],
                                  "Empty Reference": ["", " ", ""]})
        raw = pd.DataFrame([["", "", "1.000", ""], ["", "", "2.000", " "],
                            ["", "", "3.000", ""]], columns=["", "", "CD", "Unused"])
        window.set_reference_frame(reference)
        window.set_raw_frame(raw)
        self.assertEqual(window.reference_frame.columns.tolist(), ["CD Reference"])
        self.assertEqual(window.raw_frame.columns.tolist(), ["CD"])
        self.assertEqual(window.mapping_table.rowCount(), 1)
        picker = window.mapping_table.cellWidget(0, 3)
        self.assertEqual([picker.itemText(i) for i in range(picker.count())], ["", "CD"])
        pd.testing.assert_frame_equal(window.reference_model.document_frame(), reference)
        pd.testing.assert_frame_equal(window.raw_model.document_frame(), raw)

    def test_raw_only_workbook_buttons_open_all_three_editable_workspaces_without_matching(self):
        window = MatchingWindow()
        self.addCleanup(self.close_window, window)
        window.match_type.setCurrentText("NOVA")
        raw = pd.DataFrame({"Wafer ID": ["001"] * 3, "Die Seq": ["002", "036", "085"],
                            "FIELD X": ["-1", "0", "1"], "FIELD Y": ["0", "1", "0"],
                            "CD": ["1.000", "2.000", "3.000"]})
        window.set_raw_frame(raw)
        window.show()
        APP.processEvents()
        self.assertFalse(window.run_action.isEnabled())
        self.assertFalse(window.analyze_button.isEnabled())
        for button in (window.correlation_button, window.preview_open_button, window.preview_dynamic_button):
            self.assertTrue(button.isEnabled(), button.text())
            button.click()
        children = [widget for widget in APP.topLevelWidgets() if widget.isVisible()
                    and getattr(widget, "workspace_type", "") in ("correlation_trend", "wafer_map", "dynamic")]
        self.assertEqual({child.workspace_type for child in children}, {"correlation_trend", "wafer_map", "dynamic"})
        self.assertIsNone(window.result)
        self.assertTrue(window.status.isVisible())
        for child in children:
            child.tabs.setCurrentIndex(1 if child.workspace_type == "correlation_trend" else 0)
            child.sheet.setCurrentIndex(child.model.index(0, 0))
            child.sheet.setFocus()
            manual = raw.assign(CD=["4.100", "5.200", "6.300"])
            APP.clipboard().setText(manual.to_csv(sep="\t", index=False))
            QTest.keyClick(child.sheet, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
            child.recognize()
            self.assertEqual(child.model.document_frame()["CD"].tolist(), ["4.100", "5.200", "6.300"])
        self.assertTrue(window.reference_model.document_frame().empty)
        pd.testing.assert_frame_equal(window.raw_model.document_frame(), raw)

    def test_mismatched_rows_open_independent_sources_without_borrowing_row_identity(self):
        window = MatchingWindow()
        self.addCleanup(self.close_window, window)
        window.match_type.setCurrentText("NOVA")
        reference = pd.DataFrame({"CD Reference": ["2.000", "4.000"]})
        raw = pd.DataFrame({"Wafer ID": ["001"] * 3, "Die Seq": ["002", "036", "085"],
                            "CD": ["1.000", "2.000", "3.000"]})
        window.set_reference_frame(reference)
        window.set_raw_frame(raw)
        self.assertFalse(window.run_action.isEnabled())
        child = window.open_correlation_workspace()
        pd.testing.assert_frame_equal(child.reference_model.document_frame(), reference)
        pd.testing.assert_frame_equal(child.raw_model.document_frame(), raw)
        self.assertIsNone(window.result)
        self.assertTrue(window.open_stage_workspace("preview").isVisible())
        self.assertTrue(window.open_dynamic_workspace("preview").isVisible())
        with self.assertRaisesRegex(ValueError, "same number of rows"):
            window.run_analysis()

    def test_empty_final_workbook_allows_manual_child_data_and_saves_it_as_a_draft(self):
        window = MatchingWindow()
        self.addCleanup(self.close_window, window)
        window.result_mode.setCurrentText("Final")
        self.assertTrue(window.correlation_button.isEnabled())
        self.assertTrue(window.final_open_button.isEnabled())
        self.assertTrue(window.final_dynamic_button.isEnabled())
        correlation = window.open_correlation_workspace()
        dynamic = window.open_dynamic_workspace("final")
        wafer = window.open_stage_workspace("final")
        self.assertTrue(correlation.raw_model.document_frame().empty)
        self.assertTrue(dynamic.model.document_frame().empty)
        self.assertTrue(wafer.model.document_frame().empty)
        manual = pd.DataFrame({"Wafer ID": ["001"] * 3, "Die Seq": ["002", "036", "085"],
                               "X": ["-1.000", "0.000", "1.000"], "Y": ["0.000", "1.000", "0.000"],
                               "CD": ["4.100", "5.200", "6.300"]})
        wafer.set_table(manual, "Manual")
        with TemporaryDirectory() as folder:
            path = Path(folder) / "empty-with-manual-map.wkb"
            window.save_workbook(path)
            restored = MatchingWindow()
            self.addCleanup(self.close_window, restored)
            restored.load_workbook(path)
            self.assertIsNone(restored.result)
            self.assertFalse(restored.run_action.isEnabled())
            opened = restored.open_stage_workspace("final")
            pd.testing.assert_frame_equal(opened.model.document_frame(), manual)

    def test_nonempty_duplicate_columns_still_reject_replacement_without_touching_source(self):
        window = MatchingWindow()
        self.addCleanup(self.close_window, window)
        raw = pd.DataFrame({"CD": ["1.000", "2.000", "3.000"]})
        window.set_raw_frame(raw)
        with self.assertRaisesRegex(ValueError, "column names must be unique"):
            window.set_raw_frame(pd.DataFrame([["1.000", "4.000"], ["2.000", "5.000"]], columns=["CD", "CD"]))
        pd.testing.assert_frame_equal(window.raw_model.document_frame(), raw)


if __name__ == "__main__":
    unittest.main()
