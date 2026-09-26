"""User-visible Card Matching workflow tests."""

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QScrollArea, QSplitter, QTabBar

from metrology_app.matching_window import MatchingWindow
from metrology_app.module_registry import create_default_registry
from metrology_app.sheet import SheetModel, SheetView


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

    def test_reference_and_raw_inputs_are_editable_spreadsheet_grids(self):
        self.assertIsInstance(self.window.reference_model, SheetModel)
        self.assertIsInstance(self.window.raw_model, SheetModel)
        self.assertIsInstance(self.window.reference_view, SheetView)
        self.assertIsInstance(self.window.raw_view, SheetView)
        self.assertGreaterEqual(self.window.reference_model.rowCount(), 100)
        self.assertGreaterEqual(self.window.reference_model.columnCount(), 26)
        self.assertGreaterEqual(self.window.raw_model.rowCount(), 100)
        self.assertGreaterEqual(self.window.raw_model.columnCount(), 26)

        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.reference_model.setData(
            self.window.reference_model.index(1, 1),
            "14.5",
        )
        self.window.raw_model.setData(
            self.window.raw_model.index(1, 1),
            "1.5",
        )

        self.assertEqual(self.window.reference_frame.iloc[0, 1], "14.5")
        self.assertEqual(self.window.raw_frame.iloc[0, 1], "1.5")
        self.assertIsNone(self.window.result)

        self.window.raw_model.undo.undo()
        self.assertEqual(self.window.raw_frame.iloc[0, 1], "1.0")

    def test_reference_is_loaded_before_raw_data_and_enables_analysis(self):
        self.assertFalse(self.window.raw_view.isEnabled())
        self.assertFalse(self.window.analyze_button.isEnabled())

        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.assertTrue(self.window.raw_view.isEnabled())
        self.assertFalse(self.window.analyze_button.isEnabled())

        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.assertEqual(self.window.mapping_table.rowCount(), 2)
        self.assertTrue(self.window.analyze_button.isEnabled())

        result = self.window.run_analysis()
        self.assertEqual(result.parameter_names, ("CD_Bot", "SPA"))
        self.assertEqual(self.window.summary_model.rowCount(), 2)

    def test_analysis_results_share_the_scrollable_setup_workspace(self):
        self.assertEqual(self.window.windowTitle(), "Match Workbook")
        self.assertEqual(self.window.title_label.text(), "Match Workbook")
        self.assertIsInstance(self.window.mode_tabs, QTabBar)
        self.assertEqual(self.window.mode_tabs.count(), 2)
        self.assertEqual(self.window.mode_tabs.tabText(0), "Preview")
        self.assertEqual(self.window.mode_tabs.tabText(1), "Final")
        self.assertFalse(hasattr(self.window, "reference_paste_button"))
        self.assertFalse(hasattr(self.window, "raw_paste_button"))
        self.assertFalse(hasattr(self.window, "fullmap_page"))
        self.assertFalse(self.window.preview_open_button.isHidden())
        self.assertTrue(self.window.final_open_button.isHidden())
        self.assertIsInstance(self.window.setup_scroll, QScrollArea)
        self.assertIsInstance(self.window.setup_splitter, QSplitter)
        self.assertEqual(
            self.window.setup_splitter.orientation(), Qt.Orientation.Vertical
        )
        self.assertTrue(self.window.setup_page.isAncestorOf(self.window.primary_plot_splitter))
        self.assertEqual(self.window.primary_plot_splitter.count(), 4)
        self.assertIsInstance(self.window.plot_scroll, QScrollArea)
        self.assertFalse(hasattr(self.window, "result_plots"))
        self.assertFalse(hasattr(self.window, "linear_fit"))
        self.assertTrue(self.window.absolute_bias.isChecked())
        self.assertFalse(self.window.percent_bias.isChecked())
        self.window.absolute_bias.setChecked(False)
        self.assertTrue(self.window.absolute_bias.isChecked())

        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.percent_bias.setChecked(True)
        self.window.run_analysis()

        headers = [
            self.window.mapping_table.horizontalHeaderItem(column).text()
            for column in range(self.window.mapping_table.columnCount())
        ]
        self.assertEqual(headers, [
            "Use", "Parameter", "Reference column", "Raw Data column",
            "Slope", "Intercept", "R²", "Valid pairs", "Match type", "Result mode",
        ])
        self.assertEqual(self.window.mapping_table.item(0, 7).text(), "3")
        self.assertEqual(self.window.mapping_table.item(0, 8).text(), "KLA")
        self.assertEqual(self.window.mapping_table.item(0, 9).text(), "Preview")
        self.assertIn(
            "Linear fit",
            [item.name() for item in self.window.match_plot.listDataItems()],
        )
        self.assertFalse(self.window.bias_plot.isHidden())
        self.assertFalse(self.window.bias_percent_plot.isHidden())
        self.assertTrue(self.window.bias_plot.listDataItems())
        self.assertTrue(self.window.bias_percent_plot.listDataItems())

        self.window.mode_tabs.setCurrentIndex(1)
        self.assertEqual(self.window.result_mode.currentText(), "Final")
        self.assertTrue(self.window.preview_open_button.isHidden())
        self.assertFalse(self.window.final_open_button.isHidden())

    def test_raw_table_paste_auto_runs_after_first_manual_run(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")

        self.window.analyze_button.click()
        self.assertIsNotNone(self.window.result)

        APP.clipboard().setText(
            "Wafer ID\tCD_Bot\tSPA\nW1\t2\t3\nW2\t3\t4\nW3\t4\t5"
        )
        self.window.raw_view.setCurrentIndex(self.window.raw_model.index(0, 0))
        self.window.raw_view.paste()
        APP.processEvents()

        self.assertIsNotNone(self.window.result)
        self.assertEqual(
            self.window.result.series("CD_Bot")["Raw"].tolist(),
            [2.0, 3.0, 4.0],
        )

    def test_numeric_reference_columns_without_suffix_can_be_mapped_manually(self):
        reference = pd.DataFrame({
            "Wafer ID": ["slot16", "", "slot17"],
            "Die Seq": ["2", "36", "2"],
            "PMISH": ["1.1", "2.1", "3.1"],
            "TEM": ["2.0", "4.0", "6.0"],
            "BIAS": ["0.9", "1.9", "2.9"],
        })
        raw = pd.DataFrame({
            "Cur SME File Path": ["a", "b", "c"],
            "Wafer ID": ["W1", "W1", "W2"],
            "Lot ID": ["L1", "L1", "L1"],
            "Tool SN": ["T1", "T1", "T1"],
            "PAD Name": ["P1", "P1", "P1"],
            "OCD CD": ["1.0", "2.0", "3.0"],
        })

        self.window.set_reference_frame(reference, "Clipboard")
        self.window.set_raw_frame(raw, "Clipboard")

        reference_columns = [
            self.window.mapping_table.item(row, 2).text()
            for row in range(self.window.mapping_table.rowCount())
        ]
        self.assertEqual(reference_columns, ["PMISH", "TEM", "BIAS"])
        self.assertTrue(all(
            self.window.mapping_table.item(row, 0).checkState() == Qt.CheckState.Unchecked
            for row in range(self.window.mapping_table.rowCount())
        ))

        tem_row = reference_columns.index("TEM")
        self.window.mapping_table.cellWidget(tem_row, 3).setCurrentText("OCD CD")
        self.window.mapping_table.item(tem_row, 0).setCheckState(Qt.CheckState.Checked)

        self.assertTrue(self.window.analyze_button.isEnabled())
        result = self.window.run_analysis()
        self.assertEqual(result.parameter_names, ("TEM",))
        self.assertEqual(result.card("TEM").slope, 2.0)

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
        self.assertFalse(self.window.raw_model.cells)
        self.assertGreaterEqual(self.window.raw_model.rowCount(), 100)
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

        self.assertFalse(self.window.single_wafer_panel.isHidden())
        self.assertEqual(self.window.wafer_summary_model.rowCount(), 2)

        self.window.match_type.setCurrentText("TEM")
        self.window.run_analysis()
        self.assertTrue(self.window.single_wafer_panel.isHidden())
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
        self.window.percent_bias.setChecked(True)
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
            names = {path.name for path in images}
            self.assertIn("CD_Bot-bias.png", names)
            self.assertIn("CD_Bot-bias-percent.png", names)
    def test_default_registry_exposes_a_multi_instance_matching_tool(self):
        registry = create_default_registry()
        spec = registry.get("card_matching")
        first = registry.create("card_matching")
        second = registry.create("card_matching")
        try:
            self.assertEqual(spec.title, "Match Workbook")
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
