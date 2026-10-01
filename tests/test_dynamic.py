"""Dynamic repeatability analysis regression tests."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QApplication, QComboBox, QLabel, QScrollArea

from metrology_app.dynamic import dynamic_pivot, prepare_dynamic_frame
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


class DynamicWindowTests(unittest.TestCase):
    def setUp(self):
        self.window = DynamicWindow()

    def tearDown(self):
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
            ["1. Data", "2. Dynamic"],
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


if __name__ == "__main__":
    unittest.main()
