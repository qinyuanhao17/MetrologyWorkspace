"""Static pyqtgraph radius presentation and unchanged numerical/export semantics."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication

from metrology_app.radius_page import RadiusPage

APP = QApplication.instance() or QApplication([])


class StaticRadiusTests(unittest.TestCase):
    def page(self):
        page = RadiusPage()
        self.addCleanup(page.deleteLater)
        self.addCleanup(page.close)
        self.addCleanup(page.stop)
        frame = pd.DataFrame({"Wafer ID": ["W1"]*5, "X(mm)": ["-3", "0", "4", "bad", "1"],
                              "Y(mm)": ["4", "5", "3", "1", "2"],
                              "P": ["10.000", "12.000", "15.000", "7", "bad"]})
        page.set_input(frame, {"wafers": ["W1"], "metrics": ["P"], "wafer_column": "Wafer ID"})
        return page, frame

    def test_draw_is_pyqtgraph_without_an_eager_matplotlib_export(self):
        page, frame = self.page()
        original = frame.copy(deep=True)
        with patch("matplotlib.figure.Figure.subplots", side_effect=AssertionError("Eager Matplotlib")):
            page.draw_plot()
            self.assertTrue(page.ready, page.status.text())
            self.assertIsNone(page._canvas)
            panel = page.radius_grid.panels[0]
            self.assertTrue(panel.scatter.opts["antialias"])
            np.testing.assert_array_equal(panel.source["radius"], [-5, 0, 5])
            np.testing.assert_array_equal(panel.source["value"], [10, 12, 15])
        pd.testing.assert_frame_equal(frame, original)

    def test_window_resize_changes_only_display_not_scientific_coordinates(self):
        page, _frame = self.page()
        page.draw_plot()
        page.show()
        APP.processEvents()
        before = page.radius_grid.panels[0].source["radius"].copy()
        page.resize(page.width()+180, page.height()+90)
        APP.processEvents()
        transform = page.scroll.transform()
        event = QWheelEvent(QPointF(20, 20), QPointF(20, 20), QPoint(), QPoint(0, 120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier,
                            Qt.ScrollPhase.ScrollUpdate, False)
        APP.sendEvent(page.scroll.viewport(), event)
        self.assertGreater(page.scroll.transform().m11(), transform.m11())
        np.testing.assert_array_equal(before, page.radius_grid.panels[0].source["radius"])

    def test_scatter_data_limits_and_geometry_match_matplotlib_export(self):
        page, _frame = self.page()
        page.draw_plot()
        figure = page.figure
        figure.canvas.draw()
        panel = page.radius_grid.panels[0]
        axes = figure.axes[0]
        np.testing.assert_array_equal(axes.collections[0].get_offsets(),
                                     np.column_stack([panel.source["radius"], panel.source["value"]]))
        np.testing.assert_allclose(panel.y_limits, axes.get_ylim())
        scale = figure.dpi/100
        bounds = axes.bbox
        np.testing.assert_allclose(panel.box.getRect(), [bounds.x0/scale, page.base_size[1]-bounds.y1/scale,
                                                        bounds.width/scale, bounds.height/scale])
