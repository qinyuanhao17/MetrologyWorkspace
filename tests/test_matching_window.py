"""User-visible Card Matching workflow tests."""

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QApplication, QLabel, QScrollArea, QSplitter, QTabBar, QTabWidget,
)

from metrology_app.matching_window import DataFrameModel, MatchingWindow
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

    def test_keyboard_undo_restores_replaced_reference_and_raw_tables(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.show()

        self.window.raw_view.setCurrentIndex(self.window.raw_model.index(0, 0))
        self.window.raw_view.setFocus()
        APP.clipboard().setText(
            "Wafer ID\tCD_Bot\tSPA\nW1\t101\t201\nW2\t102\t202\nW3\t103\t203"
        )
        QTest.keyClick(
            self.window.raw_view,
            Qt.Key.Key_V,
            Qt.KeyboardModifier.ControlModifier,
        )
        QTest.keyClick(
            self.window.raw_view,
            Qt.Key.Key_Z,
            Qt.KeyboardModifier.ControlModifier,
        )
        self.assertEqual(
            self.window.raw_frame[["CD_Bot", "SPA"]].astype(float).values.tolist(),
            [[1.0, 2.0], [2.0, 3.0], [3.0, 4.0]],
        )

        self.window.reference_view.setCurrentIndex(
            self.window.reference_model.index(0, 0)
        )
        self.window.reference_view.setFocus()
        APP.clipboard().setText(
            "Wafer ID\tCD_Bot Reference\tSPA Reference\n"
            "W1\t112\t205\nW2\t122\t207\nW3\t132\t209"
        )
        QTest.keyClick(
            self.window.reference_view,
            Qt.Key.Key_V,
            Qt.KeyboardModifier.ControlModifier,
        )
        QTest.keyClick(
            self.window.reference_view,
            Qt.Key.Key_Z,
            Qt.KeyboardModifier.ControlModifier,
        )
        self.assertEqual(
            self.window.reference_frame[
                ["CD_Bot Reference", "SPA Reference"]
            ].astype(float).values.tolist(),
            [[12.0, 5.0], [22.0, 7.0], [32.0, 9.0]],
        )
        self.assertEqual(self.window.mapping_table.rowCount(), 2)

    def test_keyboard_undo_restores_deleted_reference_and_raw_tables(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.show()

        for view, frame_name in (
            (self.window.raw_view, "raw_frame"),
            (self.window.reference_view, "reference_frame"),
        ):
            view.setFocus()
            QTest.keyClick(
                view,
                Qt.Key.Key_A,
                Qt.KeyboardModifier.ControlModifier,
            )
            QTest.keyClick(view, Qt.Key.Key_Delete)
            self.assertTrue(getattr(self.window, frame_name).empty)
            QTest.keyClick(
                view,
                Qt.Key.Key_Z,
                Qt.KeyboardModifier.ControlModifier,
            )
            self.assertFalse(getattr(self.window, frame_name).empty)

        self.assertEqual(self.window.mapping_table.rowCount(), 2)

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

    def test_select_all_mappings_checks_every_candidate(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")

        self.assertFalse(self.window.select_all_mappings.isChecked())
        self.window.select_all_mappings.click()

        self.assertTrue(all(
            self.window.mapping_table.item(row, 0).checkState()
            == Qt.CheckState.Checked
            for row in range(self.window.mapping_table.rowCount())
        ))
        self.assertTrue(self.window.select_all_mappings.isChecked())

    def test_clearing_raw_data_keeps_mappings_and_prompts_for_columns(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.show()
        self.window.raw_view.setFocus()
        QTest.keyClick(
            self.window.raw_view,
            Qt.Key.Key_A,
            Qt.KeyboardModifier.ControlModifier,
        )
        QTest.keyClick(self.window.raw_view, Qt.Key.Key_Delete)

        self.assertTrue(self.window.raw_frame.empty)
        self.assertEqual(self.window.mapping_table.rowCount(), 2)
        self.assertTrue(all(
            self.window.mapping_table.item(row, 0).checkState()
            == Qt.CheckState.Checked
            for row in range(self.window.mapping_table.rowCount())
        ))

        self.window.raw_view.setCurrentIndex(self.window.raw_model.index(0, 0))
        APP.clipboard().setText(
            "Wafer ID\tDifferent\nW1\t1\nW2\t2\nW3\t3"
        )
        QTest.keyClick(
            self.window.raw_view,
            Qt.Key.Key_V,
            Qt.KeyboardModifier.ControlModifier,
        )

        self.assertTrue(all(
            self.window.mapping_table.item(row, 0).checkState()
            == Qt.CheckState.Checked
            for row in range(self.window.mapping_table.rowCount())
        ))
        self.assertTrue(all(
            not self.window.mapping_table.cellWidget(row, 3).currentText()
            for row in range(self.window.mapping_table.rowCount())
        ))
        self.assertIn("Choose a Raw Data column", self.window.status.text())
        self.assertEqual(self.window.status.objectName(), "warning")
        self.assertTrue(self.window.status.wordWrap())
        self.assertFalse(self.window.analyze_button.isEnabled())

    def test_analysis_results_share_the_scrollable_setup_workspace(self):
        self.assertEqual(self.window.windowTitle(), "Match Workbook")
        self.assertFalse(any(
            label.text() == "Match Workbook"
            for label in self.window.findChildren(QLabel)
        ))
        self.assertEqual(
            [action.text() for action in self.window.menuBar().actions()],
            ["File", "Analysis", "View"],
        )
        self.assertEqual(
            [action.text() for action in self.window.file_menu.actions()],
            ["Open WKB", "Save WKB", "Export Excel", "Save images"],
        )
        self.assertEqual(
            [action.text() for action in self.window.match_type_menu.actions()],
            ["KLA", "NOVA", "TEM"],
        )
        self.assertEqual(
            [action.text() for action in self.window.bias_menu.actions()],
            ["Bias", "Bias %"],
        )
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
        self.assertFalse(hasattr(self.window, "parameter_picker"))
        self.assertFalse(hasattr(self.window, "primary_plot_splitter"))
        self.assertFalse(hasattr(self.window, "plot_scroll"))
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
        self.assertEqual(tuple(self.window.plot_groups), ("CD_Bot", "SPA"))
        cd_plots = self.window.plot_groups["CD_Bot"]["plots"]
        spa_plots = self.window.plot_groups["SPA"]["plots"]
        self.assertEqual(
            tuple(cd_plots), ("match", "trend", "bias", "bias-percent")
        )
        self.assertIn(
            "Linear fit",
            [item.name() for item in cd_plots["match"].listDataItems()],
        )
        self.assertTrue(all(plot.minimumHeight() >= 280 for plot in cd_plots.values()))
        self.assertTrue(cd_plots["bias"].listDataItems())
        self.assertTrue(cd_plots["bias-percent"].listDataItems())
        self.assertTrue(spa_plots["match"].listDataItems())

        self.window.resize(1600, 900)
        self.window.show()
        APP.processEvents()
        self.assertGreater(self.window.setup_scroll.verticalScrollBar().maximum(), 0)
        first_card = self.window.plot_groups["CD_Bot"]["card"]
        second_card = self.window.plot_groups["SPA"]["card"]
        self.assertLessEqual(first_card.geometry().bottom(), second_card.geometry().top())
        self.assertTrue(
            cd_plots["match"].geometry().intersected(
                cd_plots["trend"].geometry()
            ).isEmpty()
        )
        self.assertTrue(
            cd_plots["match"].geometry().intersected(
                cd_plots["bias"].geometry()
            ).isEmpty()
        )
        self.assertEqual(
            {plot.geometry().top() for plot in cd_plots.values()},
            {cd_plots["match"].geometry().top()},
        )
        plot_container_rect = cd_plots["match"].parentWidget().contentsRect()
        self.assertTrue(all(
            plot_container_rect.contains(plot.geometry())
            for plot in cd_plots.values()
        ))

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

    def test_raw_mapping_change_auto_runs_and_preserves_layout(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window._run_analysis_clicked()
        self.window.resize(1600, 900)
        self.window.show()
        APP.processEvents()
        self.window.setup_splitter.setSizes([500, 260, 900])
        APP.processEvents()
        sizes = tuple(self.window.setup_splitter.sizes()[:2])

        self.window.mapping_table.cellWidget(0, 3).setCurrentText("SPA")
        APP.processEvents()

        self.assertIsNotNone(self.window.result)
        self.assertEqual(
            self.window.result.summary.loc[0, "Raw column"],
            "SPA",
        )
        self.assertEqual(tuple(self.window.setup_splitter.sizes()[:2]), sizes)

    def test_selected_primary_plots_share_one_horizontal_row(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()
        self.window.resize(1600, 900)
        self.window.show()
        APP.processEvents()

        plots = self.window.plot_groups["CD_Bot"]["plots"]
        self.assertEqual(tuple(plots), ("match", "trend", "bias"))
        self.assertEqual(
            {plots[name].geometry().top() for name in plots},
            {plots["match"].geometry().top()},
        )
        self.assertLess(plots["match"].geometry().right(), plots["trend"].geometry().left())
        self.assertLess(plots["trend"].geometry().right(), plots["bias"].geometry().left())
        self.assertLess(plots["match"].width(), plots["trend"].width())
        self.assertLess(plots["match"].width(), plots["bias"].width())

    def test_match_plot_uses_raw_column_title_and_shows_fit_equation(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()

        match = self.window.plot_groups["CD_Bot"]["plots"]["match"].getPlotItem()
        self.assertEqual(match.titleLabel.text, "CD_Bot")
        annotations = [item for item in match.items if isinstance(item, pg.TextItem)]
        self.assertEqual(len(annotations), 1)
        self.assertEqual(
            annotations[0].toPlainText(),
            "y = 10x + 2\nR² = 1",
        )

    def test_mapping_results_flag_out_of_range_slope_and_r_squared(self):
        reference = pd.DataFrame({
            "Slope Reference": [2.0, 4.0, 6.0, 8.0],
            "RSQ Reference": [2.0, 1.0, 2.0, 5.0],
        })
        raw = pd.DataFrame({
            "Slope": [1.0, 2.0, 3.0, 4.0],
            "RSQ": [1.0, 2.0, 3.0, 4.0],
        })
        self.window.set_reference_frame(reference, "Clipboard")
        self.window.set_raw_frame(raw, "Clipboard")
        self.window.run_analysis()

        slope_bad = self.window.mapping_table.item(0, 4)
        r_squared_good = self.window.mapping_table.item(0, 6)
        slope_good = self.window.mapping_table.item(1, 4)
        r_squared_bad = self.window.mapping_table.item(1, 6)

        self.assertNotEqual(
            slope_bad.background().style(), Qt.BrushStyle.NoBrush
        )
        self.assertIn("0.9–1.1", slope_bad.toolTip())
        self.assertEqual(
            r_squared_good.background().style(), Qt.BrushStyle.NoBrush
        )
        self.assertEqual(
            slope_good.background().style(), Qt.BrushStyle.NoBrush
        )
        self.assertNotEqual(
            r_squared_bad.background().style(), Qt.BrushStyle.NoBrush
        )
        self.assertIn("below 0.9", r_squared_bad.toolTip())

    def test_single_wafer_table_flags_the_same_quality_thresholds(self):
        model = DataFrameModel(pd.DataFrame({
            "Slope": [0.89, 1.0],
            "R²": [0.95, 0.89],
        }))

        self.assertIsNotNone(model.data(model.index(0, 0), Qt.ItemDataRole.BackgroundRole))
        self.assertIsNone(model.data(model.index(1, 0), Qt.ItemDataRole.BackgroundRole))
        self.assertIsNone(model.data(model.index(0, 1), Qt.ItemDataRole.BackgroundRole))
        self.assertIsNotNone(model.data(model.index(1, 1), Qt.ItemDataRole.BackgroundRole))

    def test_trend_and_bias_use_visible_point_lines(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.match_type.setCurrentText("TEM")
        self.window.percent_bias.setChecked(True)
        self.window.run_analysis()

        plots = self.window.plot_groups["CD_Bot"]["plots"]
        trend_items = {
            item.name(): item for item in plots["trend"].listDataItems()
        }
        self.assertEqual(set(trend_items), {"PMISH", "TEM"})
        self.assertEqual(
            trend_items["TEM"].opts["pen"].color().name(),
            "#ed7d31",
        )
        self.assertEqual(
            trend_items["PMISH"].opts["pen"].color().name(),
            "#5b9bd5",
        )
        for item in trend_items.values():
            self.assertEqual(item.opts["pen"].style(), Qt.PenStyle.SolidLine)
            self.assertGreaterEqual(item.opts["pen"].widthF(), 2.0)
            self.assertEqual(item.opts["symbol"], "o")

        bias_item = plots["bias"].listDataItems()[0]
        self.assertEqual(bias_item.opts["symbol"], "o")
        bias_percent_item = plots["bias-percent"].listDataItems()[0]
        self.assertEqual(bias_percent_item.opts["symbol"], "o")
        self.assertEqual(plots["match"].getAxis("bottom").labelText, "PMISH")
        self.assertEqual(plots["match"].getAxis("left").labelText, "TEM")
        self.assertEqual(plots["trend"].getAxis("left").labelText, "")
        self.assertEqual(plots["bias"].getAxis("left").labelText, "Bias (nm)")
        self.assertEqual(
            plots["bias-percent"].getAxis("left").labelText,
            "Bias (%)",
        )
        self.assertFalse(plots["bias"].getAxis("left").autoSIPrefix)
        self.assertFalse(plots["bias-percent"].getAxis("left").autoSIPrefix)
        self.assertEqual(
            plots["trend"].getAxis("bottom")._tickLevels,
            [[(1.0, "W1"), (2.0, "W2"), (3.0, "W3")]],
        )

    def test_run_analysis_preserves_the_setup_scroll_position(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.resize(1600, 900)
        self.window.show()
        APP.processEvents()
        scroll_bar = self.window.setup_scroll.verticalScrollBar()
        scroll_bar.setValue(0)

        self.window.analyze_button.click()
        APP.processEvents()

        self.assertEqual(scroll_bar.value(), 0)

    def test_run_analysis_preserves_the_dragged_setup_splitter_layout(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.resize(1600, 900)
        self.window.show()
        APP.processEvents()
        self.window.setup_splitter.setSizes([520, 280, 760])
        APP.processEvents()
        dragged_sizes = self.window.setup_splitter.sizes()

        self.window.run_analysis()
        APP.processEvents()

        self.assertEqual(
            self.window.setup_splitter.sizes()[:2],
            dragged_sizes[:2],
        )

    def test_wkb_restores_the_saved_setup_splitter_layout(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()
        self.window.resize(1600, 900)
        self.window.show()
        APP.processEvents()
        self.window.setup_splitter.setSizes([320, 520, 1600])
        APP.processEvents()
        saved_sizes = tuple(self.window.setup_splitter.sizes())

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "layout.wkb"
            self.window.save_workbook(path)
            reopened = MatchingWindow()
            try:
                reopened.resize(1600, 900)
                reopened.show()
                APP.processEvents()
                reopened.load_workbook(path)
                APP.processEvents()
                self.assertEqual(
                    tuple(reopened.setup_splitter.sizes()[:2]),
                    saved_sizes[:2],
                )
            finally:
                reopened.close()
                reopened.deleteLater()
                APP.processEvents()

    def test_parameter_plot_order_survives_run_and_wkb_until_reset(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window.run_analysis()

        card = self.window.plot_groups["CD_Bot"]["card"]
        self.assertTrue(card.acceptDrops())
        self.assertIsNotNone(card.findChild(QLabel, "parameterDragHandle"))
        self.window.move_parameter("SPA", "CD_Bot", before=True)

        self.assertEqual(self.window.parameter_order(), ("SPA", "CD_Bot"))
        self.window.run_analysis()
        self.assertEqual(self.window.parameter_order(), ("SPA", "CD_Bot"))

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "order.wkb"
            self.window.save_workbook(path)
            reopened = MatchingWindow()
            try:
                reopened.load_workbook(path)
                self.assertEqual(reopened.parameter_order(), ("SPA", "CD_Bot"))
                reopened.reset_order_button.click()
                self.assertEqual(
                    reopened.parameter_order(),
                    ("CD_Bot", "SPA"),
                )
            finally:
                reopened.close()
                reopened.deleteLater()
                APP.processEvents()

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

        self.assertIsNotNone(self.window.workbook)
        self.assertIsNotNone(self.window.result)
        self.assertIn("SPA", self.window.plot_groups)
        self.assertTrue(
            self.window.plot_groups["SPA"]["plots"]["trend"].listDataItems()
        )

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

    def test_switching_preview_and_final_keeps_results_and_layout(self):
        self.window.set_reference_frame(self.reference(), "Clipboard")
        self.window.set_raw_frame(self.raw(), "Clipboard")
        self.window._run_analysis_clicked()
        self.window.resize(1600, 900)
        self.window.show()
        APP.processEvents()
        self.window.setup_splitter.setSizes([480, 260, 900])
        APP.processEvents()
        sizes = tuple(self.window.setup_splitter.sizes()[:2])
        self.assertTrue(self.window.export_button.isEnabled())

        self.window.result_mode.setCurrentText("Final")
        APP.processEvents()

        self.assertIsNotNone(self.window.result)
        self.assertEqual(self.window.result.result_mode, "final")
        self.assertTrue(self.window.export_button.isEnabled())
        self.assertEqual(self.window.summary_model.rowCount(), 2)
        self.assertEqual(tuple(self.window.setup_splitter.sizes()[:2]), sizes)
        self.assertFalse(self.window.reference_card.isHidden())
        self.assertTrue(self.window.raw_card.isHidden())
        self.assertFalse(self.window.mapping_card.isHidden())

        self.window.result_mode.setCurrentText("Preview")
        APP.processEvents()

        self.assertIsNotNone(self.window.result)
        self.assertEqual(self.window.result.result_mode, "preview")
        self.assertFalse(self.window.raw_card.isHidden())
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

        self.assertIsInstance(self.window.results_tabs, QTabWidget)
        self.assertEqual(self.window.results_tabs.count(), 2)
        self.assertEqual(self.window.results_tabs.tabText(0), "All parameter plots")
        self.assertEqual(self.window.results_tabs.tabText(1), "Single-wafer metrics")
        group = self.window.plot_groups["CD"]
        self.assertFalse(group["wafer_card"].isHidden())
        self.assertEqual(group["wafer_model"].rowCount(), 2)

        self.window.match_type.setCurrentText("TEM")
        self.window.run_analysis()
        self.assertTrue(self.window.plot_groups["CD"]["wafer_card"].isHidden())
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
