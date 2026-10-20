"""Detach a live editor panel without copying its document or undo history."""
from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QAbstractButton, QDialog, QLabel, QVBoxLayout, QWidget


class _EditorWindow(QDialog):
    def __init__(self, controller, owner):
        super().__init__(owner, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.controller = controller
        self.setWindowTitle("Raw Data — double-click empty space to restore")
        self.resize(950, 480)
        QVBoxLayout(self).setContentsMargins(6, 6, 6, 6)

    def closeEvent(self, event):
        self.controller.dock()
        event.ignore()

    def event(self, event):
        if event.type() == QEvent.Type.NonClientAreaMouseButtonDblClick:
            self.controller.dock()
            return True
        return super().event(event)


class FloatingEditor(QObject):
    def __init__(self, owner, panel, view, splitter):
        super().__init__(owner)
        self.panel, self.splitter = panel, splitter
        self.placeholder = QLabel("Raw Data is floating\nDouble-click to restore", owner)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.hide()
        self.dialog = _EditorWindow(self, owner)
        self.floating = False
        self.placeholder.installEventFilter(self)
        self.dialog.installEventFilter(self)
        for widget in [panel, *panel.findChildren(QWidget)]:
            if widget is not view and not view.isAncestorOf(widget) and not isinstance(widget, QAbstractButton):
                widget.installEventFilter(self)
        panel.setToolTip("Double-click outside the table to float or restore Raw Data. The editor and Undo remain live.")

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonDblClick and event.button() == Qt.MouseButton.LeftButton:
            self.dock() if self.floating else self.detach()
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def detach(self):
        if self.floating:
            return
        self.index, self.sizes = self.splitter.indexOf(self.panel), self.splitter.sizes()
        self.splitter.replaceWidget(self.index, self.placeholder)
        self.dialog.layout().addWidget(self.panel)
        self.floating = True
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
        self.dialog.hide()
