"""Pairwise lmfit analysis and loadable correlation workspace tests."""

import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from wafermap.correlation_page import fit_numeric_pair, pairwise_linear_fits
from wafermap.correlation_window import CorrelationWindow
from wafermap.settings import get_settings
from wafermap.window import MainWindow as WaferMapWindow


ROOT = Path(__file__).resolve().parents[1]
APP = QApplication.instance() or QApplication([])


class CorrelationTests(unittest.TestCase):
    def test_first_cell_paste_auto_selects_numeric_columns(self):
        window = CorrelationWindow()
        try:
            window.sheet.setCurrentIndex(window.model.index(0, 0))
            APP.clipboard().setText(
                "Wafer ID\tX(mm)\tY(mm)\tMSE\tGOF\tNGOF\tLBH\tregIter\tCINDEX\tValue A\tValue B\n"
                "W1\t0\t0\t1\t1\t0.9\t0\t10\t1\t10\t30\n"
                "W2\t1\t1\t2\t1\t0.9\t0\t11\t1\t20\t40"
            )
            window.sheet.paste()
            window.recognize()
            self.assertEqual(set(window.selection["metrics"]), {"Value A", "Value B"})
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_module_specific_defaults_for_new_table(self):
        frame = pd.DataFrame({
            "Wafer ID": ["W1", "W2"], "X(mm)": [0, 1], "Y(mm)": [0, 1],
            "MSE": [1, 2], "GOF": [1, 1], "CINDEX": [4, 5],
            "Value A": [10, 20], "Value B": [30, 40],
        })
        wafer, correlation = WaferMapWindow(), CorrelationWindow()
        try:
            wafer.set_table(frame, "Clipboard")
            correlation.set_table(frame, "Clipboard")
            self.assertEqual(len(wafer.selection["wafers"]), 2)
            self.assertEqual(len(correlation.selection["wafers"]), 2)
            self.assertEqual(wafer.selection["metrics"], [])
            self.assertEqual(set(correlation.selection["metrics"]), {"Value A", "Value B"})
        finally:
            for window in (wafer, correlation):
                window.model.undo.setClean()
                window.close()
                window.deleteLater()
            APP.processEvents()

    def test_lmfit_pair_and_rsq_sorting(self):
        x = np.linspace(-5, 5, 31)
        frame = pd.DataFrame({"A": x, "B": 2 * x + 1, "C": x ** 2})
        fit = fit_numeric_pair(frame, "A", "B")
        self.assertAlmostEqual(fit.slope, 2)
        self.assertAlmostEqual(fit.intercept, 1)
        self.assertAlmostEqual(fit.rsquared, 1)
        fits, errors = pairwise_linear_fits(frame, ["A", "B", "C"])
        self.assertFalse(errors)
        self.assertEqual((fits[0].x_name, fits[0].y_name), ("A", "B"))
        self.assertEqual([fit.rsquared for fit in fits],
                         sorted((fit.rsquared for fit in fits), reverse=True))

    def test_invalid_pairs_are_skipped(self):
        frame = pd.DataFrame({"A": [1, 2, 3], "B": [4, 4, 4], "C": [1, None, None]})
        fits, errors = pairwise_linear_fits(frame, ["A", "B", "C"])
        self.assertEqual(fits, [])
        self.assertEqual(len(errors), 3)

    def test_more_than_sixteen_selected_columns_can_be_drawn(self):
        x = np.linspace(-2, 2, 12)
        frame = pd.DataFrame({"Wafer ID": ["W1"] * len(x), "A": x, "B": 3 * x + 2})
        for index in range(15):
            frame[f"Constant {index}"] = index
        window = CorrelationWindow()
        try:
            window.set_table(frame, "Clipboard")
            self.assertEqual(len(window.selection["metrics"]), 17)
            window.tabs.setCurrentIndex(1)
            page = window.correlation_page
            page.draw_plot()
            self.assertTrue(page.ready, page.status.text())
            self.assertEqual(len(page.all_fits), 1)
            self.assertEqual(len(page.figure.axes), 1)
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_window_reuses_data_tab_and_draws_ranked_array(self):
        window = CorrelationWindow()
        try:
            window.load_path(ROOT / "OCD_measurement_data.csv")
            self.assertEqual(window.tabs.count(), 2)
            self.assertEqual(window.tabs.tabText(0), "1. Data")
            self.assertEqual(window.tabs.tabText(1), "2. Pairwise Fit")
            self.assertGreater(window.sheet.model().rowCount(), 0)
            self.assertEqual(len(window.selection["metrics"]), 15)
            tree = window.parameter_list
            tree.blockSignals(True)
            for index in range(tree.topLevelItemCount()):
                item = tree.topLevelItem(index)
                if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                    item.setCheckState(0, Qt.CheckState.Checked if item.text(0) in
                                       {"OCD_H1", "OCD_H2", "OCD_H3"} else Qt.CheckState.Unchecked)
            tree.blockSignals(False)
            window.update_plan()
            window.tabs.setCurrentIndex(1)
            page = window.correlation_page
            page.draw_plot()
            self.assertTrue(page.ready, page.status.text())
            self.assertEqual(page.copy_shortcut.key(), QKeySequence(QKeySequence.StandardKey.Copy))
            self.assertEqual(page.min_rsq.value(), .5)
            self.assertEqual(len(page.all_fits), 3)
            self.assertEqual(len(page.fits), 1)
            scores = [fit.rsquared for fit in page.fits]
            self.assertEqual(scores, sorted(scores, reverse=True))
            self.assertTrue(all(score > .5 for score in scores))
            self.assertEqual(len(page.figure.axes), 1)
            self.assertIn("vs", page.figure.axes[0].get_title(loc="center"))
            self.assertIn("R² > 0.50", page.status.text())
            self.assertEqual(page.resolution.currentText(), get_settings()["resolution"])
            page.min_rsq.setValue(.1)
            QTest.qWait(220)
            self.assertEqual(len(page.fits), 2)
            page.min_rsq.setValue(.95)
            QTest.qWait(220)
            self.assertFalse(page.ready)
            self.assertEqual(page.fits, [])
            self.assertEqual(len(page.all_fits), 3)
            page.min_rsq.setValue(.5)
            QTest.qWait(220)
            self.assertTrue(page.ready)
            self.assertEqual(len(page.fits), 1)
            page.copy_png()
            self.assertFalse(APP.clipboard().image().isNull())
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()


if __name__ == "__main__":
    unittest.main()
