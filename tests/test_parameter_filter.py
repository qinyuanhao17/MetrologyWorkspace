"""Parameter navigation filters presentation, not the fitted source population."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QApplication, QLabel
from metrology_app.correlation_page import CorrelationPage
from metrology_app.sequence_page import SequencePage

APP = QApplication.instance() or QApplication([])


class ParameterFilterTests(unittest.TestCase):
    def data(self):
        frame = pd.DataFrame({"Wafer ID": ["W1"] * 5, "Die Seq": [2, 36, 85, 101, 105],
                              "DP": [1., 2., 3., 4., 5.], "TG": [2., 4., 6., 8., 10.],
                              "EW": [3., 6., 9., 12., 15.]})
        return frame, {"wafer_column": "Wafer ID", "wafers": ["W1"],
                       "metrics": ["DP", "TG", "EW"], "groups": {"W1": range(5)}}

    def test_correlation_parameter_and_all_keep_fits_curves_and_zoom(self):
        page = CorrelationPage()
        frame, selection = self.data()
        try:
            page.set_input(frame, selection)
            page.selector.selectAll()
            page.start_draw()
            APP.processEvents()
            original = list(page.plot_widgets)
            self.assertEqual(len(original), 3, page.status.text())
            fits = list(page.all_fits)
            self.assertEqual(len(original), 3)
            original[0].getViewBox().setRange(xRange=(2, 4), yRange=(4, 8), padding=0)
            zoom = original[0].getViewBox().viewRange()
            page.parameter_filter.buttons["DP"].click()
            self.assertEqual(len(page.page_fits()), 2)
            self.assertTrue(all("DP" in (fit.x_name, fit.y_name) for fit in page.page_fits()))
            self.assertEqual(page.all_fits, fits)
            page.parameter_filter.buttons[None].click()
            self.assertEqual(page.plot_widgets, original)
            np.testing.assert_allclose(original[0].getViewBox().viewRange(), zoom)
            pd.testing.assert_frame_equal(page.frame, frame)
        finally:
            page.close()
            page.deleteLater()
            APP.processEvents()

    def test_filtered_cached_headings_and_exports_use_current_rank(self):
        page = CorrelationPage()
        frame, selection = self.data()
        try:
            page.set_input(frame, selection)
            page.selector.selectAll()
            page.start_draw()
            APP.processEvents()
            first = page.fits[0]
            parameter = next(name for name in selection["metrics"] if name not in (first.x_name, first.y_name))
            page.parameter_filter.buttons[parameter].click()
            for rank, panel in enumerate(page.panel_hosts, 1):
                self.assertIn(f"rank {rank}", panel.findChildren(QLabel)[0].text())
            page.ensure_export_figure()
            self.assertEqual(len(page.figure.axes), 2)
            self.assertTrue(all(parameter in (ax.get_xlabel(), ax.get_ylabel()) for ax in page.figure.axes))
        finally:
            page.deleteLater()
            APP.processEvents()

    def test_trend_filter_includes_comparison_parameter_and_export(self):
        page = SequencePage()
        frame, selection = self.data()
        try:
            page.set_input(frame, selection)
            page.selector.selectAll()
            page.draw_plot()
            page.set_overlay("DP", "EW")
            APP.processEvents()
            original = list(page.plot_widgets)
            page.parameter_filter.buttons["EW"].click()
            self.assertEqual([panel["metric"] for panel in page.display_panel_specs()], ["DP", "EW"])
            page.ensure_export_figure()
            self.assertTrue(any("DP" in ax.get_title() for ax in page.figure.axes))
            self.assertFalse(any("TG" == ax.get_ylabel() for ax in page.figure.axes))
            page.parameter_filter.buttons[None].click()
            self.assertEqual(page.plot_widgets, original)
        finally:
            page.deleteLater()
            APP.processEvents()

    def test_trend_parameter_and_all_reuse_every_panel_and_keep_full_curve_values(self):
        page = SequencePage()
        frame, selection = self.data()
        try:
            page.set_input(frame, selection)
            page.selector.selectAll()
            page.draw_plot()
            APP.processEvents()
            original = list(page.plot_widgets)
            curves = [widget.listDataItems()[0] for widget in original]
            values = [curve.getData()[1].copy() for curve in curves]
            page.parameter_filter.buttons["DP"].click()
            self.assertEqual(len(page.plot_host.panels), 1)
            self.assertIs(page.plot_widgets[0], original[0])
            page.parameter_filter.buttons[None].click()
            self.assertEqual(page.plot_widgets, original)
            for curve, expected in zip(curves, values):
                np.testing.assert_array_equal(curve.getData()[1], expected)
        finally:
            page.close()
            page.deleteLater()
            APP.processEvents()


if __name__ == "__main__":
    unittest.main()
