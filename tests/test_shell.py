"""Application-shell and loadable-component regression tests."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget

from wafermap.appearance import configure_fonts, fit_window_to_screen
from wafermap.module_registry import ComponentRegistry, ComponentSpec
from wafermap.settings_dialog import SettingsDialog
from wafermap.shell import MainWindow


APP = QApplication.instance() or QApplication([])
configure_fonts(APP)  # the launcher installs the same font before building windows


class FakeScreen:
    """A display whose free area stops above the taskbar."""

    def __init__(self, rect):
        self.rect = rect

    def availableGeometry(self):
        return self.rect


class ShellTests(unittest.TestCase):
    def test_module_card_shows_the_full_component_title(self):
        shell = MainWindow()
        try:
            shell.resize(1180, 820)
            shell.show()
            shell.open_component("correlation_analysis")
            APP.processEvents()
            button = shell.module_buttons["correlation_analysis"]
            label = button.title_label
            self.assertEqual(label.text(), "Correlation and Trend")
            self.assertGreaterEqual(label.width(), label.sizeHint().width())
            self.assertEqual(shell.registry.get("correlation_analysis").title,
                             "Correlation and Trend")
        finally:
            shell.close()
            shell.deleteLater()
            APP.processEvents()

    def test_window_geometry_follows_the_display_and_the_taskbar(self):
        widget = QWidget()
        try:
            screen = FakeScreen(QRect(0, 0, 1920, 1040))  # 1920 x 1080 minus taskbar
            geometry = fit_window_to_screen(widget, (1180, 820), minimum=(900, 600),
                                            screen=screen)
            self.assertEqual((geometry.width(), geometry.height()), (1180, 820))
            self.assertEqual(geometry.center().x(), screen.rect.center().x())
            self.assertEqual(geometry.center().y(), screen.rect.center().y())

            # A display too small for the preferred size: clamp, and lower the
            # minimum so Qt can really shrink the window.
            small = FakeScreen(QRect(0, 0, 1280, 680))
            geometry = fit_window_to_screen(widget, (1520, 950), minimum=(1180, 760),
                                            screen=small)
            self.assertLessEqual(geometry.width(), small.rect.width())
            self.assertLessEqual(geometry.height(), small.rect.height())
            self.assertLessEqual(geometry.right(), small.rect.right())
            self.assertLessEqual(geometry.bottom(), small.rect.bottom())
            self.assertLessEqual(widget.minimumWidth(), geometry.width())
            self.assertLessEqual(widget.minimumHeight(), geometry.height())
        finally:
            widget.deleteLater()
            APP.processEvents()
    def test_windows_fit_the_display_above_the_taskbar(self):
        shell = MainWindow()
        try:
            shell.show()
            APP.processEvents()
            area = APP.primaryScreen().availableGeometry()
            geometry = shell.geometry()
            self.assertGreaterEqual(geometry.left(), area.left())
            self.assertGreaterEqual(geometry.top(), area.top())
            self.assertLessEqual(geometry.right(), area.right())
            self.assertLessEqual(geometry.bottom(), area.bottom())

            # A compressed shell scrolls instead of hiding its panels.
            shell.resize(700, 520)
            APP.processEvents()
            self.assertGreater(shell.shell_scroll.horizontalScrollBar().maximum(), 0)

            # Component windows open fully inside the visible area as well.
            component = shell.open_component("wafer_map")
            APP.processEvents()
            placed = component.geometry()
            self.assertGreaterEqual(placed.left(), area.left())
            self.assertGreaterEqual(placed.top(), area.top())
            self.assertLessEqual(placed.right(), area.right())
            self.assertLessEqual(placed.bottom(), area.bottom())
        finally:
            shell.close()
            shell.deleteLater()
            APP.processEvents()

    def test_settings_has_color_range_without_yaml_reload_button(self):
        dialog = SettingsDialog()
        try:
            labels = [button.text() for button in dialog.findChildren(QPushButton)]
            self.assertNotIn("Load from YAML", labels)
            dialog.color_low.setValue(21.5)
            dialog.color_high.setValue(78.5)
            values = dialog._collect()
            self.assertEqual(values["color_range_low"], .215)
            self.assertEqual(values["color_range_high"], .785)
        finally:
            dialog.close()
            dialog.deleteLater()
            APP.processEvents()

    def test_registry_rejects_duplicates_and_non_widgets(self):
        registry = ComponentRegistry()
        registry.register(ComponentSpec("sample", "Sample", "Description", "Test", QWidget))
        self.assertIsInstance(registry.create("sample"), QWidget)
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(ComponentSpec("sample", "Again", "", "Test", QWidget))
        registry.register(ComponentSpec("invalid", "Invalid", "", "Test", lambda: object()))
        with self.assertRaisesRegex(TypeError, "did not create"):
            registry.create("invalid")

    def test_wafer_workspace_supports_multiple_instances(self):
        shell = MainWindow()
        try:
            self.assertEqual(shell.loaded_component_ids, ())
            self.assertEqual(shell.available_value.text(), "2")
            first = shell.open_component("wafer_map")
            second = shell.open_component("wafer_map")
            APP.processEvents()
            self.assertIsNot(first, second)
            self.assertIs(second, shell.wafer_component)
            self.assertEqual(shell.loaded_component_ids, ("wafer_map",))
            self.assertEqual(shell.instance_count("wafer_map"), 2)
            self.assertEqual(shell.loaded_value.text(), "2")
            self.assertEqual(shell.module_buttons["wafer_map"].state_label.text(), "2 OPEN")
            self.assertTrue(shell.close_all_buttons["wafer_map"].isEnabled())
            first.close()
            APP.processEvents()
            self.assertEqual(shell.instance_count("wafer_map"), 1)
            self.assertEqual(shell.module_buttons["wafer_map"].state_label.text(), "1 OPEN")
            self.assertTrue(shell.unload_component("wafer_map"))
            APP.processEvents()
            self.assertEqual(shell.loaded_component_ids, ())
            self.assertEqual(shell.module_buttons["wafer_map"].state_label.text(), "UNLOADED")
            self.assertFalse(shell.close_all_buttons["wafer_map"].isEnabled())
            self.assertIn("correlation_analysis", shell.module_buttons)
        finally:
            shell.close()
            shell.deleteLater()
            APP.processEvents()


if __name__ == "__main__":
    unittest.main()
