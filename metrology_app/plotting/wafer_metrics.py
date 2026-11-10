"""Selectable single-wafer summary charts with a shared categorical X axis."""

from math import ceil, floor

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QFontMetrics

from ..mark2_plotting import set_hierarchy_axis
from ..wafer_metrics import METRIC_PLOTS
from .interactive import InteractivePlotWidget, place_legend_above_frame


class _MetricCategoryAxis(pg.AxisItem):
    """Keep category ticks in place and rotate only their text."""

    def __init__(self):
        super().__init__(orientation="bottom")
        self._labels = None
        self.setStyle(autoExpandTextSpace=False)

    def set_labels(self, ticks, rotated, text_extent):
        labels = (ticks, rotated, text_extent)
        if labels != self._labels:
            self._labels = labels
            self.setStyle(tickTextHeight=text_extent + 4)
            self.setTicks([ticks])

    def drawPicture(self, painter, axis_spec, tick_specs, text_specs):
        if self._labels is None or not self._labels[1]:
            super().drawPicture(painter, axis_spec, tick_specs, text_specs)
            return
        super().drawPicture(painter, axis_spec, tick_specs, [])
        ticks, _, text_extent = self._labels
        low, high = self.range
        if high == low:
            return
        bounds = self.mapRectFromParent(self.geometry())
        _, start, _end = axis_spec
        scale = bounds.width() / (high - low)
        height = painter.fontMetrics().height()
        y = start.y() + max(0, self.style["tickLength"]) + 3
        for index, label in ticks:
            painter.save()
            painter.translate(bounds.left() + (index - low) * scale, y)
            painter.rotate(90)
            painter.drawText(QRectF(0, -height / 2, text_extent, height),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
            painter.restore()


class WaferMetricPlot(InteractivePlotWidget):
    pointSelected = pyqtSignal(int)
    enlargeRequested = pyqtSignal()

    def __init__(self, **kwargs):
        self._category_axis = _MetricCategoryAxis()
        super().__init__(axisItems={"bottom": self._category_axis}, **kwargs)
        self._category_axis.setTickFont(self.font())
        self._labels = ()
        self._label_width = 0
        self._curves = []
        self.highlight = None
        self.enlarge_on_double_click = False
        self.view_box.sigResized.connect(self._update_ticks)
        self.view_box.sigXRangeChanged.connect(self._update_ticks)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.enlarge_on_double_click:
                self.enlargeRequested.emit()
            else:
                self.view_box.autoRange()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def set_summary(self, key, summary, category, value_label, *, hierarchy_columns=()):
        title, columns, colors = METRIC_PLOTS[key]
        self.setTitle(title)
        if len(hierarchy_columns) > 1:
            set_hierarchy_axis(self, hierarchy_columns, summary["Metrics Labels"], origin=0)
        else:
            if self.getAxis("bottom") is not self._category_axis:
                self.setAxisItems({"bottom": self._category_axis})
            self.setLabel("bottom", category)
        self.setLabel("left", title)
        names = (value_label, "REF") if len(columns) == 2 else (title,)
        if not self._curves:
            if len(columns) == 2:
                place_legend_above_frame(self)
            for name, color in zip(names, colors):
                curve = self.plot(pen=pg.mkPen(color, width=2), connect="finite", name=name,
                                  symbol="o", symbolSize=7, symbolBrush=color, symbolPen=None,
                                  hoverable=True, tip=self._point_tip)
                curve.sigPointsClicked.connect(self._point_clicked)
                self._curves.append(curve)
            self.highlight = pg.ScatterPlotItem(size=14, pen=pg.mkPen("#dc2626", width=2),
                                                brush=pg.mkBrush(None))
            self.highlight.setZValue(10)
            self.highlight.sigClicked.connect(self._point_clicked)
            self.addItem(self.highlight, ignoreBounds=True)
        legend = self.getPlotItem().legend
        if legend is not None:
            for curve, name in zip(self._curves, names):
                legend.getLabel(curve).setText(name)
            place_legend_above_frame(self)
        labels = tuple(str(label).replace("\n", "/") for label in summary["Wafer"])
        labels_changed = labels != self._labels
        if labels_changed:
            self._labels = labels
            font = QFontMetrics(self.font())
            self._label_width = max(map(font.horizontalAdvance, labels), default=0)
        positions = np.arange(len(labels))
        for curve, column in zip(self._curves, columns):
            values = summary[column].to_numpy(float)
            curve.setData(positions, values, data=positions, symbol="o" if np.isfinite(values).any() else None)
        if labels_changed:
            self.set_auto_x_range((-.5, max(1, len(labels)) - .5))
            self.setXRange(-.5, max(1, len(labels)) - .5, padding=0)
        self._update_ticks()

    def highlight_row(self, row):
        if self.highlight is None:
            return
        values = [] if row is None else [curve.yData[row] for curve in self._curves]
        valid = [value for value in values if np.isfinite(value)]
        self.highlight.setData([row] * len(valid), valid, data=[row] * len(valid))

    def _point_clicked(self, _curve, points, _event):
        if len(points):
            self.pointSelected.emit(int(points[0].data()))

    def _point_tip(self, _x, y, index):
        return f"{self._labels[index]}\n{y:.8g}"

    def _update_ticks(self, *_args):
        if self.getAxis("bottom") is not self._category_axis:
            return
        left, right = self.view_box.viewRange()[0]
        first, last = max(0, ceil(left)), min(len(self._labels) - 1, floor(right))
        width = max(1, int(self.view_box.width()))
        font = QFontMetrics(self.font())
        horizontal_spacing = self._label_width + 8
        rotated = first <= last and horizontal_spacing * (right - left) > width
        spacing = font.height() + 4 if rotated else horizontal_spacing
        step = max(1, ceil((right - left) * spacing / width))
        max_text = max(font.height(), int(self.height() * .42)) if rotated else width
        ticks = [(index, font.elidedText(self._labels[index], Qt.TextElideMode.ElideRight, max_text))
                 for index in range(first, last + 1, step)]
        text_extent = min(max_text, self._label_width) if rotated else font.height()
        self._category_axis.set_labels(ticks, rotated, text_extent)
