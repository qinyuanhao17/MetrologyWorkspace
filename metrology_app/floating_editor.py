"""Detach a live editor panel without copying its document or undo history."""
from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
import sys

from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (QApplication, QAbstractButton, QDialog,
                            QLabel, QVBoxLayout, QWidget)

from .settings import apply_theme


class _EditorWindow(QDialog):
    def __init__(self, controller, owner):
        # A native owned Tool raises its Workbook when activated on Windows,
        # covering the independent analysis windows the engineer is comparing.
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowSystemMenuHint
                         | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowCloseButtonHint)
        apply_theme(self)
        self.setFont(owner.font())
        owner.destroyed.connect(self.deleteLater)
        self.controller = controller
        self.setWindowTitle(" ")  # Empty titles otherwise fall back to the executable name.
        self.setAccessibleName(f"{controller.title} floating editor")
        self.resize(950, 480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        controller.pin_action = QAction("Pin floating editor within Metrology Workspace", self)
        controller.pin_action.setCheckable(True)
        controller.pin_action.setIcon(_pin_icon())
        controller.pin_action.setShortcut("Alt+P")
        controller.pin_action.toggled.connect(controller.set_pinned)
        self.addAction(controller.pin_action)

    def nativeEvent(self, event_type, message):
        if sys.platform == "win32" and bytes(event_type) == b"windows_generic_MSG":
            import ctypes
            from ctypes.wintypes import MSG
            native = MSG.from_address(int(message))
            if native.wParam == 3:  # HTSYSMENU: the native title-bar icon.
                if native.message == 0xA1:  # WM_NCLBUTTONDOWN
                    self.controller.pin_action.trigger()
                    return True, 0
                if native.message == 0xA3:  # Do not close/dock on icon double-click.
                    return True, 0
        # QWidget has no default native-message handling. Returning an explicit
        # result avoids the PyQt/Qt Windows fallback's undefined LRESULT.
        return False, 0

    def closeEvent(self, event):
        self.controller.dock()
        event.ignore()

    def event(self, event):
        if event.type() == QEvent.Type.NonClientAreaMouseButtonDblClick:
            self.controller.dock()
            return True
        return super().event(event)


def _pin_icon():
    icon = QIcon()
    for checked in (False, True):
        pixmap = QPixmap(48, 48)
        pixmap.setDevicePixelRatio(2)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(12, 12)
        if not checked:
            painter.rotate(35)
        painter.translate(-12, -12)
        painter.setPen(QPen(QColor("#2867ce" if checked else "#77808c"), 1.5))
        painter.setBrush(QColor("#dceaff" if checked else "#f0f2f5"))
        path = QPainterPath()
        path.moveTo(7, 3)
        path.lineTo(17, 3)
        path.lineTo(15, 6)
        path.lineTo(15, 10)
        path.lineTo(18, 14)
        path.lineTo(6, 14)
        path.lineTo(9, 10)
        path.lineTo(9, 6)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(12, 14, 12, 22)
        painter.end()
        icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.On if checked else QIcon.State.Off)
    return icon


class WindowPin(QObject):
    """The editor's application-scoped pin for an already independent window."""

    def __init__(self, window, owner=None):
        super().__init__(window)
        self.window, self.owner, self.pinned = window, owner or window, False
        self.raise_timer = QTimer(self, singleShot=True, interval=0)
        self.raise_timer.timeout.connect(self._raise_in_scope)
        self.action = QAction(_pin_icon(), "Pin", window)
        self.action.setCheckable(True)
        self.action.setShortcut("Alt+P")
        self.action.toggled.connect(self.set_pinned)
        window.addAction(self.action)
        self.set_pinned(False)
        QApplication.instance().installEventFilter(self)

    def _should_raise_for(self, widget):
        return (self.window.isVisible() and isinstance(widget, QWidget) and widget.isWindow()
                and widget is not self.window and QApplication.activeModalWidget() is None
                and (self.pinned or widget is self.owner))

    def _raise_in_scope(self):
        if (QApplication.applicationState() == Qt.ApplicationState.ApplicationActive
                and self._should_raise_for(QApplication.activeWindow())):
            self.window.raise_()

    def set_pinned(self, pinned):
        self.pinned = bool(pinned)
        self.action.setChecked(self.pinned)
        scope = "all Metrology Workspace windows" if self.pinned else "its parent window only"
        self.action.setToolTip(f"Above {scope}. Never above other software. Alt+P to toggle.")
        state = QIcon.State.On if self.pinned else QIcon.State.Off
        self.window.setWindowIcon(QIcon(self.action.icon().pixmap(24, 24, QIcon.Mode.Normal, state)))
        if self._should_raise_for(QApplication.activeWindow()):
            self.raise_timer.start()

    def eventFilter(self, watched, event):
        if not hasattr(self, 'window'):
            return False
        if event.type() == QEvent.Type.WindowActivate and self._should_raise_for(watched):
            self.raise_timer.start()
        return False

    def native_event(self, event_type, message):
        if sys.platform == "win32" and bytes(event_type) == b"windows_generic_MSG":
            import ctypes
            from ctypes.wintypes import MSG
            native = MSG.from_address(int(message))
            if native.wParam == 3 and native.message in (0xA1, 0xA3):
                if native.message == 0xA1:
                    self.action.trigger()
                return True, 0
        return None


class FloatingEditor(QObject):
    def __init__(self, owner, panel, view, splitter, *, title="Raw Data"):
        super().__init__(owner)
        self.owner = owner
        self.title = title
        self.pinned = False
        self.raise_timer = QTimer(self, singleShot=True, interval=0)
        self.raise_timer.timeout.connect(self._raise_in_scope)
        self.panel, self.splitter = panel, splitter
        self.placeholder = QLabel(f"{title} is floating\nDouble-click to restore", owner)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.hide()
        self.dialog = _EditorWindow(self, owner)
        self.set_pinned(False)
        self.floating = False
        self._double_click_targets = {self.placeholder, self.dialog}
        self.placeholder.installEventFilter(self)
        self.dialog.installEventFilter(self)
        for widget in [panel, *panel.findChildren(QWidget)]:
            if widget is not view and not view.isAncestorOf(widget) and not isinstance(widget, QAbstractButton):
                widget.installEventFilter(self)
                self._double_click_targets.add(widget)
        panel.setToolTip(f"Double-click outside the table to float or restore {title}. The editor and Undo remain live.")

    def eventFilter(self, watched, event):
        # Qt can deliver final child events while Python cyclic GC is clearing
        # the controller's attributes, before QObject removes its filters.
        if not hasattr(self, '_double_click_targets'):
            return False
        if event.type() in (QEvent.Type.WindowActivate, QEvent.Type.ZOrderChange):
            if self._should_raise_for(watched):
                self.raise_timer.start()
        if (watched in self._double_click_targets
                and event.type() == QEvent.Type.MouseButtonDblClick
                and event.button() == Qt.MouseButton.LeftButton):
            self.dock() if self.floating else self.detach()
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def _should_raise_for(self, widget):
        if (not self.floating or not isinstance(widget, QWidget) or not widget.isWindow()
                or isinstance(widget, _EditorWindow) or QApplication.activeModalWidget() is not None):
            return False
        # Application filters see only this process's Qt windows. There is no
        # system-topmost flag, transient owner, or workbook-family hierarchy.
        return self.pinned or widget is self.owner

    def _raise_in_scope(self):
        # Activation/z-order changes finish after WindowActivate. Coalesce one
        # local raise, and re-check the foreground app so a late timer cannot
        # lift the float over other software or another active editor.
        if (QApplication.applicationState() == Qt.ApplicationState.ApplicationActive
                and self._should_raise_for(QApplication.activeWindow())):
            self.dialog.raise_()

    def set_pinned(self, pinned):
        self.pinned = bool(pinned)
        self.pin_action.blockSignals(True)
        self.pin_action.setChecked(self.pinned)
        self.pin_action.blockSignals(False)
        state = QIcon.State.On if self.pinned else QIcon.State.Off
        self.dialog.setWindowIcon(QIcon(self.pin_action.icon().pixmap(24, 24, QIcon.Mode.Normal, state)))
        scope = "all Metrology Workspace windows" if self.pinned else "its parent window only"
        self.pin_action.setToolTip(f"{'Pinned' if self.pinned else 'Unpinned'}: above {scope}. Never above other software. Alt+P to toggle.")
        if getattr(self, 'floating', False) and self._should_raise_for(QApplication.activeWindow()):
            self.raise_timer.start()

    def detach(self):
        if self.floating:
            return
        self.index, self.sizes = self.splitter.indexOf(self.panel), self.splitter.sizes()
        self.splitter.replaceWidget(self.index, self.placeholder)
        self.dialog.layout().addWidget(self.panel)
        self.floating = True
        QApplication.instance().installEventFilter(self)
        self.panel.show()
        self.placeholder.show()
        self.dialog.show()
        self.dialog.raise_()

    def dock(self):
        if not self.floating:
            return
        self.dialog.layout().removeWidget(self.panel)
        self.splitter.replaceWidget(self.index, self.panel)
        self.placeholder.hide()
        self.panel.show()
        self.splitter.setSizes(self.sizes)
        self.floating = False
        self.raise_timer.stop()
        QApplication.instance().removeEventFilter(self)
        self.dialog.hide()
