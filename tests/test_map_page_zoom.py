"""Ctrl+wheel scales the entire static grid, never an individual scientific axis."""
import unittest
from unittest.mock import patch

import numpy as np
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication

from metrology_app.array_plot import ArrayOptions, prepare_array
from metrology_app.plot_page import PlotPage
from metrology_app.radius_page import RadiusPage
from tests.test_wafer_static import finish_graphics, map_fixture

APP = QApplication.instance() or QApplication([])


class MapPageZoomTests(unittest.TestCase):
    def page(self, kind, *, wafers=1, metrics=8):
        frame, selection = map_fixture(wafers, metrics)
        page = kind()
        self.addCleanup(APP.processEvents)
        self.addCleanup(page.deleteLater)
        self.addCleanup(page.close)
        self.addCleanup(page.stop)
        if kind is PlotPage:
            result = prepare_array(frame, selection, ArrayOptions("X mm", "Y mm"))
            page.render_result(result)
        else:
            page.set_input(frame, selection)
            page.draw_plot()
        page.resize(1400, 850)
        page.show()
        APP.processEvents()
        if kind is PlotPage:
            finish_graphics(page)
        return page

    @staticmethod
    def wheel(page, delta, modifiers=Qt.KeyboardModifier.ControlModifier, position=None):
        position = position or page.scroll.viewport().rect().center()
        event = QWheelEvent(QPointF(position), QPointF(page.scroll.viewport().mapToGlobal(position)),
                            QPoint(), QPoint(0, delta), Qt.MouseButton.NoButton, modifiers,
                            Qt.ScrollPhase.ScrollUpdate, False)
        APP.sendEvent(page.scroll.viewport(), event)
        APP.processEvents()

    def test_ctrl_wheel_changes_whole_grid_scale_without_calculation_or_export(self):
        for kind in (PlotPage, RadiusPage):
            with self.subTest(page=kind.__name__):
                page = self.page(kind)
                page.zoom.setCurrentText("100%")
                APP.processEvents()
                before = page.scroll.transform().m11()
                sources = ([scene["surface"] for scene in page.result["scenes"]]
                           if kind is PlotPage else [source["radius"].copy() for source in page.plot_sources])
                with patch("metrology_app.plot_page.prepare_array", side_effect=AssertionError("Re-interpolation")), \
                        patch("metrology_app.plot_page.draw_array", side_effect=AssertionError("Eager export")):
                    self.wheel(page, 120)
                    enlarged = page.scroll.transform().m11()
                    self.assertGreater(enlarged, before)
                    self.wheel(page, -120)
                    self.assertLess(page.scroll.transform().m11(), enlarged)
                self.assertIsNone(page._canvas)
                self.assertFalse(page.scroll.mouseEnabled)
                if kind is PlotPage:
                    for surface, scene in zip(sources, page.result["scenes"]):
                        self.assertIs(surface, scene["surface"])
                else:
                    for values, source in zip(sources, page.plot_sources):
                        np.testing.assert_array_equal(values, source["radius"])

    def test_fit_width_really_fits_a_wide_grid_and_view_control_is_visible(self):
        for kind in (PlotPage, RadiusPage):
            with self.subTest(page=kind.__name__):
                page = self.page(kind)
                page.zoom.setCurrentText("100%")
                APP.processEvents()
                self.assertGreater(page.scroll.horizontalScrollBar().maximum(), 0)
                page.zoom.setCurrentText("Fit width")
                APP.processEvents()
                self.assertEqual(page.scroll.horizontalScrollBar().maximum(), 0)
                self.assertFalse(page.zoom.isHidden())

    def test_zoom_keeps_pointer_over_same_scene_location_after_deferred_layout(self):
        for kind in (PlotPage, RadiusPage):
            with self.subTest(page=kind.__name__):
                page = self.page(kind, wafers=2, metrics=8)
                page.zoom.setCurrentText("100%")
                APP.processEvents()
                for bar in (page.scroll.horizontalScrollBar(), page.scroll.verticalScrollBar()):
                    self.assertGreater(bar.maximum(), 0)
                    bar.setValue(bar.maximum()//3)
                position = QPoint(page.scroll.viewport().width()//3, page.scroll.viewport().height()//2)
                before = page.scroll.mapToScene(position)
                self.wheel(page, 120, position=position)
                APP.processEvents()
                after = page.scroll.mapToScene(position)
                self.assertLess(abs(after.x()-before.x()), 3)
                self.assertLess(abs(after.y()-before.y()), 3)
                page.resize(page.width()+20, page.height()+20)
                APP.processEvents()
                self.assertEqual(page.zoom.currentText(), "125%")
                self.assertAlmostEqual(page.scroll.transform().m11(), 1.25)

    def test_zoom_limits_and_normal_and_shift_wheel_scrolling(self):
        for kind in (PlotPage, RadiusPage):
            with self.subTest(page=kind.__name__):
                page = self.page(kind, wafers=2, metrics=8)
                for label, delta, expected in (("1%", -120, .01), ("300%", 120, 3.)):
                    page.zoom.setCurrentText(label)
                    APP.processEvents()
                    self.wheel(page, delta)
                    self.assertAlmostEqual(page.scroll.transform().m11(), expected)
                page.zoom.setCurrentText("100%")
                APP.processEvents()
                horizontal, vertical = page.scroll.horizontalScrollBar(), page.scroll.verticalScrollBar()
                self.assertGreater(horizontal.maximum(), 0)
                self.assertGreater(vertical.maximum(), 0)
                horizontal.setValue(horizontal.maximum()//3)
                vertical.setValue(vertical.maximum()//3)
                before_h, before_v = horizontal.value(), vertical.value()
                self.wheel(page, -120, Qt.KeyboardModifier.NoModifier)
                self.assertEqual(horizontal.value(), before_h)
                self.assertGreater(vertical.value(), before_v)
                before_v = vertical.value()
                self.wheel(page, -120, Qt.KeyboardModifier.ShiftModifier)
                self.assertGreater(horizontal.value(), before_h)
                self.assertEqual(vertical.value(), before_v)
