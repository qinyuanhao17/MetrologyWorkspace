"""Persistent Highlight is distinct from ordinary selection and source colors."""
import unittest
import time
import gc
import weakref
from dataclasses import replace
import numpy as np
from PyQt6.QtCore import QByteArray, QDataStream, QIODevice, Qt
from PyQt6.QtGui import QColor, QPen
from PyQt6.QtTest import QTest
from metrology_app.spectra_plots import CurveGroup, CurveSegment, SpectrumPlotPanel
from metrology_app.spectra_viewer import SpectraViewerWindow, _line_icon
from metrology_app.sme_spectra import LoadResult
from tests.test_spectra_viewer import APP, make_spectrum


def component_pen(component):
    stream = QDataStream(QByteArray(component[2]), QIODevice.OpenModeFlag.ReadOnly)
    pen = QPen()
    stream >> pen
    return pen


class HighlightStyleTests(unittest.TestCase):
    def setUp(self):
        self.panel = SpectrumPlotPanel('Highlight', dual=True)
        self.panel.apply_theme(self.panel.palette())
        self.x = np.linspace(200, 900, 3001)
        self.y = np.sin(self.x / 30)
        self.y[100:105] = np.nan

    def tearDown(self):
        self.panel.cancel_rendering()
        self.panel.close()
        self.panel.deleteLater()
        APP.processEvents()

    def groups(self, count):
        return [CurveGroup(f'g-{i}', QColor('#e377c2'),
                (CurveSegment(f's-{i}', self.x, self.y),)) for i in range(count)]

    def test_highlight_is_one_two_stroke_overlay_per_axis_in_both_render_paths(self):
        for count in (3, 64):
            with self.subTest(groups=count):
                self.panel.set_curves(self.groups(count), secondary=self.groups(count))
                ordinary = tuple(self.panel._curve_items)
                buffers = [(c.xData, c.yData, c.screen_cache._revision) for c in ordinary]
                self.panel.set_emphasized_keys({'s-0', 's-2'})
                self.assertEqual(len(self.panel._emphasis_items), 2)
                for item in self.panel._emphasis_items:
                    components = item.raster_components()
                    self.assertEqual(len(components), 2)
                    halo, core = map(component_pen, components)
                    self.assertEqual((halo.color().name(), halo.widthF(), halo.color().alpha()),
                                     ('#ffffff', 7.5, 255))
                    self.assertEqual((core.color().name(), core.widthF(), core.color().alpha()),
                                     ('#ff3d00', 3.2, 255))
                    self.assertEqual(halo.style(), Qt.PenStyle.SolidLine)
                    self.assertEqual(core.style(), Qt.PenStyle.SolidLine)
                    self.assertIs(components[0][0], components[1][0])
                    self.assertIs(components[0][1], components[1][1])
                    self.assertTrue(np.isnan(components[0][1]).any())
                    self.assertGreater(item.zValue(), max(c.zValue() for c in ordinary))
                    self.assertEqual({s.spectrum_key for s in item._segments}, {'s-0', 's-2'})
                    self.assertTrue(all(s.x is self.x and s.y is self.y for s in item._segments))
                for item, (x, y, revision) in zip(ordinary, buffers):
                    self.assertIs(item.xData, x)
                    self.assertIs(item.yData, y)
                    self.assertEqual(item.screen_cache._revision, revision)
                    self.assertAlmostEqual(item.screen_cache.display_opacity, 128 / 255)
                self.panel.set_emphasized_keys(set())
                self.assertFalse(self.panel._emphasis_items)
                for item in ordinary:
                    self.assertEqual(item.screen_cache.display_opacity, 1)
                    self.assertEqual(item.opts['pen'].widthF(), 1.8)

    def test_ordinary_selection_keeps_original_color_and_width(self):
        self.panel.set_curves(self.groups(3), selected_keys={'s-0'})
        item = self.panel._highlight_items[0]
        self.assertEqual(item.opts['pen'].color().name(), '#e377c2')
        self.assertEqual(item.opts['pen'].widthF(), 5)

    def test_either_axis_highlight_is_above_both_axes_in_actual_scene_order(self):
        from PyQt6.QtCore import QPointF
        self.panel.resize(800, 500)
        self.panel.show()
        x = np.linspace(200, 900, 903)
        primary = [CurveGroup('primary', QColor('magenta'),
                              (CurveSegment('primary', x, np.zeros_like(x)),))]
        secondary = [CurveGroup('secondary', QColor('blue'),
                                (CurveSegment('secondary', x, np.zeros_like(x)),))]
        self.panel.set_curves(primary, secondary=secondary)
        self.panel.plot.setXRange(200, 900, padding=0)
        self.panel.plot.setYRange(-1, 1, padding=0)
        self.panel.secondary.setYRange(-1, 1, padding=0)
        for key in ('primary', 'secondary'):
            self.panel.set_emphasized_keys({key})
            APP.processEvents()
            position = self.panel.plot.getViewBox().mapViewToScene(QPointF(500, 0))
            stack = self.panel.plot.scene().items(position)
            foreground = self.panel._emphasis_items[0]
            self.assertLess(stack.index(foreground),
                            min(stack.index(item) for item in self.panel._curve_items), key)
            if key == 'secondary':
                self.panel.plot.setXRange(300, 600, padding=0)
                self.panel.secondary.setYRange(-3, 3, padding=0)
                APP.processEvents()
                self.assertEqual(foreground.getViewBox().viewRange(), self.panel.secondary.viewRange())
        self.panel.plot.setXRange(300, 600, padding=0)
        self.panel.secondary.setYRange(-.5, .7, padding=0)
        APP.processEvents()
        self.assertEqual(foreground.getViewBox().viewRange(), self.panel.secondary.viewRange())

    def test_highlight_does_not_change_manual_ranges_or_leak_scene_items(self):
        self.panel.set_curves(self.groups(64), secondary=self.groups(64))
        self.panel.plot.setXRange(300, 600, padding=0)
        self.panel.plot.setYRange(-.3, .8, padding=0)
        self.panel.secondary.setYRange(-.5, .5, padding=0)
        before = self.panel.plot.getViewBox().viewRange(), self.panel.secondary.viewRange()
        count = len(self.panel.plot.scene().items())
        for _ in range(40):
            self.panel.set_emphasized_keys({'s-0', 's-2'})
            self.panel.set_emphasized_keys(set())
        APP.processEvents()
        self.assertEqual(len(self.panel.plot.scene().items()), count)
        self.assertEqual((self.panel.plot.getViewBox().viewRange(), self.panel.secondary.viewRange()), before)

    def test_batched_highlight_cache_matches_native_stroke_compositing(self):
        self.panel.resize(800, 500)
        self.panel.show()
        self.panel.set_curves(self.groups(40))
        self.panel.set_emphasized_keys({'s-0', 's-2'})
        deadline = time.monotonic() + 20
        QTest.qWait(40)
        while self.panel.render_pending and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertFalse(self.panel.render_pending)
        cached = self.panel.plot.grab().toImage()
        for item in self.panel.plot.listDataItems():
            item.setExportMode(True, {'antialias': True})
        native = self.panel.plot.grab().toImage()
        a = np.frombuffer(cached.constBits().asstring(cached.sizeInBytes()), dtype=np.uint8).astype(int)
        b = np.frombuffer(native.constBits().asstring(native.sizeInBytes()), dtype=np.uint8).astype(int)
        self.assertLessEqual(np.abs(a - b).max(), 4)
        self.assertLess(np.abs(a - b).mean(), .05)

    def test_secondary_highlight_cache_matches_full_native_export(self):
        self.panel.resize(800, 500)
        self.panel.show()
        self.panel.set_curves(self.groups(40), secondary=self.groups(40))
        self.panel.set_emphasized_keys({'s-0', 's-2'})
        deadline = time.monotonic() + 20
        QTest.qWait(40)
        while self.panel.render_pending and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertFalse(self.panel.render_pending)
        cached = self.panel.plot.grab().toImage()
        for item in (*self.panel._curve_items, *self.panel._emphasis_items):
            item.setExportMode(True, {'antialias': True})
        native = self.panel.plot.grab().toImage()
        a = np.frombuffer(cached.constBits().asstring(cached.sizeInBytes()), dtype=np.uint8).astype(int)
        b = np.frombuffer(native.constBits().asstring(native.sizeInBytes()), dtype=np.uint8).astype(int)
        self.assertLessEqual(np.abs(a - b).max(), 4)
        self.assertLess(np.abs(a - b).mean(), .05)

    def test_dark_background_keeps_a_light_halo_and_fixed_core(self):
        self.panel.plot.setBackground('#161b22')
        self.panel.set_curves(self.groups(2))
        self.panel.set_emphasized_keys({'s-0'})
        halo, core = map(component_pen, self.panel._emphasis_items[0].raster_components())
        self.assertEqual(halo.color().name(), '#e6edf3')
        self.assertEqual(core.color().name(), '#ff3d00')

    def test_disposed_overlay_and_cache_are_released_after_repeated_highlights(self):
        self.panel.set_curves(self.groups(40), secondary=self.groups(40))
        references = []
        for _ in range(12):
            self.panel.set_emphasized_keys({'s-0'})
            for item in self.panel._emphasis_items:
                references.extend((weakref.ref(item), weakref.ref(item.screen_cache)))
            references.append(weakref.ref(self.panel._secondary_emphasis))
            self.panel.set_emphasized_keys(set())
        del item
        QTest.qWait(1)
        gc.collect()
        self.assertTrue(all(reference() is None for reference in references))

    def test_small_highlight_is_visible_while_its_background_raster_is_pending(self):
        self.panel.set_curves(self.groups(64))
        self.panel.set_emphasized_keys({'s-0'})
        overlay = self.panel._emphasis_items[0]
        self.assertIsNone(overlay.screen_cache._cached)
        self.assertEqual(overlay.opacity(), 1)
        self.assertTrue(overlay.render_pending)


class ViewerHighlightTests(unittest.TestCase):
    def test_unpinned_die_map_does_not_raise_when_spectra_viewer_is_activated(self):
        from unittest.mock import patch
        from PyQt6.QtCore import QEvent
        from PyQt6.QtWidgets import QApplication
        mapping = self.window.open_wafer_map()
        APP.processEvents()
        mapping.window_pin.raise_timer.stop()
        with patch.object(mapping, 'raise_') as raised, \
             patch.object(QApplication, 'applicationState', return_value=Qt.ApplicationState.ApplicationActive), \
             patch.object(QApplication, 'activeWindow', return_value=self.window):
            APP.sendEvent(self.window, QEvent(QEvent.Type.WindowActivate))
            APP.processEvents()
            raised.assert_not_called()
            mapping.window_pin.action.trigger()
            APP.processEvents()
            raised.assert_called_once()
            raised.reset_mock()
            mapping.window_pin.action.trigger()
            APP.sendEvent(self.window, QEvent(QEvent.Type.WindowActivate))
            APP.processEvents()
            raised.assert_not_called()

    def setUp(self):
        self.window = SpectraViewerWindow()
        self.sources = tuple(make_spectrum(i + 1, wafer='W1' if i < 2 else 'W2') for i in range(3))
        self.window.apply_load_result(LoadResult(self.sources, ()), replace=True)
        self.window.check_all_spectra()

    def tearDown(self):
        self.window.document.force_close = True
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def test_highlight_syncs_all_mueller_axes_and_floating_plot_in_both_color_modes(self):
        floating = self.window.open_plot_window(self.window.plot_panels['psi_delta'])
        for mode in ('wafer', 'sme'):
            self.window.set_color_mode(mode)
            self.window.select_spectrum_keys({self.sources[0].key, self.sources[2].key})
            self.window.highlight_selected_spectra(True)
            self.window.select_spectrum_keys(set())
            for panel in (*self.window.mueller_panel.mij_plots.values(),
                          *self.window.plot_panels.values(), floating.panel):
                if panel._all_groups:
                    self.assertTrue(panel._emphasis_items, panel.title)
                    for item in panel._emphasis_items:
                        self.assertEqual(component_pen(item.raster_components()[1]).color().name(), '#ff3d00')
            self.window.select_spectrum_keys({self.sources[0].key, self.sources[2].key})
            self.window.highlight_selected_spectra(False)

    def test_legend_highlight_icon_has_white_halo_and_bright_core(self):
        icon = _line_icon(QColor('#e377c2'), highlighted=True).pixmap(24, 14).toImage()
        self.assertEqual(icon.pixelColor(12, 7).name(), '#ff3d00')
        self.assertEqual(icon.pixelColor(12, 4).name(), '#ffffff')

    def test_persistent_highlight_changes_die_point_color_and_undo_restores_it(self):
        mapping = self.window.open_wafer_map()
        APP.processEvents()
        selected = self.sources[0].key
        self.window.select_spectrum_keys({selected})
        self.window.highlight_selected_spectra(True)
        self.window.select_spectrum_keys(set())
        plot = next(p for p in mapping.wafer_plots.values()
                    if any(selected in keys for keys in p._spot_keys))
        point = next(p for p in plot.scatter.points() if selected in p.data()['keys'])
        self.assertEqual(point.brush().color().name(), '#ff3d00')
        self.assertEqual(point.pen().color().name(), '#202020')
        self.assertEqual(point.pen().widthF(), .8)
        self.assertEqual(point.size(), 12)
        self.assertFalse(mapping._selected_keys)
        self.window.undo_action.trigger()
        self.assertEqual(point.brush().color().name(), '#3e8bd8')

    def test_clear_all_highlights_works_without_selection_and_can_be_undone(self):
        selected = {self.sources[0].key, self.sources[2].key}
        self.window.select_spectrum_keys(selected)
        self.window.highlight_selected_spectra(True)
        self.window.select_spectrum_keys(set())
        action = next(a for a in self.window.build_tree_menu().actions() if a.text() == 'Clear Highlight')
        self.assertTrue(action.isEnabled())
        action.trigger()
        self.assertFalse(self.window.highlighted_keys)
        self.assertTrue(all(not p._emphasis_items for p in self.window.mueller_panel.mij_plots.values()))
        self.window.undo_action.trigger()
        self.assertEqual(self.window.highlighted_keys, selected)
        self.window.redo_action.trigger()
        self.assertFalse(self.window.highlighted_keys)
        self.assertFalse(next(a for a in self.window.build_tree_menu().actions() if a.text() == 'Clear Highlight').isEnabled())

    def test_three_sigma_highlight_reuses_aggregate_segments_and_preserves_source_samples(self):
        originals = [s.channels[0].numeric.copy() for s in self.sources]
        self.window.set_analysis_mode('3sigma')
        panel = self.window.plot_panels['S']
        aggregate = panel.groups[0].segments[0]
        self.window.select_spectrum_keys({self.sources[0].key})
        self.window.highlight_selected_spectra(True)
        self.window.select_spectrum_keys(set())
        self.assertIs(panel._emphasis_items[0]._segments[0], aggregate)
        for source, expected in zip(self.sources, originals):
            np.testing.assert_array_equal(source.channels[0].numeric, expected)

    def test_reflectance_and_legend_keep_highlight_after_selection_is_cleared(self):
        source = self.sources[0]
        source = replace(source, channels=(replace(source.channels[0], spectrum_type='reflectance',
                                                   numeric=source.channels[0].numeric[:, :2]),))
        self.window.apply_load_result(LoadResult((source,), ()), replace=True)
        self.window.check_all_spectra()
        self.window.select_spectrum_keys({source.key})
        self.window.highlight_selected_spectra(True)
        self.window.select_spectrum_keys(set())
        self.assertTrue(self.window.plot_panels['reflectance']._emphasis_items)
        legend = self.window.legends['Reflectance']
        self.assertTrue(legend.item(0).font().bold())
        self.assertFalse(legend.item(0).isSelected())
