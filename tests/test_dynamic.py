"""Dynamic repeatability analysis regression tests."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import QItemSelectionModel, QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QLabel, QPushButton, QScrollArea,
)

from metrology_app.dynamic import dynamic_pivot, prepare_dynamic_frame
from metrology_app.dynamic import cycle_trend, selected_measurement_rows
from metrology_app.dynamic_trend import DIE_SYMBOLS
from metrology_app.dynamic_window import DynamicWindow
from metrology_app.plotting import InteractivePlotWidget


APP = QApplication.instance() or QApplication([])


class DynamicDataTests(unittest.TestCase):
    def test_empty_new_table_stays_editable_until_dynamic_rows_are_pasted(self):
        prepared = prepare_dynamic_frame(pd.DataFrame())
        self.assertTrue(prepared.empty)
        self.assertEqual(prepared.columns.tolist(), [])

    def test_cycle_is_inferred_from_dynamic_run_folder_and_report_tail_is_removed(self):
        rows = []
        for cycle in range(1, 4):
            for die in range(1, 5):
                rows.append({
                    "Cur SME File Path": rf"C:\data\DYNAMIC\run-{cycle}\die-{die}.csv",
                    "Wafer ID": "W1",
                    "Die Seq": die,
                    "DP": cycle * 10 + die,
                    "Unnamed: 4": np.nan,
                    "数据透视表": "old report",
                })

        prepared = prepare_dynamic_frame(pd.DataFrame(rows))

        self.assertEqual(
            prepared.columns.tolist(),
            ["Cur SME File Path", "Wafer ID", "Die Seq", "Cycle", "DP"],
        )
        self.assertEqual(
            prepared["Cycle"].tolist(),
            [1] * 4 + [2] * 4 + [3] * 4,
        )

    def test_cycle_fallback_handles_variable_die_and_cycle_counts(self):
        frame = pd.DataFrame({
            "Die Seq": [1, 2, 3, 1, 2, 3, 1, 2, 3],
            "DP": range(9),
        })

        prepared = prepare_dynamic_frame(frame)

        self.assertEqual(prepared["Cycle"].tolist(), [1] * 3 + [2] * 3 + [3] * 3)

    def test_pivot_has_cycles_by_die_and_sample_three_sigma_bottom_row(self):
        frame = pd.DataFrame({
            "Cycle": [1, 1, 2, 2, 3, 3],
            "Die Seq": [1, 2, 1, 2, 1, 2],
            "DP": [10.0, 20.0, 11.0, 22.0, 12.0, 24.0],
        })

        pivot = dynamic_pivot(frame, "DP")

        self.assertEqual(pivot.index.tolist(), [1, 2, 3, "3 Sigma"])
        self.assertEqual(pivot.columns.tolist(), [1, 2])
        self.assertEqual(pivot.loc[2, 1], 11.0)
        self.assertAlmostEqual(pivot.loc["3 Sigma", 1], 3.0)
        self.assertAlmostEqual(pivot.loc["3 Sigma", 2], 6.0)

    def test_duplicate_cycle_and_die_is_rejected_instead_of_silently_averaged(self):
        frame = pd.DataFrame({
            "Cycle": [1, 1],
            "Die Seq": [1, 1],
            "DP": [10.0, 11.0],
        })

        with self.assertRaisesRegex(ValueError, "duplicate Cycle / Die Seq"):
            dynamic_pivot(frame, "DP")

    def test_cycle_trend_keeps_measurements_without_the_derived_row(self):
        frame = pd.DataFrame({
            "Cycle": [1, 1, 2, 2],
            "Die Seq": [1, 2, 1, 2],
            "DP": [10.0, 20.0, 11.0, 22.0],
        })

        trend = cycle_trend(frame, "DP")

        self.assertEqual(trend.index.tolist(), [1, 2])
        self.assertEqual(trend.columns.tolist(), [1, 2])
        self.assertEqual(trend.loc[2, 2], 22.0)

    def test_selected_measurement_rows_keep_their_data_positions(self):
        frame = pd.DataFrame({
            "Wafer ID": ["W1", "W2", "W1"],
            "DP": [1.0, 2.0, 3.0],
        })
        selection = {"wafers": ["w1"], "groups": {"w1": (0, 2)}}

        rows = selected_measurement_rows(frame, selection)

        self.assertEqual(list(rows.index), [0, 2])
        self.assertEqual(rows["DP"].tolist(), [1.0, 3.0])

    def test_die_symbols_are_supported_by_both_render_backends(self):
        """A symbol pyqtgraph does not know would break the whole Trend tab."""
        from matplotlib.markers import MarkerStyle
        from pyqtgraph.graphicsItems.ScatterPlotItem import Symbols

        for qt_symbol, marker in DIE_SYMBOLS:
            with self.subTest(symbol=qt_symbol):
                self.assertIn(qt_symbol, Symbols)
                MarkerStyle(marker)


class DynamicWindowTests(unittest.TestCase):
    def setUp(self):
        self.window = DynamicWindow()

    def tearDown(self):
        self.window.model.undo.setClean()
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    @staticmethod
    def frame():
        rows = []
        for cycle in range(1, 4):
            for die in range(1, 5):
                rows.append({
                    "Cur SME File Path": rf"C:\data\DYNAMIC\run-{cycle}\die-{die}.csv",
                    "Wafer ID": "W1",
                    "Lot ID": "L1",
                    "PAD Name": "P1",
                    "Die Seq": die,
                    "DP": cycle * 10 + die,
                    "EW": cycle * 100 + die,
                    "TG": cycle * 1000 + die,
                    "UC": cycle * 10000 + die,
                    "WTH": cycle * 100000 + die,
                })
        return pd.DataFrame(rows)

    def test_selected_parameters_render_separate_vertical_table_and_plot_sections(self):
        self.window.set_table(self.frame(), "dynamic.csv")
        self.assertEqual(
            [self.window.tabs.tabText(i) for i in range(self.window.tabs.count())],
            ["1. Data", "2. Dynamic", "3. Trend"],
        )
        cycle_items = [
            self.window.parameter_list.topLevelItem(i)
            for i in range(self.window.parameter_list.topLevelItemCount())
            if self.window.parameter_list.topLevelItem(i).text(0) == "Cycle"
        ]
        self.assertEqual(len(cycle_items), 1)
        self.assertFalse(
            bool(cycle_items[0].flags() & Qt.ItemFlag.ItemIsUserCheckable)
        )

        for index in range(self.window.parameter_list.topLevelItemCount()):
            item = self.window.parameter_list.topLevelItem(index)
            if item.text(0) in {"DP", "EW"}:
                item.setCheckState(0, Qt.CheckState.Checked)
        APP.processEvents()

        page = self.window.dynamic_page
        self.assertNotIn(
            "Dynamic repeatability",
            [label.text() for label in page.findChildren(QLabel)],
        )
        self.assertEqual(
            page.findChildren(QComboBox, "dynamicParameter"), []
        )
        self.assertEqual(list(page.parameter_models), ["DP", "EW"])
        for parameter in ("DP", "EW"):
            model = page.parameter_models[parameter]
            self.assertEqual(model.frame.index.tolist(), [1, 2, 3, "3 Sigma"])
            self.assertEqual(model.frame.columns.tolist(), ["1", "2", "3", "4"])
            self.assertEqual(
                model.headerData(0, Qt.Orientation.Horizontal), "Die 1"
            )
        self.assertEqual(list(page.parameter_tables), ["DP", "EW"])
        self.assertEqual(
            [section.property("parameter") for section in page.parameter_sections],
            ["DP", "EW"],
        )
        self.assertEqual(
            [plot.getPlotItem().titleLabel.text for plot in page.plots],
            ["", "DP", "EW"],
        )
        legend = page.comparison_legend
        self.assertIsNotNone(legend)
        self.assertEqual(legend.columnCount, 2)
        self.assertEqual(legend.rowCount, 1)
        self.assertEqual(
            [label.text for _sample, label in legend.items],
            ["DP", "EW"],
        )
        self.assertTrue(all(
            sample.boundingRect().width() <= 10
            and sample.boundingRect().height() <= 10
            for sample, _label in legend.items
        ))
        self.assertEqual(
            [(plot.width(), plot.height()) for plot in page.plots],
            [(420, 270), (420, 270), (420, 270)],
        )
        self.assertEqual(len(page.bar_items), 4)
        for plot in page.plots:
            self.assertIsInstance(plot, InteractivePlotWidget)
            self.assertTrue(all(
                isinstance(item, pg.BarGraphItem)
                for item in plot.listDataItems()
            ))
            sigma_axis = plot.getAxis("left")
            self.assertEqual(sigma_axis.labelText, "3 Sigma (nm)")
            self.assertFalse(sigma_axis.autoSIPrefix)
        self.window.tabs.setCurrentIndex(1)
        self.window.resize(1100, 800)
        self.window.show()
        APP.processEvents()
        self.assertIsInstance(page.table_scroll, QScrollArea)
        self.assertIsInstance(page.plot_scroll, QScrollArea)
        self.assertIsNot(page.table_scroll, page.plot_scroll)
        self.assertEqual(
            page.table_scroll.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self.assertEqual(
            page.table_scroll.verticalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        )
        self.assertEqual(
            page.plot_scroll.verticalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        )
        for table in page.parameter_tables.values():
            self.assertEqual(table.verticalHeader().defaultSectionSize(), 28)
            self.assertTrue(page.table_host.isAncestorOf(table))
        for plot in page.plots:
            self.assertTrue(page.plot_host.isAncestorOf(plot))

    def test_more_than_three_parameter_charts_wrap_to_the_next_row(self):
        self.window.set_table(self.frame(), "dynamic.csv")
        parameters = {"DP", "EW", "TG", "UC", "WTH"}
        for index in range(self.window.parameter_list.topLevelItemCount()):
            item = self.window.parameter_list.topLevelItem(index)
            if item.text(0) in parameters:
                item.setCheckState(0, Qt.CheckState.Checked)

        self.window.tabs.setCurrentIndex(1)
        self.window.resize(1500, 900)
        self.window.show()
        APP.processEvents()

        page = self.window.dynamic_page
        self.assertEqual(
            [plot.getPlotItem().titleLabel.text for plot in page.plots],
            ["", "DP", "EW", "TG", "UC", "WTH"],
        )
        self.assertEqual(page.comparison_legend.columnCount, 5)
        self.assertEqual(page.comparison_legend.rowCount, 1)
        positions = [plot.mapTo(page.plot_host, QPoint(0, 0)) for plot in page.plots]
        self.assertEqual([point.y() for point in positions[:3]], [positions[0].y()] * 3)
        self.assertLess(positions[0].x(), positions[1].x())
        self.assertLess(positions[1].x(), positions[2].x())
        self.assertEqual([point.y() for point in positions[3:]], [positions[3].y()] * 3)
        self.assertGreater(positions[3].y(), positions[0].y())
        self.assertEqual(positions[3].x(), positions[0].x())
        self.assertEqual(positions[4].x(), positions[1].x())
        self.assertEqual(positions[5].x(), positions[2].x())
        self.assertTrue(all(
            all(isinstance(item, pg.BarGraphItem) for item in plot.listDataItems())
            for plot in page.plots
        ))
        self.assertGreater(page.plot_scroll.verticalScrollBar().maximum(), 0)

    def test_replacing_dynamic_data_keeps_available_parameters_and_refreshes_plots(self):
        self.window.set_table(self.frame(), "first-dynamic.csv")
        for index in range(self.window.parameter_list.topLevelItemCount()):
            item = self.window.parameter_list.topLevelItem(index)
            if item.text(0) in {"DP", "EW"}:
                item.setCheckState(0, Qt.CheckState.Checked)
        first_sigma = float(
            self.window.dynamic_page.parameter_models["DP"].frame.loc[
                "3 Sigma", "1"
            ]
        )

        replacement = self.frame()
        replacement["DP"] = replacement["DP"] * 2
        self.window.set_table(replacement, "replacement-dynamic.csv")

        self.assertEqual(self.window.selection["metrics"], ["DP", "EW"])
        self.assertEqual(
            list(self.window.dynamic_page.parameter_models), ["DP", "EW"]
        )
        self.assertAlmostEqual(
            float(
                self.window.dynamic_page.parameter_models["DP"].frame.loc[
                    "3 Sigma", "1"
                ]
            ),
            first_sigma * 2,
        )

    def test_new_table_does_not_require_die_seq_before_data_is_pasted(self):
        self.window.set_table(pd.DataFrame(), "Untitled")
        self.assertEqual(self.window.model.frame().shape, (0, 0))

    def select_parameters(self, *names):
        tree = self.window.parameter_list
        tree.blockSignals(True)
        for index in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(index)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked if item.text(0) in names
                    else Qt.CheckState.Unchecked,
                )
        tree.blockSignals(False)
        self.window.update_plan()
        APP.processEvents()

    def wait_for_dynamic_refresh(self):
        QTest.qWait(400)
        APP.processEvents()

    @staticmethod
    def select_cell(table, model, row, column):
        """Click-equivalent: make one pivot cell current and selected."""
        index = model.index(row, column)
        table.setCurrentIndex(index)
        table.selectionModel().select(
            index, QItemSelectionModel.SelectionFlag.ClearAndSelect
        )
        return index

    def test_deleting_a_pivot_cell_edits_the_data_sheet_and_recomputes_sigma(self):
        """Delete on a pivot cell drops that measurement point for good."""
        self.window.set_table(self.frame(), "dynamic.csv")
        self.select_parameters("DP")
        page = self.window.dynamic_page
        model = page.parameter_models["DP"]
        table = page.parameter_tables["DP"]

        self.assertTrue(
            bool(model.flags(model.index(0, 0)) & Qt.ItemFlag.ItemIsEditable)
        )
        self.assertFalse(
            bool(model.flags(model.index(3, 0)) & Qt.ItemFlag.ItemIsEditable)
        )

        self.select_cell(table, model, 0, 0)
        QTest.keyClick(table, Qt.Key.Key_Delete)
        self.wait_for_dynamic_refresh()

        column = self.window.model.frame().columns.get_loc("DP")
        self.assertEqual(
            self.window.model.cells.get((1, column), ""), ""
        )
        refreshed = page.parameter_models["DP"].frame
        self.assertTrue(pd.isna(refreshed.loc[1, "1"]))
        self.assertAlmostEqual(
            float(refreshed.loc["3 Sigma", "1"]),
            3 * np.std([21.0, 31.0], ddof=1),
        )

    def test_restore_returns_the_pivot_to_the_loaded_values(self):
        self.window.set_table(self.frame(), "dynamic.csv")
        self.select_parameters("DP")
        page = self.window.dynamic_page
        page.parameter_models["DP"].edit({(0, 0): "", (0, 1): ""})
        self.wait_for_dynamic_refresh()
        self.assertTrue(pd.isna(page.parameter_models["DP"].frame.loc[1, "1"]))

        self.assertTrue(page.restore_parameter("DP"))
        self.wait_for_dynamic_refresh()

        restored = page.parameter_models["DP"].frame
        self.assertAlmostEqual(float(restored.loc[1, "1"]), 11.0)
        self.assertAlmostEqual(float(restored.loc[1, "2"]), 12.0)
        self.assertAlmostEqual(float(restored.loc["3 Sigma", "1"]), 30.0)

    def test_ctrl_z_undoes_one_step_at_a_time(self):
        """Ctrl+Z is single-step; Restore is the whole-table reset."""
        self.window.set_table(self.frame(), "dynamic.csv")
        self.select_parameters("DP")
        page = self.window.dynamic_page
        model = page.parameter_models["DP"]
        self.select_cell(page.parameter_tables["DP"], model, 0, 0)
        QTest.keyClick(page.parameter_tables["DP"], Qt.Key.Key_Delete)
        self.wait_for_dynamic_refresh()
        model = page.parameter_models["DP"]
        self.select_cell(page.parameter_tables["DP"], model, 0, 1)
        QTest.keyClick(page.parameter_tables["DP"], Qt.Key.Key_Delete)
        self.wait_for_dynamic_refresh()

        QTest.keyClick(
            page.parameter_tables["DP"], Qt.Key.Key_Z,
            Qt.KeyboardModifier.ControlModifier,
        )
        self.wait_for_dynamic_refresh()

        frame = page.parameter_models["DP"].frame
        self.assertTrue(pd.isna(frame.loc[1, "1"]))
        self.assertAlmostEqual(float(frame.loc[1, "2"]), 12.0)

    def test_value_edit_and_undo_keep_dynamic_views_and_unrelated_curves(self):
        self.window.set_table(self.frame(), "dynamic.csv")
        self.select_parameters("DP", "EW")
        page, trend = self.window.dynamic_page, self.window.dynamic_trend
        tables = dict(page.parameter_tables)
        models = dict(page.parameter_models)
        bars = list(page.bar_items)
        plots = list(page.plots)
        trend_plots = dict(trend.panel_widgets)
        picker = trend.die_pickers["EW"]
        picker.setCurrentIndex(1)
        ew_curve = trend.panel_widgets["EW"].listDataItems()[0]
        ew_values = ew_curve.getData()[1].copy()
        zoom = plots[-1].getViewBox()
        zoom.setRange(xRange=(1, 3), yRange=(20, 40), padding=0)
        previous_zoom = zoom.viewRange()
        self.select_cell(tables["DP"], models["DP"], 0, 0)

        for operation in ("edit", "undo", "redo"):
            with self.subTest(operation=operation):
                if operation == "edit":
                    models["DP"].edit({(0, 0): "14"})
                elif operation == "undo":
                    QTest.keyClick(tables["DP"], Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
                else:
                    self.window.model.undo.redo()
                self.wait_for_dynamic_refresh()
                expected = 11.0 if operation == "undo" else 14.0
                self.assertEqual(page.parameter_tables, tables)
                self.assertEqual(page.parameter_models, models)
                self.assertEqual(page.plots, plots)
                self.assertEqual(page.bar_items, bars)
                self.assertEqual(trend.panel_widgets, trend_plots)
                self.assertIs(trend.die_pickers["EW"], picker)
                self.assertEqual(picker.currentText(), "Die 2")
                self.assertIs(trend.panel_widgets["EW"].listDataItems()[0], ew_curve)
                np.testing.assert_array_equal(ew_curve.getData()[1], ew_values)
                self.assertEqual(zoom.viewRange(), previous_zoom)
                self.assertEqual(tables["DP"].currentIndex().row(), 0)
                self.assertAlmostEqual(models["DP"].frame.loc[1, "1"], expected)
                sigma = 25.632011235952593 if operation != "undo" else 30.0
                self.assertAlmostEqual(models["DP"].frame.loc["3 Sigma", "1"], sigma)
                self.assertAlmostEqual(bars[0].opts["height"][0], sigma)
                self.assertAlmostEqual(bars[2].opts["height"][0], sigma)
                self.assertAlmostEqual(trend.panel_widgets["DP"].listDataItems()[0].getData()[1][0], expected)

    def test_pivot_paste_writes_the_value_into_the_data_sheet(self):
        self.window.set_table(self.frame(), "dynamic.csv")
        self.select_parameters("DP")
        page = self.window.dynamic_page
        model = page.parameter_models["DP"]
        table = page.parameter_tables["DP"]
        self.select_cell(table, model, 0, 0)
        APP.clipboard().setText("99.5")

        QTest.keyClick(table, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        self.wait_for_dynamic_refresh()

        column = self.window.model.frame().columns.get_loc("DP")
        self.assertEqual(self.window.model.cells.get((1, column)), "99.5")
        self.assertAlmostEqual(
            float(page.parameter_models["DP"].frame.loc[1, "1"]), 99.5
        )

    def test_partial_dynamic_update_preserves_sparse_die_positions(self):
        frame = self.frame()
        frame.loc[frame["Die Seq"] == 2, "DP"] = np.nan
        self.window.set_table(frame, "sparse.csv")
        self.select_parameters("DP", "EW")
        page = self.window.dynamic_page
        before_x = page.bar_items[0].opts["x"].copy()
        page.parameter_models["DP"].edit({(0, 1): "50"})
        self.wait_for_dynamic_refresh()
        np.testing.assert_array_equal(page.bar_items[0].opts["x"], before_x)
        np.testing.assert_array_equal(page.bar_items[2].opts["x"], [1, 2, 3])

    def test_data_sheet_range_edit_updates_each_affected_parameter_and_undo(self):
        self.window.set_table(self.frame(), "dynamic.csv")
        self.select_parameters("DP", "EW", "TG")
        page = self.window.dynamic_page
        tables = dict(page.parameter_tables)
        columns = self.window.model.frame().columns
        self.window.model.edit({(1, columns.get_loc("DP")): "14",
                                (1, columns.get_loc("EW")): "131"})
        self.wait_for_dynamic_refresh()
        self.assertEqual(page.parameter_tables, tables)
        self.assertAlmostEqual(page.parameter_models["DP"].frame.loc["3 Sigma", "1"], 25.632011235952593)
        self.assertAlmostEqual(page.parameter_models["EW"].frame.loc["3 Sigma", "1"], 256.3201123595259)
        self.window.model.undo.undo()
        self.wait_for_dynamic_refresh()
        self.assertEqual(page.parameter_tables, tables)
        self.assertAlmostEqual(page.parameter_models["DP"].frame.loc["3 Sigma", "1"], 30)
        self.assertAlmostEqual(page.parameter_models["EW"].frame.loc["3 Sigma", "1"], 300)

    def test_edit_after_parameter_removal_keeps_trend_export_on_current_parameters(self):
        self.window.set_table(self.frame(), "dynamic.csv")
        self.select_parameters("DP", "EW")
        self.select_parameters("DP")
        trend = self.window.dynamic_trend
        # Edit Die 2 while Die 1 remains displayed: the export must still receive
        # new table values when the engineer later switches to Die 2.
        self.window.dynamic_page.parameter_models["DP"].edit({(0, 1): "42"})
        self.wait_for_dynamic_refresh()
        self.assertEqual([name for name, _table in trend.panel_specs], ["DP"])
        self.assertEqual(list(trend.panel_tables), ["DP"])
        trend.die_pickers["DP"].setCurrentIndex(1)
        self.assertAlmostEqual(trend.plot_widgets[0].listDataItems()[0].getData()[1][0], 42)
        trend.ensure_export_figure()
        self.assertEqual(len(trend.figure.axes), 1)
        self.assertAlmostEqual(trend.figure.axes[0].lines[0].get_ydata()[0], 42)

    def test_trend_tab_draws_one_cycle_panel_per_parameter_and_one_die(self):
        """Cycle is the x-axis; each panel draws the Die its picker selects."""
        self.window.set_table(self.frame(), "dynamic.csv")
        self.select_parameters("DP", "EW")
        page = self.window.dynamic_trend

        self.assertTrue(page.ready, page.status.text())
        self.assertEqual(
            [parameter for parameter, _table in page.panel_specs], ["DP", "EW"]
        )
        self.assertEqual(len(page.plot_widgets), 2)
        plot_item = page.plot_widgets[0].getPlotItem()
        self.assertEqual(len(plot_item.listDataItems()), 1)
        self.assertEqual(
            [picker.currentText() for picker in page.die_pickers.values()],
            ["Die 1", "Die 1"],
        )
        picker = page.die_pickers["DP"]
        self.assertEqual(
            [picker.itemText(index) for index in range(picker.count())],
            ["Die 1", "Die 2", "Die 3", "Die 4"],
        )
        self.assertIsNotNone(page.panel_hosts[0].side_widget)
        self.assertEqual(page.x_range, (0.5, 3.5))

    def test_trend_tab_has_a_die_picker_instead_of_a_compare_control(self):
        self.window.set_table(self.frame(), "dynamic.csv")
        self.select_parameters("DP")
        page = self.window.dynamic_trend

        labels = [button.text() for button in page.findChildren(QPushButton)]
        self.assertNotIn("Add Compare", labels)
        self.assertEqual(list(page.die_pickers), ["DP"])
        self.assertFalse(page.die_pickers["DP"].currentText().startswith("Die 5"))

    def test_trend_tab_reports_a_parameter_without_dynamic_values(self):
        self.window.set_table(self.frame(), "dynamic.csv")
        self.select_parameters("DP")
        page = self.window.dynamic_trend
        page.selection["metrics"] = ["DP", "TG"]
        page.frame = page.frame.drop(columns=["TG"])

        page.refresh()

        self.assertFalse(page.ready)
        self.assertIn("TG", page.status.text())

    def test_trend_tab_export_mirror_and_copy_use_the_cycle_axis(self):
        self.window.set_table(self.frame(), "dynamic.csv")
        self.select_parameters("DP", "EW")
        page = self.window.dynamic_trend

        page.ensure_export_figure()

        self.assertEqual(len(page.figure.axes), 2)
        axes = page.figure.axes[0]
        self.assertEqual(axes.get_xlabel(), "Cycle")
        self.assertEqual(axes.get_title(), "DP · Die 1")
        self.assertEqual(len(axes.get_lines()), 1)
        page.copy_png()
        self.assertIn("Copied Cycle trends", page.status.text())

    def test_trend_die_picker_switches_one_panel_only(self):
        """Wheel-switching a Die redraws its panel without scrolling the page."""
        self.window.set_table(self.frame(), "dynamic.csv")
        self.select_parameters("DP", "EW")
        page = self.window.dynamic_trend
        page.columns.setCurrentText("1")
        self.window.tabs.setCurrentIndex(2)
        self.window.resize(1200, 500)
        self.window.show()
        APP.processEvents()
        before = page.plot_widgets[1].getPlotItem().listDataItems()[0].getData()[1]

        picker = page.die_pickers["DP"]
        picker.setCurrentText("Die 3")
        picker.clearFocus()
        scroll_bar = page.interactive_scroll.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())
        scroll_position = scroll_bar.value()
        self.assertGreater(scroll_position, 0)

        def wheel(delta):
            event = QWheelEvent(
                QPointF(5, 5), QPointF(picker.mapToGlobal(QPoint(5, 5))),
                QPoint(), QPoint(0, delta), Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.ScrollUpdate, False,
            )
            QApplication.sendEvent(picker, event)
            APP.processEvents()
            self.assertTrue(event.isAccepted())

        wheel(-120)
        self.assertEqual(page.selected_dies["DP"], "4")
        wheel(-120)
        self.assertEqual(picker.currentText(), "Die 4")
        wheel(120)
        APP.processEvents()

        self.assertEqual(page.selected_dies["DP"], "3")
        self.assertEqual(scroll_bar.value(), scroll_position)
        self.assertEqual(page.die_pickers["EW"].currentText(), "Die 1")
        np.testing.assert_array_equal(
            page.plot_widgets[1].getPlotItem().listDataItems()[0].getData()[1],
            before,
        )
        drawn = page.plot_widgets[0].getPlotItem().listDataItems()[0].getData()[1]
        expected = pd.to_numeric(
            page.panel_tables["DP"]["3"], errors="coerce"
        ).to_numpy(float)
        np.testing.assert_array_equal(drawn, expected)
        page.ensure_export_figure()
        self.assertEqual(page.figure.axes[0].get_title(), "DP · Die 3")

    def test_trend_tab_draws_many_dies_without_a_symbol_error(self):
        """A ten-plus Die run used to hit a pyqtgraph symbol it does not know."""
        rows = []
        for cycle in range(1, 4):
            for die in range(1, 13):
                rows.append({
                    "Cur SME File Path":
                        rf"C:\data\DYNAMIC\run-{cycle}\die-{die}.csv",
                    "Wafer ID": "W1",
                    "Lot ID": "L1",
                    "PAD Name": "P1",
                    "Die Seq": die,
                    "DP": 60.0 + cycle + die * 0.1,
                })
        self.window.set_table(pd.DataFrame(rows), "many-dies.csv")
        self.select_parameters("DP")
        page = self.window.dynamic_trend

        self.assertTrue(page.ready, page.status.text())
        self.assertEqual(len(page.plot_widgets[0].getPlotItem().listDataItems()), 1)
        picker = page.die_pickers["DP"]
        self.assertEqual(picker.count(), 12)
        picker.setCurrentText("Die 12")
        APP.processEvents()
        self.assertEqual(page.selected_dies["DP"], "12")
        page.ensure_export_figure()
        self.assertEqual(len(page.figure.axes), 1)
        self.assertEqual(page.figure.axes[0].get_title(), "DP · Die 12")


if __name__ == "__main__":
    unittest.main()
