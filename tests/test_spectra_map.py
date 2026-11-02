"""Qt integration checks for paginated spectrum wafer maps."""

import os
import time
import unittest
from dataclasses import replace

import numpy as np
import pyqtgraph as pg

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtTest import QTest

from metrology_app.spectra_map import SpectraMapWindow
from tests.test_spectra_viewer import make_spectrum


APP = QApplication.instance() or QApplication([])


class SpectraMapWindowTests(unittest.TestCase):
    def setUp(self):
        self.window = SpectraMapWindow()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def settle_page(self, expected):
        deadline = time.monotonic() + 3
        while len(self.window.wafer_plots) < expected and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.005)
        self.assertEqual(len(self.window.wafer_plots), expected)

    def test_one_map_per_wafer_and_only_checked_files_make_points(self):
        spectra = (
            make_spectrum(1, wafer="W1"),
            make_spectrum(2, wafer="W1"),
            make_spectrum(1, wafer="W2"),
        )
        self.window.set_data(
            spectra,
            checked_keys={spectrum.key for spectrum in spectra},
        )
        self.assertEqual(self.window.wafer_count, 2)
        self.assertEqual(self.window.point_count, 3)

        self.window.set_data(spectra, checked_keys={spectra[0].key})
        self.assertEqual(self.window.wafer_count, 2)
        self.assertEqual(self.window.point_count, 1)

    def test_pages_contain_at_most_twelve_wafer_maps(self):
        spectra = tuple(
            make_spectrum(1, wafer=f"W{index:02d}")
            for index in range(1, 14)
        )
        self.window.set_data(
            spectra,
            checked_keys={spectrum.key for spectrum in spectra},
        )
        self.assertEqual(self.window.wafer_count, 13)
        self.assertEqual(self.window.page_count, 2)
        self.settle_page(12)
        self.window.change_page(1)
        self.settle_page(1)

    def test_full_page_is_built_in_responsive_batches(self):
        spectra = tuple(
            make_spectrum(1, wafer=f"W{index:02d}")
            for index in range(1, 13)
        )
        self.window.set_data(
            spectra,
            checked_keys={spectrum.key for spectrum in spectra},
        )
        self.assertLess(len(self.window.wafer_plots), 12)
        self.settle_page(12)

    def test_identical_coordinates_render_one_point_for_multiple_spectra(self):
        first = make_spectrum(1, wafer="W1")
        second = replace(
            make_spectrum(2, wafer="W1"),
            x_mm=first.x_mm,
            y_mm=first.y_mm,
        )
        self.window.set_data(
            (first, second),
            checked_keys={first.key, second.key},
        )
        self.assertEqual(self.window.point_count, 1)
        self.settle_page(1)
        self.assertEqual(len(self.window.wafer_plots[("W1", "L1", "P1")].scatter.data), 1)

    def test_selecting_a_spectrum_reuses_the_current_wafer_plot(self):
        spectrum = make_spectrum(1, wafer="W1")
        self.window.set_data(
            (spectrum,),
            checked_keys={spectrum.key},
        )
        self.settle_page(1)
        plot = self.window.wafer_plots[("W1", "L1", "P1")]
        self.window.select_spectrum_keys({spectrum.key})
        self.assertIs(self.window.wafer_plots[("W1", "L1", "P1")], plot)
        self.assertEqual(len(plot.selection.data["x"]), 1)

    def test_left_drag_selects_point_clusters_without_zoom_and_modifiers_add_points(self):
        spectra = tuple(replace(make_spectrum(i + 1), x_mm=x, y_mm=y)
                        for i, (x, y) in enumerate(((-20, -10), (20, 10), (0, 30), (-20, -10))))
        self.window.set_data(spectra, checked_keys={s.key for s in spectra})
        self.window.show()
        self.settle_page(1)
        APP.processEvents()
        plot = self.window.wafer_plots[("W1", "L1", "P1")]
        view = plot.plot.getViewBox()
        ranges = view.viewRange()
        selected = []
        self.window.spectra_selected.connect(lambda keys: selected.append(set(keys)))

        def drag(start, end, modifiers=Qt.KeyboardModifier.NoModifier):
            a = plot.plot.mapFromScene(view.mapViewToScene(QPointF(*start)))
            b = plot.plot.mapFromScene(view.mapViewToScene(QPointF(*end)))
            QTest.mousePress(plot.plot.viewport(), Qt.MouseButton.LeftButton, modifiers, pos=a)
            QTest.mouseMove(plot.plot.viewport(), ((QPointF(a) + QPointF(b)) / 2).toPoint(), delay=25)
            QTest.qWait(30)
            QTest.mouseMove(plot.plot.viewport(), b, delay=25)
            QTest.qWait(30)
            QTest.mouseRelease(plot.plot.viewport(), Qt.MouseButton.LeftButton, modifiers, pos=b)
            QTest.qWait(30)

        drag((-30, -20), (30, 20))
        self.assertEqual(selected[-1], {spectra[i].key for i in (0, 1, 3)})
        self.assertEqual(len(plot.selection.data), 2)
        self.assertEqual(view.viewRange(), ranges)
        drag((10, 40), (-10, 25), Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(selected[-1], {s.key for s in spectra})
        drag((-10, 25), (10, 40))
        self.assertEqual(selected[-1], {spectra[2].key})
        drag((-30, -20), (-10, 0), Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(selected[-1], {spectra[i].key for i in (0, 2, 3)})
        drag((30, -40), (40, -30))
        self.assertEqual(selected[-1], set())
        self.assertEqual(view.viewRange(), ranges)

    def test_map_uses_equal_aspect_and_infers_common_wafer_diameters(self):
        small = replace(make_spectrum(1, wafer="W1"), x_mm=40.0, y_mm=0.0)
        large = replace(make_spectrum(1, wafer="W2"), x_mm=125.0, y_mm=0.0)
        self.window.resize(1000, 760)
        self.window.show()
        self.window.set_data(
            (small, large),
            checked_keys={small.key, large.key},
        )
        self.settle_page(2)
        first = self.window.wafer_plots[("W1", "L1", "P1")]
        second = self.window.wafer_plots[("W2", "L1", "P1")]
        self.assertTrue(first.plot.getPlotItem().getViewBox().state["aspectLocked"])
        self.assertEqual(first.wafer_diameter, 100)
        self.assertEqual(second.wafer_diameter, 300)
        self.assertEqual(first.plot.width(), first.plot.height())
        self.assertEqual(first.plot.getAxis("left").labelText, "")
        self.assertEqual(first.plot.getAxis("bottom").labelText, "X (mm)")
        self.assertTrue(first.plot.getAxis("top").isVisible())
        self.assertTrue(first.plot.getAxis("right").isVisible())
        for point_plot in (first, second):
            point_plot.plot.grab()
            x, y = point_plot.scatter.getData()
            marker = point_plot.plot.getViewBox().mapViewToScene(QPointF(float(x[0]), float(y[0])))
            self.assertAlmostEqual(point_plot.labels[0].sceneBoundingRect().top() - marker.y(), 8, places=3)

    def test_same_wafer_with_different_lot_or_pad_has_separate_outlined_maps(self):
        spectra = (make_spectrum(1), make_spectrum(1, lot="L2"),
                   make_spectrum(1, pad="P2"))
        self.window.set_data(spectra, checked_keys={s.key for s in spectra})
        self.assertEqual(self.window.wafer_count, 3)
        self.assertEqual(self.window.point_count, 3)
        self.settle_page(3)
        plot = self.window.wafer_plots[("W1", "L1", "P1")]
        self.assertEqual(plot.plot.getPlotItem().titleLabel.text, "W1 · L1 · P1")
        outline = [item for item in plot.plot.listDataItems()
                   if isinstance(item, pg.PlotDataItem)]
        self.assertEqual(len(outline), 1)
        x, y = outline[0].getData()
        self.assertAlmostEqual(float(np.max(np.hypot(x, y))), plot.wafer_diameter / 2)
        self.assertEqual(plot.labels[0].toPlainText(), "1")


if __name__ == "__main__":
    unittest.main()
