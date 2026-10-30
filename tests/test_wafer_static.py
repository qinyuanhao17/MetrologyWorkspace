"""Static wafer-map presentation: real page seam, with synthetic measurements."""
from statistics import median
from time import perf_counter
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt
from PyQt6.QtGui import QImage, QPainter, QWheelEvent
from PyQt6.QtTest import QTest
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from metrology_app.array_plot import ArrayOptions, draw_array, prepare_array
from metrology_app.plot_page import PlotPage


APP = QApplication.instance() or QApplication([])


def finish_graphics(page):
    deadline = perf_counter() + 8
    while page.background_render_pending:
        if perf_counter() >= deadline:
            raise AssertionError(page.status.text())
        QTest.qWait(1)


def map_fixture(wafers=2, metrics=5):
    axis = np.linspace(-120, 120, 9)
    xy = [(x, y) for x in axis for y in axis if x*x + y*y < 145**2]
    frame = pd.DataFrame([
        {"Wafer ID": f"W{wafer}", "X mm": str(x), "Y mm": str(y),
         **{f"P{metric}": str(10 + metric + x*.002 + y*.001 + wafer*.1)
            for metric in range(metrics)}}
        for wafer in range(wafers) for x, y in xy
    ])
    selection = {"wafer_column": "Wafer ID", "wafers": [f"W{i}" for i in range(wafers)],
                 "metrics": [f"P{i}" for i in range(metrics)]}
    return frame, selection


class StaticWaferTests(unittest.TestCase):
    def make_page(self, result):
        page = PlotPage()
        self.addCleanup(page.deleteLater)
        self.addCleanup(page.close)
        self.addCleanup(page.stop)
        page.render_result(result)
        finish_graphics(page)
        self.assertIsNotNone(page.result, page.empty.text())
        return page

    def test_screen_zoom_scales_the_grid_without_matplotlib_or_individual_plot_navigation(self):
        frame, selection = map_fixture(1, 2)
        result = prepare_array(frame, selection, ArrayOptions("X mm", "Y mm"))
        with patch("metrology_app.plot_page.draw_array", side_effect=AssertionError("Eager export")):
            page = self.make_page(result)
            page.show()
            APP.processEvents()
            self.assertIsNone(page._canvas)
            before = page.scroll.transform()
            event = QWheelEvent(QPointF(20, 20), QPointF(20, 20), QPoint(), QPoint(0, 120),
                                Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier,
                                Qt.ScrollPhase.ScrollUpdate, False)
            APP.sendEvent(page.scroll.viewport(), event)
            self.assertGreater(page.scroll.transform().m11(), before.m11())
            self.assertFalse(page.scroll.mouseEnabled)
            self.assertFalse(page.zoom.isHidden())
            for panel in page.map_grid.panels:
                self.assertEqual(panel.acceptedMouseButtons(), Qt.MouseButton.NoButton)
                self.assertTrue(panel.acceptHoverEvents())
                self.assertEqual(panel.image.acceptedMouseButtons(), Qt.MouseButton.NoButton)

    def test_screen_geometry_pixels_and_contours_match_export(self):
        frame, selection = map_fixture(2, 2)
        options = ArrayOptions("X mm", "Y mm", contour=True, shared_scale=True,
                               cmap="viridis", opacity=.8, point_outline=True)
        result = prepare_array(frame, selection, options)
        page = self.make_page(result)
        # Do not use png_bytes here: UI checkbox reconciliation is tested below.
        figure = page.figure
        figure.canvas.draw()
        scale = figure.dpi/100
        height = page.map_grid.boundingRect().height()
        for panel, (plot, scene) in zip(page.map_grid.panels, page.artists):
            bounds = plot.axes.bbox
            np.testing.assert_allclose(panel.axis_rect.getRect(),
                [bounds.x0/scale, height-bounds.y1/scale, bounds.width/scale, bounds.height/scale], atol=1e-8)
            self.assertEqual((panel.low, panel.high), plot.image.get_clim())
            surface = scene["surface"][3].data
            expected = plot.image.to_rgba(np.ma.masked_invalid(surface), bytes=True)
            np.testing.assert_array_equal(panel.rgba, expected)
            np.testing.assert_array_equal(panel.image.image, expected[::-1])
            self.assertEqual(panel.image.opacity(), .8)
            self.assertTrue(panel.image.flags() & panel.GraphicsItemFlag.ItemStacksBehindParent)
            panel._prepare_contours()
            self.assertEqual(len(panel.contours), len(plot.contours.get_paths()))
            for (path, _colour), exported in zip(panel.contours, plot.contours.get_paths()):
                if len(exported.vertices):
                    np.testing.assert_allclose([path.boundingRect().left(), path.boundingRect().right(),
                                               path.boundingRect().top(), path.boundingRect().bottom()],
                                              [exported.vertices[:, 0].min(), exported.vertices[:, 0].max(),
                                               exported.vertices[:, 1].min(), exported.vertices[:, 1].max()])

    def test_copy_png_matches_unchanged_matplotlib_renderer_and_updated_controls(self):
        frame, selection = map_fixture(1, 2)
        result = prepare_array(frame, selection, ArrayOptions("X mm", "Y mm"))
        page = self.make_page(result)
        page.labels.setChecked(True)
        page.points.setChecked(True)
        page.point_decimals.blockSignals(True)  # Local display test, not a settings test.
        page.point_decimals.setValue(3)
        page.point_decimals.blockSignals(False)
        page.contour.setChecked(True)
        page.point_outline.setChecked(True)
        page.color_map.setCurrentText("Viridis")
        page.scale_bar.setChecked(False)
        page.apply_plot_style()
        finish_graphics(page)
        actual = QImage.fromData(page.png_bytes())
        page.figure.canvas.draw()
        reference = Figure(figsize=page.figure.get_size_inches(), dpi=page.figure.dpi, facecolor="white")
        FigureCanvasAgg(reference)
        # Presentation updates no longer mutate the still-published old result.
        self.assertFalse(result['settings'].contour)
        draw_array(reference, page.result, int(page.font_size.currentText()))
        from io import BytesIO
        from metrology_app.appearance import export_dpi, resolution_settings, MAX_COPY_PIXELS
        buffer = BytesIO()
        reference.savefig(buffer, format="png", dpi=export_dpi(reference,
            resolution_settings(page.resolution)[1], MAX_COPY_PIXELS), facecolor="white")
        self.assertEqual(actual, QImage.fromData(buffer.getvalue()))
        for panel in page.map_grid.panels:
            self.assertEqual(panel.value_labels.decimals, 3)
            self.assertTrue(panel.source["options"].contour)
            self.assertFalse(panel.source["options"].show_colorbar)

    def test_skip_error_and_replacement_do_not_leave_old_maps(self):
        frame, selection = map_fixture(1, 2)
        result = prepare_array(frame, selection, ArrayOptions("X mm", "Y mm"))
        result["scenes"][1]["error"] = "Invalid coordinates"
        page = self.make_page(result)
        self.assertEqual(page.map_grid.valid_count, 1)
        old = tuple(page.map_grid.panels)
        frame, selection = map_fixture(1, 1)
        replacement = prepare_array(frame, selection, ArrayOptions("X mm", "Y mm"))
        page.render_result(replacement)
        self.assertEqual(len(page.map_grid.panels), 1)
        self.assertTrue(all(panel.scene() is None for panel in old))
        replacement["scenes"][0]["skip"] = True
        page.render_result(replacement)
        self.assertEqual(page.map_grid.valid_count, 0)

    def test_repeated_data_changes_keep_only_current_scene_items(self):
        frame, selection = map_fixture(1, 2)
        original = frame.copy(deep=True)
        page = PlotPage()
        self.addCleanup(page.deleteLater)
        self.addCleanup(page.close)
        self.addCleanup(page.stop)
        for case in range(8):
            current = frame.rename(columns={"P0": f"Case {case}"})
            current_selection = dict(selection, metrics=[f"Case {case}", "P1"])
            result = prepare_array(current, current_selection, ArrayOptions("X mm", "Y mm"))
            page.render_result(result)
            APP.processEvents()
            self.assertEqual(len(page.scene.items()), 5)  # Root + two panels + two ImageItems.
            self.assertEqual(page.map_grid.panels[0].source["metric"], f"Case {case}")
            self.assertIsNone(page._canvas)
        pd.testing.assert_frame_equal(frame, original)

    def test_prepared_maps_do_not_block_the_ui(self):
        """Ten prepared maps should present within a 250 ms UI blocking budget."""
        frame, selection = map_fixture()
        original = frame.copy(deep=True)
        result = prepare_array(frame, selection, ArrayOptions("X mm", "Y mm"))
        page = PlotPage()
        page.resize(1200, 800)
        page.show()
        APP.processEvents()
        durations = []
        try:
            for _ in range(3):
                start = perf_counter()
                page.render_result(result)
                APP.processEvents()
                finish_graphics(page)  # Completion remains inside the original timing budget.
                durations.append(perf_counter() - start)
                self.assertIsNotNone(page.result, page.empty.text())
            print("wafer UI seconds:", durations, "median:", median(durations), flush=True)
            pd.testing.assert_frame_equal(frame, original)
            self.assertLess(median(durations), .25, "Wafer-map presentation blocks the UI")
        finally:
            page.stop()
            page.close()
            page.deleteLater()
            APP.processEvents()
