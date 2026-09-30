"""Dynamic repeatability analysis regression tests."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QComboBox, QScrollArea

from metrology_app.dynamic import dynamic_pivot, prepare_dynamic_frame
from metrology_app.dynamic_window import DynamicWindow


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
                })
        return pd.DataFrame(rows)

    def test_selected_parameters_render_comparison_and_individual_fixed_plots(self):
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
        self.assertEqual(
            page.findChildren(QComboBox, "dynamicParameter"), []
        )
        self.assertEqual(
            page.pivot_model.frame.index.tolist(),
            [1, 2, 3, "3 Sigma"],
        )
        self.assertEqual(
            page.pivot_model.frame.columns.tolist(),
            [
                ("DP", "1"), ("DP", "2"), ("DP", "3"), ("DP", "4"),
                ("EW", "1"), ("EW", "2"), ("EW", "3"), ("EW", "4"),
            ],
        )
        self.assertEqual(
            [plot.getPlotItem().titleLabel.text for plot in page.plots],
            ["DP + EW", "DP", "EW"],
        )
        self.assertEqual(
            [(plot.width(), plot.height()) for plot in page.plots],
            [(510, 330), (510, 330), (510, 330)],
        )
        combined_bars = [
            item for item in page.plots[0].getPlotItem().items
            if isinstance(item, pg.BarGraphItem)
        ]
        self.assertEqual(len(combined_bars), 2)
        self.assertNotEqual(
            combined_bars[0].opts["brush"].color().name(),
            combined_bars[1].opts["brush"].color().name(),
        )
        legend_labels = [
            label.text for _sample, label in page.plots[0].getPlotItem().legend.items
        ]
        self.assertEqual(legend_labels, ["DP", "EW"])
        for plot in page.plots:
            sigma_axis = plot.getAxis("left")
            self.assertEqual(sigma_axis.labelText, "3 Sigma (nm)")
            self.assertFalse(sigma_axis.autoSIPrefix)
        self.window.tabs.setCurrentIndex(1)
        self.window.resize(1100, 800)
        self.window.show()
        APP.processEvents()
        self.assertIsInstance(page.plot_scroll, QScrollArea)
        self.assertGreater(page.plot_scroll.horizontalScrollBar().maximum(), 0)
        self.assertEqual(
            page.table.verticalHeader().defaultSectionSize(), 28
        )

    def test_new_table_does_not_require_die_seq_before_data_is_pasted(self):
        self.window.set_table(pd.DataFrame(), "Untitled")
        self.assertEqual(self.window.model.frame().shape, (0, 0))


if __name__ == "__main__":
    unittest.main()
