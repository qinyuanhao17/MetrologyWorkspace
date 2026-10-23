"""Two explicit floating-editor scopes, independent of analysis-window kinds."""
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import QApplication, QSplitter, QTableWidget, QVBoxLayout, QWidget

from metrology_app.floating_editor import FloatingEditor

APP = QApplication.instance() or QApplication([])


class FloatingPinTests(unittest.TestCase):
    def setUp(self):
        self.owner, self.peer = QWidget(), QWidget()
        self.owner.setWindowTitle("Parent")
        self.peer._managed_owner = self.owner
        self.splitter = QSplitter(self.owner)
        QVBoxLayout(self.owner).addWidget(self.splitter)
        self.panel, self.side = QWidget(), QWidget()
        self.view = QTableWidget(2, 2, self.panel)
        QVBoxLayout(self.panel).addWidget(self.view)
        self.splitter.addWidget(self.panel)
        self.splitter.addWidget(self.side)
        self.control = FloatingEditor(self.owner, self.panel, self.view, self.splitter)
        self.owner.show()
        self.peer.show()
        self.control.detach()
        APP.processEvents()

    def tearDown(self):
        self.control.dock()
        for widget in (self.peer, self.owner):
            widget.close()
            widget.deleteLater()
        APP.processEvents()

    def test_unpinned_is_parent_only_and_pin_is_an_accessible_top_left_control(self):
        action = self.control.pin_action
        self.assertTrue(action.isCheckable())
        self.assertFalse(action.isChecked())
        self.assertTrue(self.control.dialog.accessibleName())
        self.assertFalse(self.control.dialog.windowIcon().isNull())
        self.assertEqual(self.control.dialog.windowTitle().strip(), "")
        self.assertEqual(self.control.dialog.layout().count(), 1)
        with patch.object(self.control.dialog, "raise_") as raised:
            self.activate(self.peer)
            raised.assert_not_called()
            self.activate(self.owner)
            raised.assert_called_once()

    def test_pinned_covers_other_workspace_windows_but_not_system_topmost_or_modal(self):
        self.control.pin_action.trigger()
        self.assertTrue(self.control.pinned)
        with patch.object(self.control.dialog, "raise_") as raised:
            self.activate(self.peer)
            raised.assert_called_once()
            raised.reset_mock()
            with patch.object(QApplication, "activeModalWidget", return_value=self.peer):
                self.activate(self.owner)
            raised.assert_not_called()
            self.activate(self.control.dialog)
            raised.assert_not_called()
        self.assertFalse(self.control.dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.assertIsNone(self.control.dialog.parentWidget())

    def activate(self, window, *, foreground=True):
        state = Qt.ApplicationState.ApplicationActive if foreground else Qt.ApplicationState.ApplicationInactive
        with patch.object(QApplication, "activeWindow", return_value=window), \
                patch.object(QApplication, "applicationState", return_value=state):
            APP.sendEvent(window, QEvent(QEvent.Type.WindowActivate))
            APP.processEvents()  # Native z-order changes settle before the queued local raise.

    def test_delayed_raise_is_cancelled_when_another_application_is_active(self):
        self.control.set_pinned(True)
        with patch.object(self.control.dialog, "raise_") as raised:
            self.activate(self.peer, foreground=False)
            raised.assert_not_called()

    def test_pin_changes_scope_without_replacing_editor_and_dock_retains_choice(self):
        model = self.view.model()
        self.control.pin_action.trigger()
        self.control.dock()
        self.assertIs(self.splitter.widget(0), self.panel)
        self.control.detach()
        self.assertIs(self.view.model(), model)
        self.assertTrue(self.control.pinned)
        self.control.pin_action.trigger()
        with patch.object(self.control.dialog, "raise_") as raised:
            self.activate(self.peer)
            raised.assert_not_called()

    def test_native_title_icon_toggles_pin_without_docking(self):
        import sys
        if sys.platform != "win32":
            self.skipTest("Native title-bar icon contract is Windows-specific")
        import ctypes
        from ctypes.wintypes import MSG
        message = MSG()
        message.message, message.wParam = 0xA1, 3
        handled, _ = self.control.dialog.nativeEvent(b"windows_generic_MSG", ctypes.addressof(message))
        self.assertTrue(handled)
        self.assertTrue(self.control.pinned)
        message.message = 0xA3
        self.control.dialog.nativeEvent(b"windows_generic_MSG", ctypes.addressof(message))
        self.assertTrue(self.control.floating)
