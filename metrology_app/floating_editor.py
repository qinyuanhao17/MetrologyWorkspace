"""Detach a live editor panel without copying its document or undo history."""
from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QApplication, QAbstractButton, QDialog, QLabel, QVBoxLayout, QWidget

from .settings import apply_theme


class _EditorWindow(QDialog):
    def __init__(self, controller, owner):
        # A native owned Tool raises its Workbook when activated on Windows,
        # covering the independent analysis windows the engineer is comparing.
        super().__init__(owner if controller.owner_only else None, Qt.WindowType.Tool)
        apply_theme(self)
        self.setFont(owner.font())
        owner.destroyed.connect(self.deleteLater)
        self.controller = controller
        self.setWindowTitle(f"{controller.title} — double-click empty space to restore")
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
    def __init__(self, owner, panel, view, splitter, *, title="Raw Data", owner_only=False):
        super().__init__(owner)
        self.owner = owner
        self.title, self.owner_only = title, owner_only
        self.panel, self.splitter = panel, splitter
        self.placeholder = QLabel(f"{title} is floating\nDouble-click to restore", owner)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.hide()
        self.dialog = _EditorWindow(self, owner)
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
        if event.type() == QEvent.Type.WindowActivate and self.floating and not self.owner_only:
            if (watched is not self.dialog and self._in_workbook_scope(watched)
                    and QApplication.activeModalWidget() is None):
                self.dialog.raise_()
        if (watched in self._double_click_targets
                and event.type() == QEvent.Type.MouseButtonDblClick
                and event.button() == Qt.MouseButton.LeftButton):
            self.dock() if self.floating else self.detach()
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def _in_workbook_scope(self, widget):
        if not isinstance(widget, QWidget) or not widget.isWindow():
            return False
        # Include owned dialogs, but not other workbooks or their analysis views.
        while widget is not None:
            if widget is self.owner or getattr(widget, '_managed_owner', None) is self.owner:
                return True
            widget = widget.parentWidget()
        return False

    def detach(self):
        if self.floating:
            return
        self.index, self.sizes = self.splitter.indexOf(self.panel), self.splitter.sizes()
        self.splitter.replaceWidget(self.index, self.placeholder)
        self.dialog.layout().addWidget(self.panel)
        self.floating = True
        if not self.owner_only:
            # Unowned ordinary Tools do not activate their Workbook ancestor.
            # Raise without activating only inside the current workbook family.
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
        if not self.owner_only:
            QApplication.instance().removeEventFilter(self)
        self.dialog.hide()
