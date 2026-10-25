"""Die hover, thicker export curves, Bias limits, Dynamic titles and map sizing."""
import os
from pathlib import Path
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from openpyxl import load_workbook
from PyQt6.QtCore import QPointF
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QToolTip

from metrology_app.dynamic_page import DynamicPage
from metrology_app.excel_export import parameter_figure, picture_ratio
from metrology_app.matching.analysis import Card
from metrology_app.matching_window import MatchingWindow

APP = QApplication.instance() or QApplication([])


class ExportHoverFixTests(unittest.TestCase):
    def setUp(self):
        self.window = MatchingWindow()
        self.child = None

    def tearDown(self):
        for window in (self.child, self.window):
            if window is None:
                continue
            window.document.force_close = True
            window.close()
            window.deleteLater()
        APP.processEvents()

    def draw_stage(self):
        reference = pd.DataFrame({"CD Reference": [3.0, 5.0, 7.0, 4.0, 6.0, 8.0]})
        raw = pd.DataFrame({
            "Wafer ID": ["W1"] * 3 + ["W2"] * 3,
            "Die Seq": [1, 2, 3] * 2,
            "FIELD X": [-1.0, 1.0, 0.0] * 2,
            "FIELD Y": [-1.0, -1.0, 1.0] * 2,
            "CD": ["1.0", "2.0", "3.0", "4.0", "5.0", "6.0"],
        })
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.run_analysis()
        self.child = self.window.open_stage_workspace("preview")
        self.child.resize(1400, 900)
        self.child.show()
        APP.processEvents()

    @staticmethod
    def wait_worker(page, timeout=60):
        deadline = time.perf_counter() + timeout
        while getattr(page, "worker", None) is not None and time.perf_counter() < deadline:
            APP.processEvents()
            time.sleep(0.01)
        APP.processEvents()

    def test_map_and_radius_hover_report_die_and_value(self):
        self.draw_stage()
        self.child.tabs.setCurrentIndex(1)
        self.child.check_all(self.child.wafer_list, True)
        self.child.check_all(self.child.parameter_list, True)
        APP.processEvents()
        map_page = self.child.plot_page
        self.wait_worker(map_page)
        map_page.selector.selectAll()
        map_page.draw_maps()
        self.wait_worker(map_page)
        panel = map_page.map_grid.panels[0]
        point = QPointF(*map(float, panel._pixel_positions[0]))
        text = panel.hover_text(point)
        self.assertIn("Die 1", text)
        self.assertIn("CD = 1", text)
        self.assertIn("X = -1", text)
        # A real mouse move must reach the panel and show the tooltip.
        view = map_page.scroll
        scene_point = panel.mapToScene(point)
        QTest.mouseMove(view.viewport(), view.mapFromScene(scene_point))
        APP.processEvents()
        self.assertIn("Die 1", QToolTip.text())
        self.assertIn("Die 1", map_page.status.text())

        radius_page = self.child.radius_page
        radius_page.selector.selectAll()
        radius_page.draw_plot()
        APP.processEvents()
        radius_panel = radius_page.radius_grid.panels[0]
        radius_point = QPointF(*map(float, radius_panel._pixel_positions[0]))
        radius_text = radius_panel.hover_text(radius_point)
        self.assertIn("Die 1", radius_text)
        self.assertIn("CD = 1", radius_text)
        self.assertIn("Signed radius", radius_text)

    def test_export_bias_figure_has_limits_and_thicker_curves(self):
        data = pd.DataFrame({"Raw": np.linspace(1, 2, 5),
                             "Reference": np.linspace(2.1, 2.3, 5)})
        figure = parameter_figure("DP", data, Card(1.0, 0.1, 0.9, 5), "preview", "All",
                                  panel="Bias", unit="nm", bias_limit=0.2,
                                  show_bias_limit=True)
        lines = figure.axes[0].lines
        red = [line for line in lines if line.get_color() == "#DC2626"]
        self.assertEqual(sorted(round(float(line.get_ydata()[0]), 6) for line in red),
                         [-0.2, 0.2])
        curve = next(line for line in lines if line.get_color() == "#4F8BD6")
        self.assertEqual(curve.get_linewidth(), 2.5)
        self.assertEqual(curve.get_markersize(), 6)

    def test_export_trend_uses_the_shared_line_and_marker_style(self):
        from metrology_app.excel_export import report_sequence_layout
        data = pd.DataFrame({"Raw": [1., 2., 3.], "Reference": [1.1, 2.1, 3.1],
                             "Die Seq": ["1", "2", "3"]})
        sequence = report_sequence_layout(data["Die Seq"].tolist(), name="Die")
        sequence.update({"ticks": [], "mode": "die"})
        figure = parameter_figure(
            "DP", data, Card(1.0, 0., 0.9, 3), "preview", "All",
            panel="Trend", unit="nm", sequence=sequence)
        curves = figure.axes[0].lines
        self.assertEqual(len(curves), 2)
        self.assertTrue(all(line.get_linewidth() == 2.5 for line in curves))
        self.assertTrue(all(line.get_marker() == "o" for line in curves))
        self.assertTrue(all(line.get_markersize() == 6 for line in curves))

    def test_trend_and_bias_axes_leave_marker_headroom(self):
        from openpyxl.chart import LineChart
        from metrology_app.excel_export import chart_limits
        trend = LineChart()
        chart_limits(trend, [14.888, 21.817])
        self.assertLess(trend.y_axis.scaling.min, 14.)
        self.assertGreater(trend.y_axis.scaling.max, 24.)
        bias = LineChart()
        chart_limits(bias, [-.25, .24], symmetric=True)
        self.assertLess(bias.y_axis.scaling.min, -.3)
        self.assertGreater(bias.y_axis.scaling.max, .3)

    def test_map_and_radius_pictures_share_row_height(self):
        class Picture:
            width, height = 1000, 400
        shapes = {"Wafer Map": (2, 3), "Radius": (1, 3)}
        self.assertEqual(picture_ratio("Wafer Map", Picture(), shapes),
                         picture_ratio("Radius", Picture(), shapes))

    def test_paginated_parameter_figures_show_their_page_label(self):
        data = pd.DataFrame({
            "Raw": [1., 2., 3.],
            "Reference": [2., 3., 4.],
            "Die Seq": ["1", "2", "3"],
        })
        for panel, expected in (
                ("Match", "CD (Page 1/2)"),
                ("Trend", "CD (Page 1/2)"),
                ("Bias", "Bias (Page 1/2)"),
                ("Bias %", "Bias % (Page 1/2)")):
            figure = parameter_figure(
                "CD", data, None, "Final", "Wafer",
                panel=panel, page_label="Page 1/2")
            try:
                self.assertEqual(figure.axes[0].get_title(), expected)
            finally:
                figure.clear()

    def test_dynamic_plot_title_uses_cycles_and_parameter(self):
        page = DynamicPage()
        pivot = pd.DataFrame(np.zeros((11, 2)), columns=[1, 2],
                             index=[*range(10), "3 Sigma"])
        page._add_parameter_plot("DP", pivot, "#3366cc")
        self.assertEqual(page.plots[0].getPlotItem().titleLabel.text,
                         "10 Cycles Dynamic of DP (nm)")
        page.deleteLater()

    def test_native_bias_chart_contains_limit_series(self):
        self.draw_stage()
        from PyQt6.QtWidgets import QCheckBox, QDoubleSpinBox
        limit_cell = self.window.mapping_table.cellWidget(0, 10)
        self.assertIsNotNone(limit_cell)
        show_box = limit_cell.findChild(QCheckBox)
        spin = limit_cell.findChild(QDoubleSpinBox)
        self.assertIsNotNone(show_box)
        self.assertIsNotNone(spin)
        spin.setValue(0.2)
        show_box.setChecked(True)
        APP.processEvents()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "native.xlsx"
            self.window.export_excel(path)
            book = load_workbook(path)
            series = [item for sheet in book.worksheets
                      for chart in getattr(sheet, "_charts", [])
                      for item in chart.series]
            values = {round(float(point.v), 6) for item in series
                      if getattr(item.val, "numLit", None)
                      for point in item.val.numLit.pt}
            self.assertIn(0.2, values)
            self.assertIn(-0.2, values)
            styled = [item for sheet in book.worksheets if sheet.title.startswith("Match")
                      for chart in getattr(sheet, "_charts", [])
                      for item in chart.series
                      if item.marker is not None and item.marker.symbol == "circle"
                      and item.graphicalProperties.line.solidFill is not None]
            self.assertTrue(styled)
            self.assertTrue(all(item.marker.size == 6 for item in styled))
            self.assertTrue(all(item.graphicalProperties.line.w == 31750 for item in styled))


if __name__ == "__main__":
    unittest.main()
