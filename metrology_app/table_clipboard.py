"""Range-only clipboard feedback shared by editable table views.

The overlay never reads cell values or changes selection/document state. Even a
whole-sheet copy paints at most four visible line segments per animation tick.
"""
import csv
from io import StringIO

from PyQt6.QtCore import QEvent, QObject, QPointF, Qt, QTimer
from PyQt6.QtGui import QColor, QKeySequence, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget

from .settings import get_settings


def selection_bounds(view):
    """Preserve selectable-index semantics without expanding uniform ranges."""
    if getattr(view.model(), "uniform_selectable", False):
        ranges = view.selectionModel().selection()
        if not ranges:
            return None
        return (min(r.top() for r in ranges), min(r.left() for r in ranges),
                max(r.bottom() for r in ranges), max(r.right() for r in ranges))
    indexes = view.selectedIndexes()
    if not indexes:
        return None
    return (min(i.row() for i in indexes), min(i.column() for i in indexes),
            max(i.row() for i in indexes), max(i.column() for i in indexes))


def copy_selection(view, role=Qt.ItemDataRole.DisplayRole, *, cell_text=None):
    """Copy exact source strings where available, displayed values elsewhere."""
    bounds = selection_bounds(view)
    if bounds is None:
        return False
    top, left, bottom, right = bounds
    model = view.model()
    uniform = getattr(model, "uniform_selectable", False)
    output = StringIO()
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    for row in range(top, bottom + 1):
        if cell_text is not None:
            values = [cell_text(row, column) for column in range(left, right + 1)]
        elif uniform:
            values = [model.cells.get((row, column), "") for column in range(left, right + 1)]
        else:
            values = [model.data(model.index(row, column), role) for column in range(left, right + 1)]
        writer.writerow(["" if value is None else value for value in values])
    text = output.getvalue()
    QApplication.clipboard().setText(text)
    if QApplication.clipboard().text() != text:
        return False
    view.clipboard_outline.show_range(bounds, "copy")
    return True


class _CopyFeedback(QObject):
    """Computed/configuration grids can copy, but never cut their results."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        view.installEventFilter(self)
        model = view.model()
        for signal in (model.modelReset, model.dataChanged, model.rowsRemoved, model.columnsRemoved):
            signal.connect(view.clipboard_outline.clear)

    def eventFilter(self, _watched, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.matches(QKeySequence.StandardKey.Copy):
                copy_selection(self.view)
                return True
            if event.matches(QKeySequence.StandardKey.Cut):
                return True
            if event.key() == Qt.Key.Key_Escape:
                self.view.clipboard_outline.clear()
        return False


def attach_copy_feedback(view):
    """Attach to an existing result/configuration view after setting its model."""
    view.clipboard_outline = ClipboardRangeOutline(view)
    view._copy_feedback = _CopyFeedback(view)
    return view._copy_feedback


class ClipboardRangeOutline(QWidget):
    """Mouse-transparent copy/cut perimeter; paste uses native selection."""

    def __init__(self, view):
        super().__init__(view.viewport())
        self.view = view
        self.bounds = None
        self.mode = None
        self.phase = 0
        self.timer = QTimer(self)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self._animate)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setGeometry(view.viewport().rect())
        view.viewport().installEventFilter(self)
        view.horizontalScrollBar().valueChanged.connect(self.update)
        view.verticalScrollBar().valueChanged.connect(self.update)
        view.horizontalHeader().sectionResized.connect(self.update)
        view.verticalHeader().sectionResized.connect(self.update)
        QApplication.clipboard().dataChanged.connect(self._clipboard_changed)
        self.hide()

    def show_range(self, bounds, mode):
        self.bounds, self.mode, self.phase = bounds, mode, 0
        self.setGeometry(self.view.viewport().rect())
        self.show()
        self.raise_()
        self._update_timer()
        self.update()

    def clear(self, *_args):
        self.timer.stop()
        self.bounds = self.mode = None
        self.hide()

    def _clipboard_changed(self):
        if self.mode == "copy":
            self.clear()

    def _update_timer(self):
        if self.bounds is not None and self.mode == "copy" and self.view.isVisible():
            self.timer.start()
        else:
            self.timer.stop()

    def _animate(self):
        self.phase = (self.phase + 1) % 8
        self.update()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self.setGeometry(self.view.viewport().rect())
        elif event.type() in (QEvent.Type.Show, QEvent.Type.Hide):
            self._update_timer()
        return False

    def paintEvent(self, _event):
        if self.bounds is None:
            return
        top, left, bottom, right = self.bounds
        view = self.view
        x1, y1 = view.columnViewportPosition(left) + 1, view.rowViewportPosition(top) + 1
        x2 = view.columnViewportPosition(right) + view.columnWidth(right) - 2
        y2 = view.rowViewportPosition(bottom) + view.rowHeight(bottom) - 2
        if x2 < x1 or y2 < y1:
            return
        painter = QPainter(self)
        pen = QPen(QColor("#55d98a" if get_settings()["theme"] == "dark" else "#168547"), 2)
        pen.setCosmetic(True)
        if self.mode == "copy":
            pen.setDashPattern([4, 4])
            pen.setDashOffset(self.phase)
        painter.setPen(pen)
        # Clip each real edge, not the rectangle itself: offscreen ranges must
        # not acquire fake borders at the viewport edge. Work stays O(1).
        width, height = self.width() - 1, self.height() - 1
        for y in (y1, y2):
            if 0 <= y <= height and x1 <= width and x2 >= 0:
                painter.drawLine(QPointF(max(0, x1), y), QPointF(min(width, x2), y))
        for x in (x1, x2):
            if 0 <= x <= width and y1 <= height and y2 >= 0:
                painter.drawLine(QPointF(x, max(0, y1)), QPointF(x, min(height, y2)))
