"""Static pyqtgraph radius scatter arrays, with the existing scientific style."""
import numpy as np
import pyqtgraph as pg
from matplotlib.colors import to_rgba
from matplotlib.ticker import AutoLocator, MaxNLocator, ScalarFormatter
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QGraphicsRectItem, QToolTip

from .wafer_graphics import WaferPanel
from .plotting.identity_labels import measurement_caption


class RadiusPanel(pg.GraphicsObject):
    # One shared scientific text style; no coupling to wafer data or surfaces.
    font = staticmethod(WaferPanel.font)
    text = staticmethod(WaferPanel.text)

    def __init__(self, source, parent):
        super().__init__(parent)
        self.source = self._owned_source(source)
        self._source_geometry_changed = True
        self.box = QRectF()
        self.base = 10
        self.identity_labels = {"pad": True, "lot": True}
        self._pixel_positions = np.empty((0, 2))
        self.status_callback = None
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(True)
        self.scatter = None
        if not source.get("skip") and len(source["value"]):
            values = source["value"]
            low, high = AutoLocator().nonsingular(float(values.min()), float(values.max()))
            margin = .05*(high-low)
            self.y_limits = (low-margin, high+margin)
            self.clip = QGraphicsRectItem(self)
            self.clip.setPen(QPen(Qt.PenStyle.NoPen))
            self.clip.setFlag(self.GraphicsItemFlag.ItemClipsChildrenToShape)
            self.clip.setFlag(self.GraphicsItemFlag.ItemStacksBehindParent)
            self.clip.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.zero = pg.PlotCurveItem(pen=pg.mkPen("#707070", width=.7*100/72))
            self.zero.setParentItem(self.clip)
            colour = QColor.fromRgbF(*to_rgba(source["color"]))
            colour.setAlphaF(.78)
            pen = pg.mkPen(QColor(255, 255, 255, round(.78*255)), width=.25*100/72)
            pen.setCosmetic(False)
            self.scatter = pg.ScatterPlotItem(size=4*100/72, pxMode=False, symbol="o",
                                              brush=colour, pen=pen, hoverable=False, antialias=True)
            self.scatter.setParentItem(self.clip)
            self.scatter.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    @staticmethod
    def _owned_source(source):
        # Cache comparisons must describe the previous draw even if a caller
        # later reuses its dict or edits an array in place.
        owned = dict(source)
        for key in ("radius", "value"):
            if key in owned:
                owned[key] = np.array(owned[key], copy=True)
        if "die" in owned:
            owned["die"] = list(owned["die"])
        return owned

    def update_source(self, source):
        """Reuse identical graphics roles; coordinates are rebuilt by relayout."""
        populated = not source.get("skip") and bool(len(source["value"]))
        if populated != (self.scatter is not None):
            return False
        previous = self.source
        self._source_geometry_changed = (populated and (previous["limit"] != source["limit"]
            or not np.array_equal(previous["radius"], source["radius"])
            or not np.array_equal(previous["value"], source["value"])))
        self.source = self._owned_source(source)
        if populated:
            values = source["value"]
            low, high = AutoLocator().nonsingular(float(values.min()), float(values.max()))
            margin = .05*(high-low)
            self.y_limits = low-margin, high+margin
            colour = QColor.fromRgbF(*to_rgba(source["color"]))
            colour.setAlphaF(.78)
            if previous["color"] != source["color"]:
                self.scatter.setBrush(colour)
        self.update()
        return True

    def boundingRect(self):
        return self.box.adjusted(-90, -85, 40, 65)

    def set_geometry(self, box, base, identity_labels):
        if (not self._source_geometry_changed and self.box == box and self.base == base
                and self.identity_labels == identity_labels):
            return
        self._source_geometry_changed = False
        self.prepareGeometryChange()
        self.box, self.base, self.identity_labels = QRectF(box), base, identity_labels
        if self.scatter is not None:
            self.clip.setRect(box)
            limit = self.source["limit"]
            low, high = self.y_limits
            x = box.left()+(self.source["radius"]+limit)/(2*limit)*box.width()
            y = box.bottom()-(self.source["value"]-low)/(high-low)*box.height()
            self.scatter.setData(x=x, y=y)
            self.zero.setData(x=[box.center().x()]*2, y=[box.top(), box.bottom()])
            self._pixel_positions = np.column_stack((x, y)) if len(x) else np.empty((0, 2))
        self.update()

    def hover_text(self, point):
        """Nearest source die showing its value and signed radius."""
        if self.scatter is None or not len(self._pixel_positions):
            return None
        delta = self._pixel_positions - np.array([point.x(), point.y()])
        distances = np.einsum("ij,ij->i", delta, delta)
        index = int(distances.argmin())
        if distances[index] > 10 * 10:
            return None
        source = self.source
        die = str(source.get("die", [""] * len(source["value"]))[index] or "").strip()
        text = [str(source["label"]).replace("\n", " · ")]
        if die:
            text.append(f"Die {die}")
        text.append(f"{source['metric']} = {float(source['value'][index]):.8g}")
        text.append(f"Signed radius = {float(source['radius'][index]):.6g} {source['unit']}")
        return " · ".join(text)

    def hoverMoveEvent(self, event):
        text = self.hover_text(event.pos())
        if text:
            if self.status_callback is not None:
                self.status_callback(text)
            views = self.scene().views() if self.scene() is not None else []
            widget = views[0].viewport() if views else None
            position = event.screenPos()
            QToolTip.showText(position.toPoint() if hasattr(position, "toPoint") else position,
                              text, widget)
        else:
            QToolTip.hideText()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        QToolTip.hideText()
        super().hoverLeaveEvent(event)

    def paint(self, painter, *args):
        if self.source.get("skip"):
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box, base = self.box, self.base
        painter.setPen(QPen(QColor("#303030"), .8*100/72))
        painter.drawRect(box)
        if self.scatter is None:
            painter.setFont(self.font(base))
            self.text(painter, "No valid samples", box)
            return
        detail = max(6, base-1)
        line = detail*1.45*100/72
        bottom = box.top()-5*100/72
        painter.setPen(QColor("#17202a"))
        painter.setFont(self.font(base, True))
        self.text(painter, self.source["metric"], QRectF(box.left()-30, bottom-3*line, box.width()+60, line))
        painter.setFont(self.font(detail))
        caption = measurement_caption(self.source["label"], self.identity_labels).replace("\n", " · ")
        self.text(painter, caption, QRectF(box.left()-30, bottom-2*line, box.width()+60, line))
        self.text(painter, self.source["stats"], QRectF(box.left()-30, bottom-line, box.width()+60, line))
        self._paint_ticks(painter, (-self.source["limit"], self.source["limit"]), horizontal=True)
        self._paint_ticks(painter, self.y_limits, horizontal=False)
        painter.setFont(self.font(max(6, base-1)))
        self.text(painter, f'Signed radius ({self.source["unit"]})',
                  QRectF(box.left(), box.bottom()+25, box.width(), 22))
        painter.save()
        painter.translate(box.left()-52, box.center().y())
        painter.rotate(-90)
        self.text(painter, self.source["metric"], QRectF(-box.height()/2, -12, box.height(), 24))
        painter.restore()

    def _paint_ticks(self, painter, limits, *, horizontal):
        low, high = limits
        size = max(5, self.base-2)
        length = self.box.width() if horizontal else self.box.height()
        bins = int(np.clip(np.floor(length*.72/(size*(3 if horizontal else 2))), 1, 9))
        levels = MaxNLocator(nbins=bins, steps=[1, 2, 2.5, 5, 10]).tick_values(low, high)
        formatter = ScalarFormatter()
        formatter.create_dummy_axis()
        formatter.axis.set_view_interval(low, high)
        formatter.set_locs(levels)
        painter.setFont(self.font(size))
        painter.setPen(QPen(QColor("#303030"), .8*100/72))
        for value in levels:
            if not low <= value <= high:
                continue
            fraction = (value-low)/(high-low)
            if horizontal:
                x = self.box.left()+fraction*self.box.width()
                painter.drawLine(QPointF(x, self.box.bottom()), QPointF(x, self.box.bottom()+3.5))
                painter.drawLine(QPointF(x, self.box.top()), QPointF(x, self.box.top()-3.5))
                self.text(painter, formatter(value), QRectF(x-45, self.box.bottom()+4, 90, 20))
            else:
                y = self.box.bottom()-fraction*self.box.height()
                painter.drawLine(QPointF(self.box.left(), y), QPointF(self.box.left()-3.5, y))
                painter.drawLine(QPointF(self.box.right(), y), QPointF(self.box.right()+3.5, y))
                self.text(painter, formatter(value), QRectF(self.box.left()-62, y-10, 54, 20),
                          Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        offset = formatter.get_offset()
        if offset:
            location = QRectF(self.box.right()-90, self.box.bottom()+43, 90, 18) if horizontal else QRectF(self.box.left()-55, self.box.top()-22, 90, 18)
            self.text(painter, offset, location)


class RadiusGrid(pg.GraphicsObject):
    def __init__(self):
        super().__init__()
        self.rect, self.panels = QRectF(), []
        self.status_callback = None
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def boundingRect(self):
        return self.rect

    def paint(self, painter, *args):
        pass

    def set_result(self, sources, shape, base, labels):
        previous, self.panels = self.panels, []
        self.prepareGeometryChange()
        rows, columns = shape
        self.rect = QRectF(0, 0, columns*460, rows*420+30)
        for index, source in enumerate(sources):
            panel = previous[index] if index < len(previous) else None
            if panel is not None and panel.update_source(source):
                self.panels.append(panel)
            else:
                self.panels.append(RadiusPanel(source, self))
        retained = set(self.panels)
        for panel in previous:
            if panel not in retained:
                panel.setParentItem(None)
                if panel.scene() is not None:
                    panel.scene().removeItem(panel)
        for panel in self.panels:
            panel.status_callback = self.status_callback
        self.relayout(shape, base, labels)

    def relayout(self, shape, base, labels):
        rows, columns = shape
        grow = max(0, base-10)
        left, right, top, bottom = 60+7*grow, 30+4*grow, 75+8*grow, 55+6*grow
        wspace, hspace = .32+.02*grow, .48+.055*grow
        width = (self.rect.width()-left-right)/(columns+(columns-1)*wspace)
        height = (self.rect.height()-top-bottom)/(rows+(rows-1)*hspace)
        for index, panel in enumerate(self.panels):
            row, column = divmod(index, columns)
            panel.set_geometry(QRectF(left+column*width*(1+wspace), top+row*height*(1+hspace), width, height), base, labels)
