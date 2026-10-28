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
        for varied in (False, True):
            with self.subTest(varied=varied):
                style = {'pen': None, 'symbol': 'o', 'symbolSize': 5, 'symbolPen': None,
                         'symbolBrush': pg.mkBrush('#5b9bd5')}
                if varied:
                    style.update(symbol=['o', 't', 's'] * 7,
                                 symbolSize=np.tile([3., 5., 7.], 7),
                                 symbolBrush=[pg.mkBrush(c) for c in ['#5b9bd5', '#ed7d31', '#009e73'] * 7])
                expected = pg.PlotDataItem(x, y, **style)
                actual = ResponsivePlotDataItem(x, y, **style)
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
