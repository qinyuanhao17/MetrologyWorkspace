"""Application-shell and loadable-component regression tests."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import (
    QApplication, QLabel, QListWidget, QPlainTextEdit, QPushButton, QWidget,
)

from metrology_app.appearance import configure_fonts, fit_window_to_screen
from metrology_app.module_registry import ComponentRegistry, ComponentSpec
from metrology_app.settings_dialog import SettingsDialog
from metrology_app.shell import MainWindow


APP = QApplication.instance() or QApplication([])
configure_fonts(APP)  # the launcher installs the same font before building windows


class FakeScreen:
    """A display whose free area stops above the taskbar."""

    def __init__(self, rect):
        self.rect = rect

    def availableGeometry(self):
        return self.rect


class ShellTests(unittest.TestCase):
    def test_section_guidance_is_available_from_titles_not_subtitle_rows(self):
        shell = MainWindow()
        try:
            labels = shell.findChildren(QLabel)
            workspace = next(label for label in labels if label.text() == "Workspace")
            activity = next(label for label in labels if label.text() == "Activity")
            log = next(label for label in labels if label.text() == "Log")
            self.assertEqual(
                workspace.toolTip(), "Open a tool in its own analysis window."
            )
            self.assertEqual(
                activity.toolTip(), "Windows and files opened in this session."
            )
            self.assertEqual(
                log.toolTip(), "Runtime, file paths, and errors for debugging."
            )
            self.assertFalse(any(
                label.objectName() in {"pageSubtitle", "componentDescription"}
                for label in labels
            ))
            self.assertFalse(any(label.text() == "AVAILABLE TOOLS" for label in labels))
            self.assertFalse(shell.findChildren(QWidget, "componentCard"))
            self.assertIsInstance(shell.activity, QListWidget)
            self.assertIsInstance(shell.log_output, QPlainTextEdit)
        finally:
            shell.close()
            shell.deleteLater()
            APP.processEvents()

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
            self.assertEqual(shell.available_value.text(), "4")
            first = shell.open_component("wafer_map")
            second = shell.open_component("wafer_map")
            APP.processEvents()
            self.assertIsNot(first, second)
            self.assertIs(second, shell.wafer_component)
            self.assertEqual(shell.loaded_component_ids, ("wafer_map",))
            self.assertEqual(shell.instance_count("wafer_map"), 2)
            self.assertEqual(shell.loaded_value.text(), "2")
            self.assertEqual(shell.module_buttons["wafer_map"].state_label.text(), "2 OPEN")
            first.close()
            APP.processEvents()
            self.assertEqual(shell.instance_count("wafer_map"), 1)
            self.assertEqual(shell.module_buttons["wafer_map"].state_label.text(), "1 OPEN")
            self.assertTrue(shell.unload_component("wafer_map"))
            APP.processEvents()
            self.assertEqual(shell.loaded_component_ids, ())
            self.assertEqual(shell.module_buttons["wafer_map"].state_label.text(), "CLOSED")
            self.assertIn("correlation_analysis", shell.module_buttons)
            self.assertIn("dynamic_analysis", shell.module_buttons)
        finally:
            shell.close()
            shell.deleteLater()
            APP.processEvents()

    def test_terminal_log_records_runtime_component_and_error_information(self):
        shell = MainWindow()
        try:
            initial = shell.log_output.toPlainText()
            self.assertIn("Python", initial)
            self.assertIn("Working directory", initial)
            self.assertEqual(shell.log_output.horizontalScrollBar().value(), 0)

            component = shell.open_component("wafer_map")
            APP.processEvents()
            self.assertIn("Opened Wafer Map", shell.log_output.toPlainText())
            self.assertIn("Opened Wafer Map", shell.activity.item(0).text())
            component.close()
            APP.processEvents()
            self.assertIn("Closed a Wafer Map window", shell.log_output.toPlainText())
            self.assertIn("Closed a Wafer Map window", shell.activity.item(0).text())

            shell.record("Error", "example traceback")
            self.assertIn("ERROR", shell.log_output.toPlainText())
            self.assertIn("example traceback", shell.log_output.toPlainText())
        finally:
            shell.close()
            shell.deleteLater()
            APP.processEvents()

    def test_log_spans_the_bottom_below_the_restored_activity_panel(self):
        shell = MainWindow()
        try:
            shell.resize(1180, 820)
            shell.show()
            APP.processEvents()

            activity_bottom = shell.activity.mapTo(
                shell, QPoint(0, shell.activity.height())
            ).y()
            log_top = shell.log_output.mapTo(shell, QPoint(0, 0)).y()
            self.assertGreaterEqual(log_top, activity_bottom)
            self.assertGreater(shell.log_output.width(), shell.activity.width())
        finally:
            shell.close()
            shell.deleteLater()
            APP.processEvents()

    def test_light_theme_uses_a_light_fixed_width_terminal_log(self):
        shell = MainWindow()
        try:
            with patch("metrology_app.shell.get_settings", return_value={"theme": "light"}):
                shell.apply_settings()
            shell.show()
            APP.processEvents()

            palette = shell.log_output.palette()
            self.assertEqual(
                palette.color(QPalette.ColorRole.Base).name(), "#fbfbfc"
            )
            self.assertEqual(
                palette.color(QPalette.ColorRole.Text).name(), "#24212a"
            )
            self.assertIn(
                shell.log_output.font().family(),
                {"Cascadia Mono", "Cascadia Code", "JetBrains Mono", "Consolas", "Courier New"},
            )
        finally:
            shell.close()
            shell.deleteLater()
            APP.processEvents()

    def test_terminal_log_colours_level_labels_after_theme_switch(self):
        shell = MainWindow()
        try:
            shell.record("App", "analysis completed")
            shell.record("Warning", "column needs attention")
            shell.record("Error", "analysis failed")
            with patch("metrology_app.shell.get_settings", return_value={"theme": "light"}):
                shell.apply_settings()
            APP.processEvents()

            colours = {}
            block = shell.log_output.document().begin()
            while block.isValid():
                iterator = block.begin()
                while not iterator.atEnd():
                    fragment = iterator.fragment()
                    for level in ("INFO", "WARNING", "ERROR"):
                        if fragment.text() == f"[{level}]":
                            colours[level] = (
                                fragment.charFormat().foreground().color().name()
                            )
                    iterator += 1
                block = block.next()

            self.assertEqual(colours, {
                "INFO": "#1d5fbf",
                "WARNING": "#8a5a00",
                "ERROR": "#b42318",
            })
            text = shell.log_output.toPlainText()
            self.assertIn("[INFO]", text)
            self.assertIn("[WARNING]", text)
            self.assertIn("[ERROR]", text)
        finally:
            shell.close()
            shell.deleteLater()
            APP.processEvents()


if __name__ == "__main__":
    unittest.main()
