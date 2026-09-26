"""User-visible Card Matching workflow tests."""

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PyQt6.QtWidgets import QApplication

from metrology_app.matching_window import MatchingWindow
from metrology_app.module_registry import create_default_registry


APP = QApplication.instance() or QApplication([])


class MatchingWindowTests(unittest.TestCase):
    def setUp(self):
        self.window = MatchingWindow()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def reference(self):
        return pd.DataFrame({
            "Wafer ID": ["W1", "W2", "W3"],
            "CD_Bot Reference": [12.0, 22.0, 32.0],
            "SPA Reference": [5.0, 7.0, 9.0],
        })

    def raw(self):
        return pd.DataFrame({
            "Wafer ID": ["W1", "W2", "W3"],
            "CD_Bot": [1.0, 2.0, 3.0],
            "SPA": [2.0, 3.0, 4.0],
        })

    def test_reference_is_loaded_before_raw_data_and_enables_analysis(self):
        self.assertFalse(self.window.raw_paste_button.isEnabled())
        self.assertFalse(self.window.analyze_button.isEnabled())

        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.assertTrue(self.window.raw_paste_button.isEnabled())
        self.assertFalse(self.window.analyze_button.isEnabled())

        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.assertEqual(self.window.mapping_table.rowCount(), 2)
        self.assertTrue(self.window.analyze_button.isEnabled())

        result = self.window.run_analysis()
        self.assertEqual(result.parameter_names, ("CD_Bot", "SPA"))
        self.assertEqual(self.window.summary_model.rowCount(), 2)
        self.assertEqual(self.window.tabs.currentWidget(), self.window.results_page)

    def test_final_mode_keeps_evaluated_values_equal_to_raw_data(self):
        reference = pd.DataFrame({"CD Reference": [10.0, 20.0, 30.0]})
        raw = pd.DataFrame({"CD": [11.0, 19.0, 31.0]})
        self.window.set_reference_frame(reference, "Clipboard")
        self.window.set_raw_frame(raw, "Clipboard")
        self.window.result_mode.setCurrentText("Final")

        result = self.window.run_analysis()

        self.assertEqual(result.series("CD")["Evaluated Value"].tolist(), [11.0, 19.0, 31.0])

    def test_preview_and_final_fullmap_open_in_the_existing_wafer_workspace(self):
        opened = []

        class FakeWaferWorkspace:
            def set_table(self, frame, source):
                self.frame = frame
                self.source = source

            def show(self):
                opened.append(self)

        self.window.close()
        self.window.deleteLater()
        self.window = MatchingWindow(wafer_window_factory=FakeWaferWorkspace)
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.set_preview_frame(pd.DataFrame({
            "Wafer ID": ["P1", "P1"],
            "X": [-1.0, 1.0],
            "Y": [0.0, 0.0],
            "CD_Bot": [4.0, 5.0],
            "SPA": [5.0, 6.0],
        }), "Preview clipboard")
        final = pd.DataFrame({
            "Wafer ID": ["F1", "F1"],
            "X": [-1.0, 1.0],
            "Y": [0.0, 0.0],
            "CD_Bot": [41.0, 51.0],
            "SPA": [11.0, 13.0],
        })
        self.window.set_final_frame(final, "Final clipboard")
        self.window.run_analysis()

        preview_workspace = self.window.open_stage_workspace("preview")
        final_workspace = self.window.open_stage_workspace("final")

        self.assertEqual(len(opened), 2)
        self.assertIn("Preview", preview_workspace.source)
        self.assertIn("Final", final_workspace.source)
        self.assertEqual(preview_workspace.frame["CD_Bot"].tolist(), [42.0, 52.0])
        pd.testing.assert_frame_equal(final_workspace.frame, final)

    def test_pasting_fullmap_after_analysis_keeps_match_results_interactive(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()

        self.window.set_preview_frame(pd.DataFrame({
            "Wafer ID": ["P1", "P1"],
            "CD_Bot": [4.0, 5.0],
            "SPA": [5.0, 6.0],
        }), "Preview clipboard")
        self.window.parameter_picker.setCurrentText("SPA")

        self.assertIsNotNone(self.window.workbook)
        self.assertIsNotNone(self.window.result)
        self.assertEqual(self.window.parameter_picker.currentText(), "SPA")

    def test_replacing_reference_requires_fresh_raw_data(self):
        self.window.set_reference_frame(self.reference(), "First Reference")
        self.window.set_raw_frame(self.raw(), "First Raw")
        self.assertTrue(self.window.analyze_button.isEnabled())

        replacement = self.reference().rename(columns={"CD_Bot Reference": "CD_Top Reference"})
        self.window.set_reference_frame(replacement, "Replacement Reference")

        self.assertTrue(self.window.raw_frame.empty)
        self.assertEqual(self.window.raw_model.rowCount(), 0)
        self.assertFalse(self.window.analyze_button.isEnabled())
        self.assertIn("Paste the row-aligned Raw Data", self.window.status.text())

    def test_changing_analysis_options_invalidates_the_displayed_result(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()
        self.assertTrue(self.window.export_button.isEnabled())

        self.window.result_mode.setCurrentText("Final")

        self.assertIsNone(self.window.result)
        self.assertFalse(self.window.export_button.isEnabled())
        self.assertEqual(self.window.summary_model.rowCount(), 0)
    def test_nova_shows_single_wafer_slope_and_r_squared_but_tem_does_not(self):
        reference = pd.DataFrame({
            "Wafer ID": ["W1"] * 3 + ["W2"] * 3,
            "CD Reference": [3.0, 5.0, 7.0, 1.0, 4.0, 7.0],
        })
        raw = pd.DataFrame({
            "Wafer ID": ["W1"] * 3 + ["W2"] * 3,
            "CD": [1.0, 2.0, 3.0, 1.0, 2.0, 3.0],
        })
        self.window.set_reference_frame(reference, "Clipboard")
        self.window.set_raw_frame(raw, "Clipboard")
        self.window.match_type.setCurrentText("NOVA")
        self.window.run_analysis()

        self.assertTrue(self.window.result_plots.isTabEnabled(self.window.wafer_tab_index))
        self.assertEqual(self.window.wafer_summary_model.rowCount(), 2)

        self.window.match_type.setCurrentText("TEM")
        self.window.run_analysis()
        self.assertFalse(self.window.result_plots.isTabEnabled(self.window.wafer_tab_index))
    def test_exports_excel_and_separate_plot_images_after_analysis(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.set_preview_frame(self.raw().assign(**{
            "Wafer ID": ["P1", "P2", "P3"],
        }), "Preview clipboard")
        final = pd.DataFrame({
            "Wafer ID": ["F1", "F2", "F3"],
            "CD_Bot": [12.0, 22.0, 32.0],
            "SPA": [5.0, 7.0, 9.0],
        })
        self.window.set_final_frame(final, "Final clipboard")
        self.window.run_analysis()
        with tempfile.TemporaryDirectory() as folder:
            excel_path = Path(folder) / "result.xlsx"
            image_folder = Path(folder) / "images"
            self.window.export_excel(excel_path)
            images = self.window.save_plot_images(image_folder)

            with pd.ExcelFile(excel_path, engine="openpyxl") as book:
                self.assertEqual(book.sheet_names, [
                    "Summary", "Reference", "Raw Data", "Preview",
                    "Preview FullMap", "Final FullMap",
                ])
            preview = pd.read_excel(excel_path, sheet_name="Preview", engine="openpyxl")
            preview_fullmap = pd.read_excel(
                excel_path, sheet_name="Preview FullMap", engine="openpyxl"
            )
            final_fullmap = pd.read_excel(
                excel_path, sheet_name="Final FullMap", engine="openpyxl"
            )
            self.assertIn("CD_Bot | Evaluated Value", preview.columns)
            self.assertIn("SPA | Bias", preview.columns)
            self.assertEqual(preview_fullmap["CD_Bot"].tolist(), [12, 22, 32])
            pd.testing.assert_frame_equal(final_fullmap, final, check_dtype=False)
            self.assertTrue(images)
            self.assertTrue(all(path.exists() and path.suffix == ".png" for path in images))
    def test_default_registry_exposes_a_multi_instance_matching_tool(self):
        registry = create_default_registry()
        spec = registry.get("card_matching")
        first = registry.create("card_matching")
        second = registry.create("card_matching")
        try:
            self.assertEqual(spec.title, "Card Matching Workbook")
            self.assertIsInstance(first, MatchingWindow)
            self.assertIsNot(first, second)
        finally:
            first.close()
            second.close()
            first.deleteLater()
            second.deleteLater()
            APP.processEvents()


if __name__ == "__main__":
    unittest.main()
