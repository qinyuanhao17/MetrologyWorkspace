"""Qt integration checks for paginated spectrum wafer maps."""

import os
import time
import unittest
from dataclasses import replace

import numpy as np
import pyqtgraph as pg

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QScrollArea
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtTest import QTest

from metrology_app.spectra_map import SpectraMapWindow
from tests.test_spectra_viewer import make_spectrum


APP = QApplication.instance() or QApplication([])


class SpectraMapWindowTests(unittest.TestCase):
    def test_single_tile_window_has_regular_titles_and_tight_square_coordinate_extent(self):
        source = make_spectrum(1)
        self.window.show()
        self.window.set_data((source,),checked_keys={source.key})
        self.settle_page(1)
        plot = next(iter(self.window.wafer_plots.values()))
        plot.plot.grab(); APP.processEvents()
        self.assertLessEqual(self.window.minimumWidth(),plot.width()+80)
        self.assertLessEqual(self.window.minimumHeight(),plot.height()+144)
        self.assertIn('font-weight: 400',plot.title_label.styleSheet())
        xr,yr = plot.plot.getViewBox().viewRange()
        self.assertAlmostEqual(xr[1]-xr[0],yr[1]-yr[0],delta=2)
        half = plot.wafer_diameter/2
        self.assertLess(yr[1]-half,half*.08)

    def test_pad_outlines_stay_behind_points_and_reuse_geometry_on_check_changes(self):
        from tests.test_spectra_pad_geometry import point
        sources = (point(1, 0, 0, 0, 0), point(2, 1, 0, 20, 0), point(3, 0, 1, 0, 30))
        self.window.set_data(sources, checked_keys={s.key for s in sources})
        self.settle_page(1)
        plot = next(iter(self.window.wafer_plots.values()))
        self.assertEqual((plot.pad_layout.width_mm, plot.pad_layout.height_mm), (20, 30))
        self.assertEqual(plot.pad_edges.opts["pen"].color().name(), "#c4c4c4")
        self.assertLess(plot.pad_edges.zValue(), plot.scatter.zValue())
        radius = plot.wafer_diameter / 2
        for x0, y0, x1, y1 in plot.pad_layout.segments:
            self.assertAlmostEqual(np.hypot(x0, y0), radius)
            self.assertAlmostEqual(np.hypot(x1, y1), radius)
        geometry = plot.pad_edges.xData
        self.window.update_checks({sources[0].key}, selected_keys={sources[1].key})
        self.assertIs(plot.pad_edges.xData, geometry)
        self.assertEqual(len(plot.scatter.points()), 3)

    def test_cards_show_live_point_counts_without_changing_plot_size_or_range(self):
        first, second = make_spectrum(1), make_spectrum(2)
        self.window.set_data((first, second), checked_keys={first.key}, selected_keys={second.key})
        self.settle_page(1)
        plot = next(iter(self.window.wafer_plots.values()))
        self.assertEqual(plot.summary_label.text(), "2 points · 1 checked · 1 selected")
        size, ranges = plot.size(), plot.plot.getViewBox().viewRange()
        self.window.update_checks({first.key, second.key}, selected_keys=set())
        self.assertEqual(plot.summary_label.text(), "2 points · 2 checked · 0 selected")
        self.assertEqual(plot.size(), size)
        self.assertEqual(plot.plot.getViewBox().viewRange(), ranges)
        self.assertEqual(self.window.summary_label.text(), "1 wafer · 2 points")

    def test_blank_scroll_area_clears_selection_without_affecting_checks(self):
        source = make_spectrum(1)
        self.window.show()
        self.window.set_data((source,), checked_keys={source.key}, selected_keys={source.key})
        self.settle_page(1)
        selected = []
        self.window.spectra_selected.connect(selected.append)
        viewport = self.window.scroll_area.viewport()
        QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=QPoint(viewport.width() - 2, 2))
        self.assertEqual(selected[-1], set())
        self.assertEqual(self.window._checked_keys, {source.key})

    def test_check_unselected_applies_only_to_points_in_the_context_wafer(self):
        spectra = (make_spectrum(1), make_spectrum(2), make_spectrum(1, wafer="W2"))
        self.window.set_data(spectra, checked_keys={s.key for s in spectra}, selected_keys={spectra[0].key})
        updates = []
        self.window.checks_changed.connect(updates.append)
        actions = {a.text(): a for a in self.window.build_selection_menu(("W1", "L1", "P1")).actions()}
        actions["Uncheck Unselected"].trigger()
        self.assertEqual(updates[-1], {spectra[1].key: False})
        actions["Check Unselected"].trigger()
        self.assertEqual(updates[-1], {spectra[1].key: True})

    def test_map_tiles_keep_their_size_and_use_scrollbars_when_window_shrinks(self):
        spectra = tuple(make_spectrum(1, wafer=f"W{i}") for i in range(12))
        self.window.show()
        self.window.set_data(spectra, checked_keys={s.key for s in spectra})
        self.settle_page(12)
        QTest.qWait(30)
        sizes = {key: plot.plot.size() for key, plot in self.window.wafer_plots.items()}
        scroll = self.window.findChild(QScrollArea)
        self.assertIsNotNone(scroll)
        self.window.resize(960, 650)
        QTest.qWait(40)
        self.assertEqual({key: plot.plot.size() for key, plot in self.window.wafer_plots.items()}, sizes)
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
        self.assertGreater(scroll.horizontalScrollBar().maximum(), 0)

    def test_check_changes_reuse_plots_ranges_and_unchecked_points(self):
        spectra = (make_spectrum(1), make_spectrum(2))
        self.window.show()
        self.window.set_data(spectra, checked_keys={s.key for s in spectra})
        self.settle_page(1)
        APP.processEvents()
        plot = next(iter(self.window.wafer_plots.values()))
        size, ranges, labels = plot.plot.size(), plot.plot.getViewBox().viewRange(), tuple(plot.labels)
        self.window.set_data(spectra, checked_keys={spectra[1].key})
        APP.processEvents()
        self.assertIs(next(iter(self.window.wafer_plots.values())), plot)
        self.assertEqual(plot.plot.size(), size)
        self.assertEqual(plot.plot.getViewBox().viewRange(), ranges)
        self.assertEqual(tuple(plot.labels), labels)
        self.assertEqual(len(plot.scatter.points()), 2)
        self.assertEqual(plot.scatter.points()[0].brush().color().name(), "#d6d9de")
        self.assertEqual(plot.scatter.points()[1].brush().color().name(), "#3e8bd8")

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

    def test_long_titles_keep_whole_wafers_visible_on_full_pages_and_resize(self):
        spectra = tuple(replace(make_spectrum(die, wafer=f"AI01750.00-{index:02d}", lot="AI01750.00", pad="2026-8-18-15-8-39"),
                                x_mm=x, y_mm=0.0)
                        for index in range(13) for die, x in ((1, -125.0), (2, 125.0)))
        self.window.resize(1600, 1000)
        self.window.show()
        self.window.set_data(spectra, checked_keys={s.key for s in spectra})
        self.settle_page(12)

        def assert_complete():
            QTest.qWait(30)
            self.window.grab()
            for plot in self.window.wafer_plots.values():
                view = plot.plot.getViewBox()
                for x, y in ((-150, 0), (150, 0), (0, -150), (0, 150)):
                    position = plot.plot.mapFromScene(view.mapViewToScene(QPointF(x, y)))
                    self.assertTrue(plot.plot.viewport().rect().contains(position),
                                    f"{plot.wafer}: {position}, viewport {plot.plot.viewport().rect()}")

        assert_complete()
        self.window.resize(960, 650)
        assert_complete()
        self.window.change_page(1)
        self.settle_page(1)
        assert_complete()
        last = next(iter(self.window.wafer_plots.values()))
        self.assertGreater(last.plot.height(), 300)

    def test_one_map_per_wafer_retains_unchecked_points(self):
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
        self.assertEqual(self.window.point_count, 3)

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
        self.window.set_data(spectra, checked_keys=set())
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
        self.assertEqual(first.plot.getAxis("left").labelText, "Y (mm)")
        self.assertEqual(first.plot.getAxis("bottom").labelText, "X (mm)")
        self.assertTrue(first.plot.getAxis("top").isVisible())
        self.assertTrue(first.plot.getAxis("right").isVisible())
        for point_plot in (first, second):
            point_plot.plot.grab()
            x, y = point_plot.scatter.getData()
            marker = point_plot.plot.getViewBox().mapViewToScene(QPointF(float(x[0]), float(y[0])))
            self.assertAlmostEqual(point_plot.labels[0].sceneBoundingRect().top() - marker.y(), 2, places=3)

    def test_same_wafer_with_different_lot_or_pad_has_separate_outlined_maps(self):
        spectra = (make_spectrum(1), make_spectrum(1, lot="L2"),
                   make_spectrum(1, pad="P2"))
        self.window.set_data(spectra, checked_keys={s.key for s in spectra})
        self.assertEqual(self.window.wafer_count, 3)
        self.assertEqual(self.window.point_count, 3)
        self.settle_page(3)
        plot = self.window.wafer_plots[("W1", "L1", "P1")]
        self.assertEqual(plot.title_label.text(), "W1 · L1 · P1")
        outline = [item for item in plot.plot.listDataItems()
                   if isinstance(item, pg.PlotDataItem) and item is not plot.pad_edges]
        self.assertEqual(len(outline), 1)
        x, y = outline[0].getData()
        self.assertAlmostEqual(float(np.max(np.hypot(x, y))), plot.wafer_diameter / 2)
        self.assertEqual(plot.labels[0].toPlainText(), "1")


if __name__ == "__main__":
    unittest.main()
