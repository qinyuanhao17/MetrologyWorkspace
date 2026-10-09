"""Per-plot X/Y direction keeps the same observations and refits the response."""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtWidgets import QApplication, QAbstractButton
from PyQt6.QtCore import QPoint
from PyQt6.QtTest import QTest
from metrology_app import correlation_page as correlations
from metrology_app.correlation_window import CorrelationWindow
from metrology_app.matching import ParameterMapping

APP = QApplication.instance() or QApplication([])


class CorrelationAxisTests(unittest.TestCase):
    def test_copy_png_does_not_include_axis_controls_and_restores_them(self):
        page, _frame = self.page()
        page.resize(1180, 760)
        page.show()
        APP.processEvents()
        button = self.button(page, 0)
        button.setStyleSheet("background: #ff00ff; color: #000000; border: none;")
        page.copy_png()
        image = APP.clipboard().image()
        self.assertFalse(image.isNull(), page.status.text())
        origin = button.mapTo(page.plot_host, QPoint(0, 0))
        scale = image.width() / page.plot_host.width()
        pixels = [image.pixelColor(round((origin.x() + x) * scale), round((origin.y() + y) * scale)).name()
                  for x in range(3, button.width() - 3, 3) for y in range(3, button.height() - 3, 3)]
        self.assertNotIn("#ff00ff", pixels, "Copy PNG must exclude window controls")
        self.assertFalse(button.isHidden())

    def test_reference_direction_is_independent_and_survives_formal_save_and_open(self):
        raw = pd.DataFrame({"Wafer ID": ["001"] * 4, "Die Seq": ["002", "036", "050", "085"],
                            "CD": ["1.000", "2.000", "3.000", "4.000"],
                            "Depth": ["1.000", "2.000", "2.000", "5.000"]})
        reference = raw.copy(deep=True)
        reference["CD"] = ["11.000", "12.000", "13.000", "14.000"]
        mappings = (ParameterMapping("CD", "CD", "CD"), ParameterMapping("Depth", "Depth", "Depth"))
        window, restored = CorrelationWindow(), CorrelationWindow()
        self.addCleanup(APP.processEvents)
        for target in (window, restored):
            self.addCleanup(self.close_window, target)
            target.document.timer.stop()
        window.set_sources(reference, raw, mappings)
        page = window.correlation_page
        page.selector.selectAll()
        page.start_draw()
        window.tabs.setCurrentWidget(page)
        APP.processEvents()
        window.document.mark_clean()
        window.document.identity_timer.stop()
        before = window.workspace_snapshot()
        target = next(index for index, fit in enumerate(page.page_fits()) if fit.sources[0].name == "Reference")
        other = next(index for index, fit in enumerate(page.page_fits()) if fit.sources[0].name == "Raw Data")
        self.button(page, target).click()
        self.assertEqual(page.plot_widgets[target].getPlotItem().getAxis("bottom").labelText, "Depth")
        self.assertEqual(page.plot_widgets[other].getPlotItem().getAxis("bottom").labelText, "CD")
        self.assertTrue(window.document.is_dirty(), "axis direction is a saved document choice")
        deadline = perf_counter() + 1
        while not window.isWindowModified() and perf_counter() < deadline:
            QTest.qWait(10)
        self.assertTrue(window.isWindowModified(), "the title must show the unsaved direction choice")
        with TemporaryDirectory() as scratch:
            path = Path(scratch) / "correlation.wct"
            self.assertEqual(window.document.save(path), path.resolve())
            self.assertFalse(window.document.is_dirty())
            restored.load_workspace(path)
            APP.processEvents()
            self.assertEqual(restored.correlation_page.axis_state(), page.axis_state())
            for fit, widget in zip(restored.correlation_page.page_fits(), restored.correlation_page.plot_widgets):
                expected = "Depth" if fit.sources[0].name == "Reference" else "CD"
                self.assertEqual(widget.getPlotItem().getAxis("bottom").labelText, expected)
            for name, frame in before.frames.items():
                pd.testing.assert_frame_equal(frame, restored.workspace_snapshot().frames[name])
        for target in (window, restored):
            target.document.identity_timer.stop()
            target.refresh_timer.stop()

    def test_direction_survives_parameter_filter_reordering_and_new_measurements(self):
        page, frame = self.page()
        target = next(index for index, fit in enumerate(page.page_fits())
                      if (fit.x_name, fit.y_name) == ("CD", "Depth"))
        self.button(page, target).click()
        page.parameter_filter.buttons["CD"].click()
        for fit, widget in zip(page.page_fits(), page.plot_widgets):
            if {fit.x_name, fit.y_name} == {"CD", "Depth"}:
                self.assertEqual(widget.getPlotItem().getAxis("bottom").labelText, "Depth")
        page.parameter_filter.buttons[None].click()
        changed = frame.copy(deep=True)
        changed["Depth"] = [2., 4., 4., 10.]
        selection = dict(page.selection, metrics=["Height", "Depth", "CD"])
        page.set_input(changed, selection)
        page.selector.selectAll()
        page.start_draw()
        page.ensure_export_figure()
        axis = next(ax for ax in page.figure.axes if {ax.get_xlabel(), ax.get_ylabel()} == {"CD", "Depth"})
        self.assertEqual((axis.get_xlabel(), axis.get_ylabel()), ("Depth", "CD"))
        np.testing.assert_array_equal(axis.collections[0].get_offsets()[:, 0], [2., 4., 4., 10.])
        np.testing.assert_allclose(axis.lines[0].get_ydata(), [1.5, 13 / 6, 13 / 6, 25 / 6])

    def test_saved_direction_does_not_force_drawing_a_pending_selection(self):
        window, restored = CorrelationWindow(), CorrelationWindow()
        self.addCleanup(APP.processEvents)
        for target in (window, restored):
            self.addCleanup(self.close_window, target)
            target.document.timer.stop()
        window.set_table(pd.DataFrame({"Wafer ID": ["001"] * 4, "CD": [1., 2., 3., 4.],
                                       "Depth": [1., 2., 2., 5.]}), "test")
        page = window.correlation_page
        page.selector.selectAll()
        page.start_draw()
        self.button(page, 0).click()
        page.selector.clearSelection()
        restored.restore_workspace(window.workspace_snapshot())
        self.assertFalse(restored.correlation_page.ready)
        self.assertTrue(restored.correlation_page.selector.pending_draw)
        self.assertEqual(restored.correlation_page.axis_state(), page.axis_state())
        restored.correlation_page.selector.selectAll()
        restored.correlation_page.start_draw()
        self.assertEqual(restored.correlation_page.plot_widgets[0].getPlotItem().getAxis("bottom").labelText, "Depth")
        for target in (window, restored):
            target.document.identity_timer.stop()
            target.refresh_timer.stop()

    def page(self):
        page = correlations.CorrelationPage()
        frame = pd.DataFrame({"Wafer ID": ["W1"] * 4, "CD": [1., 2., 3., 4.],
                              "Depth": [1., 2., 2., 5.], "Height": [3., 4., 7., 9.]})
        page.set_input(frame, {"wafer_column": "Wafer ID", "wafers": ["W1"],
                               "groups": {"W1": range(4)}, "metrics": ["CD", "Depth", "Height"]})
        page.selector.selectAll()
        page.start_draw()
        APP.processEvents()
        self.addCleanup(APP.processEvents)
        self.addCleanup(page.deleteLater)
        self.addCleanup(page.close)
        return page, frame

    @staticmethod
    def close_window(window):
        window.document.force_close = True
        window.close()
        window.deleteLater()

    @staticmethod
    def button(page, index):
        buttons = [control for control in page.panel_hosts[index].findChildren(QAbstractButton)
                   if control.text() == "Swap X/Y"]
        if not buttons:
            raise AssertionError("Each correlation plot needs its own Swap X/Y control")
        return buttons[0]

    def test_one_plot_switches_axes_and_export_without_replacing_other_plots_or_source(self):
        page, frame = self.page()
        before = frame.copy(deep=True)
        widgets = list(page.plot_widgets)
        target = next(index for index, fit in enumerate(page.page_fits())
                      if (fit.x_name, fit.y_name) == ("CD", "Depth"))
        other = next(index for index in range(len(widgets)) if index != target)
        widgets[other].getViewBox().setRange(xRange=(1.5, 3.5), yRange=(3, 8), padding=0)
        zoom = widgets[other].getViewBox().viewRange()
        page.ensure_export_figure()
        self.button(page, target).click()
        plot = widgets[target].getPlotItem()
        self.assertEqual(plot.getAxis("bottom").labelText, "Depth")
        self.assertEqual(plot.getAxis("left").labelText, "CD")
        scatter = next(item for item in plot.items if isinstance(item, pg.ScatterPlotItem))
        np.testing.assert_array_equal(scatter.getData()[0], [1., 2., 2., 5.])
        np.testing.assert_array_equal(scatter.getData()[1], [1., 2., 3., 4.])
        page.ensure_export_figure()
        axis = page.figure.axes[target]
        self.assertEqual((axis.get_xlabel(), axis.get_ylabel()), ("Depth", "CD"))
        np.testing.assert_allclose(axis.lines[0].get_ydata(), [1.5, 13 / 6, 13 / 6, 25 / 6])
        self.assertEqual(page.plot_widgets, widgets)
        np.testing.assert_allclose(widgets[other].getViewBox().viewRange(), zoom)
        self.button(page, target).click()
        self.assertEqual((plot.getAxis("bottom").labelText, plot.getAxis("left").labelText), ("CD", "Depth"))
        self.assertEqual(page.axis_state(), [])
        pd.testing.assert_frame_equal(page.frame, before)

    def test_reversed_direction_refits_same_paired_points_not_reciprocal_slope(self):
        frame = pd.DataFrame({"CD": ["1.000", "2.000", "3.000", "4.000", "bad", "6.000"],
                              "Depth": ["1.000", "2.000", "2.000", "5.000", "7.000", "bad"]})
        before = frame.copy(deep=True)
        forward = correlations.fit_numeric_pair(frame, "CD", "Depth")
        reversed_fit = correlations.swap_fit_axes(forward)
        self.assertEqual((reversed_fit.x_name, reversed_fit.y_name), ("Depth", "CD"))
        self.assertAlmostEqual(forward.slope, 1.2)
        self.assertAlmostEqual(reversed_fit.slope, 2 / 3)
        self.assertAlmostEqual(reversed_fit.intercept, 5 / 6)
        self.assertAlmostEqual(reversed_fit.rsquared, .8)
        np.testing.assert_array_equal(reversed_fit.x, [1., 2., 2., 5.])
        np.testing.assert_array_equal(reversed_fit.y, [1., 2., 3., 4.])
        np.testing.assert_allclose(reversed_fit.predicted, [1.5, 13 / 6, 13 / 6, 25 / 6])
        pd.testing.assert_frame_equal(frame, before)


if __name__ == "__main__":
    unittest.main()
