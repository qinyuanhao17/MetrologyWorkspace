"""Resizable plots remain inside their owning parameter card."""

import os
import json
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QSplitter, QWidget

from metrology_app.plotting.parameter_layout import ParameterPlotArea

APP = QApplication.instance() or QApplication([])


class DragEvent:
    """Qt's synthetic drop constructors cannot supply a drag source."""

    def __init__(self, source, position):
        self._source = source
        self._position = QPointF(position)
        self.accepted = False

    def source(self):
        return self._source

    def position(self):
        return self._position

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.accepted = False


class ParameterPlotLayoutTests(unittest.TestCase):
    def test_plots_resize_and_move_below_a_neighbour_without_leaving_the_area(self):
        plots = {name: QWidget() for name in ("match", "trend", "bias")}
        area = ParameterPlotArea(plots, plot_height=330)
        try:
            area.resize(1400, area.height())
            area.show()
            APP.processEvents()
            width = plots["match"].width()
            splitter = next(s for s in area.findChildren(QSplitter)
                            if s.orientation() == Qt.Orientation.Horizontal)
            self.assertEqual(splitter.handleWidth(), 6)
            handle = splitter.handle(1)
            point = handle.rect().center()
            QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=point)
            QTest.mouseMove(handle, point + QPoint(100, 0))
            QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=point + QPoint(100, 0))
            APP.processEvents()
            self.assertGreater(plots["match"].width(), width + 50)
            height = area.height()
            target = area.docks["trend"]
            event = DragEvent(area.docks["bias"], QPoint(target.width() // 2, target.height() - 2))
            target.dragEnterEvent(event)
            target.dragMoveEvent(event)
            self.assertTrue(event.accepted)
            target.dropEvent(event)
            APP.processEvents()
            self.assertGreater(area.height(), height + 300)
            trend = plots["trend"].mapTo(area, QPoint())
            bias = plots["bias"].mapTo(area, QPoint())
            self.assertGreater(bias.y(), trend.y() + 330)
            self.assertEqual(bias.x(), trend.x())
            self.assertTrue(all(s.handleWidth() == 6 for s in area.findChildren(QSplitter)))
            self.assertTrue(all(area.isAncestorOf(plot) for plot in plots.values()))
            self.assertEqual(plots["match"].height(), 330)
        finally:
            area.close()
            area.deleteLater()
            APP.processEvents()

    def test_layout_round_trip_rejects_detached_or_foreign_plots(self):
        area = ParameterPlotArea({name: QWidget() for name in ("match", "trend", "bias")})
        other = ParameterPlotArea({name: QWidget() for name in ("match", "trend", "bias")})
        try:
            area.resize(1400, area.height())
            area.show()
            APP.processEvents()
            area.moveDock(area.docks["bias"], "bottom", area.docks["trend"])
            APP.processEvents()
            state = area.saveState()
            other.restoreState(json.loads(json.dumps(state)))
            other.resize(1400, other.height())
            other.show()
            APP.processEvents()
            self.assertEqual(other.saveState(), state)
            foreign = DragEvent(area.docks["match"], QPoint(5, 5))
            other.docks["match"].dragEnterEvent(foreign)
            self.assertFalse(foreign.accepted)
            other.moveDock(area.docks["match"], "left", other.docks["trend"])
            self.assertIs(area.docks["match"].area, area)
            QTest.mouseDClick(area.docks["match"].label, Qt.MouseButton.LeftButton)
            self.assertEqual(area.tempAreas, [])
            for invalid in ({"main": state["main"], "float": [[state, [0, 0, 100, 100]]]},
                            {"main": ["dock", "not-a-plot", {}], "float": []}):
                with self.assertRaisesRegex(ValueError, "plot"):
                    other.restoreState(invalid)
                self.assertEqual(other.saveState(), state)
        finally:
            area.close()
            other.close()
            area.deleteLater()
            other.deleteLater()
            APP.processEvents()
