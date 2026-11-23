"""Small widgets shared by more than one workspace."""

from PyQt6.QtCore import QEvent, QLocale, QObject, QPointF, QSignalBlocker, QSize, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import (
    QAbstractScrollArea, QApplication, QComboBox, QListWidget, QStyle,
    QPushButton, QStyleOption, QStyleOptionButton, QStyleOptionComboBox, QStylePainter,
)


def configure_date_calendar(date_input):
    locale = QLocale(QLocale.Language.English, QLocale.Country.UnitedKingdom)
    date_input.setLocale(locale)
    date_input.setDisplayFormat("yyyy-MM-dd")
    date_input.setCalendarPopup(True)
    calendar = date_input.calendarWidget()
    calendar.setLocale(locale)
    calendar.setObjectName("appDateCalendar")
    calendar.setMinimumSize(336, 300)
    calendar.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
    calendar.setVerticalHeaderFormat(calendar.VerticalHeaderFormat.NoVerticalHeader)
    calendar.setHorizontalHeaderFormat(calendar.HorizontalHeaderFormat.ShortDayNames)


class ScrollSafeComboBox(QComboBox):
    """A picker whose value never changes from the mouse wheel.

    The surrounding page or table gets the notch instead, so an accidental
    wheel cannot silently remap a parameter or switch a curve.
    """

    def wheelEvent(self, event):
        parent = self.parentWidget()
        fallback = None
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                fallback = fallback or parent
                if parent.verticalScrollBar().maximum() > 0:
                    break
            parent = parent.parentWidget()
        parent = parent or fallback
        if parent is None:
            event.ignore()
            return
        viewport = parent.viewport()
        forwarded = QWheelEvent(
            QPointF(viewport.mapFromGlobal(event.globalPosition().toPoint())),
            event.globalPosition(), event.pixelDelta(), event.angleDelta(),
            event.buttons(), event.modifiers(), event.phase(), event.inverted(),
        )
        QApplication.sendEvent(viewport, forwarded)
        event.setAccepted(forwarded.isAccepted())


def _draw_picker_arrow(widget, painter):
    option = QStyleOption()
    option.initFrom(widget)
    area = widget.rect()
    area.setWidth(24)
    area.moveRight(widget.rect().right())
    option.rect = QStyle.alignedRect(
        widget.layoutDirection(), Qt.AlignmentFlag.AlignCenter, QSize(10, 10), area,
    )
    QApplication.style().drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorArrowDown, option, painter)


class WaferColumnButton(QPushButton):
    """Keep the multi-select menu and use the same arrow as the Die picker."""

    def paintEvent(self, _event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.features &= ~QStyleOptionButton.ButtonFeature.HasMenu
        painter = QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)
        _draw_picker_arrow(self, painter)


class DieColumnComboBox(ScrollSafeComboBox):
    """Show the Die field name in the closed control."""

    def __init__(self, parent=None):
        super().__init__(parent, objectName="diePicker")
        self.setAccessibleName("Die column")
        self.setToolTip("Raw column used for Die labels in the plots.")

    def set_columns(self, columns):
        from .data import die_sequence_column

        selected = self.currentData()
        choices = tuple(name for name in columns if str(name).casefold() != "cycle")
        if tuple(self.itemData(i) for i in range(self.count())) == (None, *choices):
            return
        default = die_sequence_column(choices)
        with QSignalBlocker(self):
            self.clear()
            self.addItem(f"Auto ({default})" if default is not None else "Auto", None)
            for column in choices:
                self.addItem(str(column), column)
            self.setCurrentIndex(max(0, self.findData(selected)))
            self.setEnabled(bool(choices))

    def paintEvent(self, _event):
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        option.currentText = f"Die: {option.currentText}"
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)

        _draw_picker_arrow(self, painter)


class CheckableListWidget(QListWidget):
    """Click anywhere on an enabled checkable row to toggle it once."""
    def mouseReleaseEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
        if event.button() == Qt.MouseButton.LeftButton and item is not None and (item.flags() & flags) == flags:
            state = Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked
            item.setCheckState(state)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class LinkedVerticalScroll(QObject):
    """Use Ctrl+wheel to align the vertical scroll progress of peer views."""

    def __init__(self, parent, views):
        super().__init__(parent)
        self.views = {view.viewport(): view.verticalScrollBar() for view in views}
        for viewport in self.views:
            viewport.installEventFilter(self)

    def eventFilter(self, viewport, event):
        control = Qt.KeyboardModifier.ControlModifier
        if (event.type() != QEvent.Type.Wheel or not event.modifiers() & control
                or not (event.pixelDelta().y() or event.angleDelta().y())):
            return False
        peers = {view: bar for view, bar in self.views.items() if view.isVisible()}
        if viewport not in peers:
            return False
        anchor = viewport if peers[viewport].maximum() > 0 else max(peers, key=lambda view: peers[view].maximum())
        source = peers[anchor]
        if source.maximum() == 0:
            return False
        scroll = QWheelEvent(QPointF(anchor.mapFromGlobal(event.globalPosition().toPoint())),
                             event.globalPosition(), event.pixelDelta(), event.angleDelta(),
                             event.buttons(), event.modifiers() & ~control, event.phase(), event.inverted())
        QApplication.sendEvent(anchor, scroll)
        progress = source.value() / source.maximum()
        for bar in peers.values():
            if bar is not source:
                bar.setValue(round(progress * bar.maximum()))
        event.accept()
        return True


__all__ = ["CheckableListWidget", "LinkedVerticalScroll", "ScrollSafeComboBox"]
