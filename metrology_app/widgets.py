"""Small widgets shared by more than one workspace."""

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QAbstractScrollArea, QApplication, QComboBox


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


__all__ = ["ScrollSafeComboBox"]
