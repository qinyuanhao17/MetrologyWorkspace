"""Application-shell and loadable-component regression tests."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QPushButton, QWidget

from wafermap.module_registry import ComponentRegistry, ComponentSpec
from wafermap.settings_dialog import SettingsDialog
from wafermap.shell import MainWindow


APP = QApplication.instance() or QApplication([])


class ShellTests(unittest.TestCase):
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
