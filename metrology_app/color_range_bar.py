"""Compact draggable palette-range selector for the wafer map colour scale."""

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget


class ColorRangeBar(QWidget):
    """Show the whole palette and let two handles pick the band that is used."""

    changed = pyqtSignal(float, float)
    GAP = 0.03

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("colorRangeBar")
        self.setMinimumWidth(120)
        self.setFixedHeight(26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Drag the two handles to choose which part of the palette the map uses.\n"
                        "Moving the left handle right skips the darkest shades.")
        self._colormap = None
        self._low, self._high = 0.0, 1.0
        self._active = None

    # -- state -------------------------------------------------------------
    def set_colormap(self, colormap):
        self._colormap = colormap
        self.update()

    def set_range(self, low, high, notify=False):
        low = min(max(float(low), 0.0), 1.0)
        high = min(max(float(high), 0.0), 1.0)
        if high - low < self.GAP:
            high = min(1.0, low + self.GAP)
            low = max(0.0, high - self.GAP)
        moved = (low, high) != (self._low, self._high)
        self._low, self._high = low, high
        self.update()
        if notify and moved:
            self.changed.emit(self._low, self._high)

    def range(self):
        return self._low, self._high

    # -- geometry ----------------------------------------------------------
    def _track(self):
        inset = 6.0
        return QRectF(inset, (self.height() - 10) / 2, max(1.0, self.width() - 2 * inset), 10)

    def value_at(self, x):
        track = self._track()
        return min(1.0, max(0.0, (x - track.left()) / track.width()))

    def x_of(self, value):
        track = self._track()
        return track.left() + track.width() * value

    # -- painting ----------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track = self._track()
        if self._colormap is not None:
            gradient = QLinearGradient(track.left(), 0, track.right(), 0)
            for step in range(33):
                position = step / 32
                gradient.setColorAt(position, QColor.fromRgbF(*self._colormap(position)[:3]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawRoundedRect(track, 3, 3)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 150))
        if self._low > 0.001:
            painter.drawRect(QRectF(track.left(), track.top(), track.width() * self._low, track.height()))
        if self._high < 0.999:
            painter.drawRect(QRectF(self.x_of(self._high), track.top(),
                                    track.width() * (1 - self._high), track.height()))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#8a8a90"), 1))
        painter.drawRoundedRect(track, 3, 3)
        for value in (self._low, self._high):
            x = self.x_of(value)
            handle = QPolygonF([QPointF(x, track.top() - 6), QPointF(x - 5, track.top() - 1),
                                QPointF(x - 5, track.bottom() + 1), QPointF(x, track.bottom() + 6),
                                QPointF(x + 5, track.bottom() + 1), QPointF(x + 5, track.top() - 1)])
            painter.setPen(QPen(QColor("#ffffff"), 1))
            painter.setBrush(QColor("#1f1f1f"))
            painter.drawPolygon(handle)
        painter.end()

    # -- interaction -------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        value = self.value_at(event.position().x())
        self._active = "low" if abs(value - self._low) <= abs(value - self._high) else "high"
        self._drag(value)

    def mouseMoveEvent(self, event):
        if self._active is not None:
            self._drag(self.value_at(event.position().x()))

    def mouseReleaseEvent(self, event):
        self._active = None

    def _drag(self, value):
        if self._active == "low":
            self.set_range(min(value, self._high - self.GAP), self._high, notify=True)
        elif self._active == "high":
            self.set_range(self._low, max(value, self._low + self.GAP), notify=True)


__all__ = ["ColorRangeBar"]
