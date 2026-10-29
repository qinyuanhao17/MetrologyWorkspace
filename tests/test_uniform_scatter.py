"""Uniform scatter updates reuse symbols without losing native point/style data."""
import unittest
from unittest.mock import patch
from hashlib import sha256

import numpy as np
import pyqtgraph as pg
from pyqtgraph.graphicsItems.ScatterPlotItem import SymbolAtlas
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from metrology_app.plotting.curve import ResponsivePlotDataItem

APP = QApplication.instance() or QApplication([])


class UniformScatterTests(unittest.TestCase):
    def test_opt_in_initial_data_also_prepares_only_one_symbol_key(self):
        x = np.arange(10000.)
        calls = []
        original = SymbolAtlas._keys
        def count(atlas, styles):
            calls.append(len(styles))
            return original(atlas, styles)
        with patch.object(SymbolAtlas, '_keys', count):
            item = ResponsivePlotDataItem(x, np.sin(x), pen=None, symbol='o', symbolSize=5,
                                         symbolPen=None, symbolBrush=pg.mkBrush('#5b9bd5'),
                                         broadcast_uniform_symbols=True)
        self.assertTrue(calls)
        self.assertLessEqual(max(calls), 1)
        np.testing.assert_array_equal(item.scatter.getData()[0], x)
        np.testing.assert_array_equal(item.scatter.getData()[1], np.sin(x))

    def test_opt_in_broadcast_enumerates_one_style_but_keeps_every_native_point(self):
        x = np.arange(10000.)
        item = ResponsivePlotDataItem(x, np.sin(x), pen=None, symbol='o', symbolSize=5,
                                     symbolPen=None, symbolBrush=pg.mkBrush('#5b9bd5'),
                                     broadcast_uniform_symbols=True)
        columns = list(item.scatter._style(['symbol', 'size', 'pen', 'brush']))
        self.assertEqual([len(column) for column in columns], [1] * 4)
        item.setData(x, np.cos(x))
        self.assertEqual(len(item.scatter.points()), 10000)
        np.testing.assert_array_equal(item.scatter.getData()[0], x)
        np.testing.assert_array_equal(item.scatter.getData()[1], np.cos(x))
        self.assertTrue(np.all(item.scatter.data['sourceRect']['w'] > 0))
        item.setData(x[:2], x[:2], symbol=['o', 't'])
        columns = list(item.scatter._style(['symbol', 'size', 'pen', 'brush']))
        self.assertEqual([len(column) for column in columns], [2] * 4)

    def test_uniform_update_prepares_one_atlas_key_for_all_native_points(self):
        x = np.arange(1024.)
        item = ResponsivePlotDataItem(x, np.sin(x), pen=None, symbol='o', symbolSize=5,
                                     symbolPen=None, symbolBrush=pg.mkBrush('#5b9bd5'))
        calls = []
        original = SymbolAtlas._keys
        def count(atlas, styles):
            calls.append(len(styles))
            return original(atlas, styles)
        with patch.object(SymbolAtlas, '_keys', count):
            item.setData(x, np.cos(x))
        self.assertTrue(calls)
        self.assertLessEqual(max(calls), 1, 'identical symbols must not make a key for every data point')
        np.testing.assert_array_equal(item.scatter.data['x'], x)
        np.testing.assert_array_equal(item.scatter.data['y'], np.cos(x))
        self.assertEqual(len(item.scatter.points()), 1024)

    def image(self, item):
        widget = pg.PlotWidget(background='w')
        try:
            widget.resize(480, 320)
            widget.hideAxis('left')
            widget.hideAxis('bottom')
            widget.setRange(xRange=(-1, 21), yRange=(-1.3, 1.3), padding=0)
            widget.addItem(item)
            image = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
            return sha256(image.constBits().asstring(image.sizeInBytes())).hexdigest()
        finally:
            widget.deleteLater()
            APP.processEvents()

    def test_native_pixels_and_point_values_match_for_uniform_and_varied_styles(self):
        x = np.arange(21.)
        y = np.sin(x)
        for varied, broadcast in ((False, False), (False, True), (True, False), (True, True)):
            with self.subTest(varied=varied, broadcast=broadcast):
                style = {'pen': None, 'symbol': 'o', 'symbolSize': 5, 'symbolPen': None,
                         'symbolBrush': pg.mkBrush('#5b9bd5')}
                if varied:
                    style.update(symbol=['o', 't', 's'] * 7,
                                 symbolSize=np.tile([3., 5., 7.], 7),
                                 symbolBrush=[pg.mkBrush(c) for c in ['#5b9bd5', '#ed7d31', '#009e73'] * 7])
                expected = pg.PlotDataItem(x, y, **style)
                actual = ResponsivePlotDataItem(x, y, broadcast_uniform_symbols=broadcast, **style)
                expected.setData(x, -y)
                actual.setData(x, -y)
                np.testing.assert_array_equal(expected.scatter.data['x'], actual.scatter.data['x'])
                np.testing.assert_array_equal(expected.scatter.data['y'], actual.scatter.data['y'])
                self.assertEqual(self.image(expected), self.image(actual))

    def test_style_changes_and_atlas_clear_preserve_native_pixels(self):
        x = np.arange(21.)
        style = {'pen': None, 'symbol': 'o', 'symbolSize': 5, 'symbolPen': None,
                 'symbolBrush': pg.mkBrush('#5b9bd5')}
        expected, actual = pg.PlotDataItem(x, np.sin(x), **style), ResponsivePlotDataItem(x, np.sin(x), **style)
        for item in (expected, actual):
            item.setData(x, np.sin(x), symbolBrush=pg.mkBrush('#009e73'),
                         symbolPen=pg.mkPen('#111111', width=1), symbolSize=9)
            item.scatter.fragmentAtlas.clear()
            item.scatter.data['sourceRect'] = 0
            item.scatter.updateSpots()
        self.assertEqual(self.image(expected), self.image(actual))

    def test_opt_in_atlas_keeps_native_pixels_after_style_dpr_and_size_changes(self):
        x = np.arange(21.)
        style = {'pen': None, 'symbol': 'o', 'symbolSize': 5, 'symbolPen': None,
                 'symbolBrush': pg.mkBrush('#5b9bd5')}
        expected = pg.PlotDataItem(x, np.sin(x), **style)
        actual = ResponsivePlotDataItem(x, np.sin(x), broadcast_uniform_symbols=True, **style)
        for size, colour, dpr, rows in ((9, '#009e73', 1, 21), (4, '#ed7d31', 2, 13),
                                       (7, '#5b9bd5', 1, 21)):
            for item in (expected, actual):
                item.setData(x[:rows], np.cos(x[:rows]), symbolBrush=pg.mkBrush(colour),
                             symbolPen=pg.mkPen('#111111', width=1), symbolSize=size)
                item.scatter.fragmentAtlas.setDevicePixelRatio(dpr)
                item.scatter.fragmentAtlas.clear()
                item.scatter.data['sourceRect'] = 0
                item.scatter.updateSpots()
            np.testing.assert_array_equal(expected.scatter.data['x'], actual.scatter.data['x'])
            np.testing.assert_array_equal(expected.scatter.data['y'], actual.scatter.data['y'])
            self.assertEqual(len(actual.scatter.points()), rows)
            self.assertEqual(self.image(expected), self.image(actual))

    def test_opt_in_hover_and_scaled_styles_fall_back_to_full_native_enumeration(self):
        x = np.arange(21.)
        style = {'pen': None, 'symbol': 'o', 'symbolSize': 5, 'symbolPen': None,
                 'symbolBrush': pg.mkBrush('#5b9bd5'), 'hoverable': True,
                 'hoverBrush': pg.mkBrush('#ed7d31'), 'hoverSize': 11}
        # The existing responsive item preserves hover across range changes;
        # bare PlotDataItem clears it while reloading the same display arrays.
        expected = ResponsivePlotDataItem(x, np.sin(x), **style)
        actual = ResponsivePlotDataItem(x, np.sin(x), broadcast_uniform_symbols=True, **style)
        for item in (expected, actual):
            # PlotDataItem does not forward hover kwargs; enable its native
            # scatter explicitly so this really exercises hovered styles.
            item.scatter.setData(x, np.sin(x), hoverable=True,
                                 hoverBrush=pg.mkBrush('#ed7d31'), hoverSize=11)
            self.assertTrue(item.scatter.opts['hoverable'])
            item.scatter.data['hovered'][[1, 3]] = True
            item.scatter.data['sourceRect'] = 0
            item.scatter.updateSpots()
        for scale in (None, 2):
            first = list(expected.scatter._style(['symbol', 'size', 'pen', 'brush'], scale=scale))
            second = list(actual.scatter._style(['symbol', 'size', 'pen', 'brush'], scale=scale))
            self.assertEqual([len(column) for column in second], [21] * 4)
            for a, b in zip(first, second):
                np.testing.assert_array_equal(a, b)
        self.assertEqual(self.image(expected), self.image(actual))
