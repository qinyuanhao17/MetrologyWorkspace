"""Floating editors preserve live models without system-wide topmost windows."""
import unittest

from unittest.mock import patch
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import QApplication

from metrology_app.matching_window import MatchingWindow
from metrology_app.correlation_window import CorrelationWindow
from metrology_app.window import MainWindow

APP = QApplication.instance() or QApplication([])


class FloatScopeTests(unittest.TestCase):
    def test_unpinned_raw_raise_is_parent_only_and_never_covers_modal_prompts(self):
        window, child, unrelated = MatchingWindow(), MainWindow(), MainWindow()
        try:
            child._managed_owner = window
            control = window.raw_floating_editor
            control.detach()
            with patch.object(control.dialog, 'raise_') as raise_float, \
                    patch.object(QApplication, 'applicationState', return_value=Qt.ApplicationState.ApplicationActive):
                APP.sendEvent(child, QEvent(QEvent.Type.WindowActivate))
                raise_float.assert_not_called()
                with patch.object(QApplication, 'activeWindow', return_value=window):
                    APP.sendEvent(window, QEvent(QEvent.Type.WindowActivate))
                    APP.processEvents()
                raise_float.assert_called_once()
                raise_float.reset_mock()
                APP.sendEvent(unrelated, QEvent(QEvent.Type.WindowActivate))
                raise_float.assert_not_called()
                with patch.object(QApplication, 'activeModalWidget', return_value=child):
                    APP.sendEvent(child, QEvent(QEvent.Type.WindowActivate))
                raise_float.assert_not_called()
        finally:
            for view in (unrelated, child, window):
                view.document.force_close = True
                view.close()
                view.deleteLater()
            APP.processEvents()

    def test_raw_editor_is_not_a_system_topmost_window(self):
        window = MatchingWindow()
        try:
            control = window.raw_floating_editor
            control.detach()
            self.assertFalse(control.dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
            self.assertIsNone(control.dialog.parentWidget(), 'Activating the float must not raise Workbook')
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_map_and_both_correlation_sources_float_without_replacing_models(self):
        for kind in (MainWindow, CorrelationWindow):
            window = kind()
            try:
                controls = [(getattr(window, 'measurement_floating_editor', None), window.sheet)]
                if kind is CorrelationWindow:
                    controls.append((getattr(window, 'reference_floating_editor', None), window.reference_sheet))
                for control, view in controls:
                    self.assertIsNotNone(control)
                    model = view.model()
                    control.detach()
                    self.assertTrue(control.floating)
                    self.assertFalse(control.dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
                    control.dock()
                    self.assertIs(view.model(), model)
            finally:
                window.document.force_close = True
                window.close()
                window.deleteLater()
                APP.processEvents()
