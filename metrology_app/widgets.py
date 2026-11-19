"""Small widgets shared by more than one workspace."""

from PyQt6.QtCore import QEvent, QObject, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QAbstractScrollArea, QApplication, QComboBox, QListWidget


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
