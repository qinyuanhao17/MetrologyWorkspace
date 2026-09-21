"""Signed-radius page behavior."""
import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from wafermap.radius_page import signed_radius
from wafermap.appearance import screen_render_scale
from wafermap.settings import get_settings
from wafermap.window import MainWindow

ROOT = Path(__file__).resolve().parents[1]
APP = QApplication.instance() or QApplication([])


class RadiusTests(unittest.TestCase):
    def test_signed_radius_uses_x_side(self):
        np.testing.assert_allclose(signed_radius([-3, 0, 4], [4, 5, 3]), [-5, 0, 5])

    @staticmethod
    def select_parameters(window, names):
        tree = window.parameter_list
        tree.blockSignals(True)
        for index in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(index)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(0, Qt.CheckState.Checked if item.text(0) in names else Qt.CheckState.Unchecked)
        tree.blockSignals(False)
        window.update_plan()

    def test_real_data_draws_selected_parameters(self):
        window = MainWindow()
        try:
            window.load_path(ROOT / "OCD_measurement_data.csv")
            self.select_parameters(window, {"OCD_H1", "OCD_H2", "OCD_H3"})
            self.assertEqual(window.tabs.tabText(2), "3. Radius Plot")
            page = window.radius_page
            self.assertEqual((page.x_column.currentText(), page.y_column.currentText()), ("X(mm)", "Y(mm)"))
            page.draw_plot()
            self.assertTrue(page.ready)
            self.assertEqual(len(page.figure.axes), 18)
            self.assertEqual(len(page.figure.legends), 0)
            self.assertTrue(all(len(axis.collections) == 1 for axis in page.figure.axes))
            self.assertEqual(page.base_size, (3 * 460, 6 * 370 + 30))
            self.assertEqual(page.resolution.currentText(), get_settings()["resolution"])
            screen_scale = {"Standard": 1, "High": 1.5, "Ultra": 2}[page.resolution.currentText()]
            screen_scale = screen_render_scale(3 * 460, 6 * 370 + 30, screen_scale)
            self.assertEqual(page.canvas.width(), round(3 * 460 * screen_scale))
            self.assertIn("18 / 18 radius plots drawn", page.status.text())
            first_axis = page.figure.axes[0]
            self.assertEqual(first_axis.get_title(loc="center"), "OCD_H1")
            self.assertEqual(first_axis.title.get_fontweight(), "bold")
            self.assertIn("PAD:", first_axis._wafer_title_details[0].get_text())
            self.assertIn("Min", first_axis._wafer_title_details[1].get_text())
            self.assertTrue(all(text.get_ha() == "center" for text in first_axis._wafer_title_details))
            offsets = page.figure.axes[0].collections[0].get_offsets()
            self.assertTrue((offsets[:, 0] < 0).any() and (offsets[:, 0] > 0).any())
            self.assertEqual(page.figure.axes[0].get_xlim(), (-150, 150))
            APP.processEvents()
            with patch.object(page.canvas, "draw") as redraw:
                page.zoom_by_wheel(120)
                self.assertEqual(page.zoom.currentText(), "75%")
                APP.processEvents()
                redraw.assert_not_called()
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_radius_plot_keeps_its_own_box_selection(self):
        window = MainWindow()
        try:
            window.load_path(ROOT / "OCD_measurement_data.csv")
            self.select_parameters(window, {"OCD_H1", "OCD_H2"})
            page = window.radius_page
            self.assertIsNot(page.selector, window.plot_page.selector)
            self.assertEqual((page.selector.rowCount(), page.selector.columnCount()), (6, 2))
            page.selector.clearSelection()
            page.selector.item(1, 1).setSelected(True)
            page.draw_plot()
            self.assertTrue(page.ready)
            self.assertEqual(len(page.figure.axes), 12)
            self.assertEqual(sum(ax.axison for ax in page.figure.axes), 1)
            self.assertIn("1 / 12", page.status.text())
            # The wafer-map selection keeps every box; the two selectors are independent.
            self.assertEqual(len(window.plot_page.selector.selected_cells()), 12)
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()


if __name__ == "__main__":
    unittest.main()
