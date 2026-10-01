"""Signed-radius page behavior."""
import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from metrology_app.radius_page import signed_radius
from metrology_app.appearance import screen_render_scale
from metrology_app.settings import get_settings
from metrology_app.window import MainWindow

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
            window.load_path(ROOT / "sample_data" / "OCD_measurement_data.csv")
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
            self.assertEqual(page.copy_shortcut.key(), QKeySequence(QKeySequence.StandardKey.Copy))
            page.copy_png()
            self.assertFalse(APP.clipboard().image().isNull())
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
            window.load_path(ROOT / "sample_data" / "OCD_measurement_data.csv")
            self.select_parameters(window, {"OCD_H1", "OCD_H2"})
            page = window.radius_page
            self.assertIsNot(page.selector, window.plot_page.selector)
            self.assertEqual((page.selector.rowCount(), page.selector.columnCount()), (6, 2))
            page.selector.clearSelection()
            page.selector.item(1, 1).setSelected(True)
            page.draw_plot()
            self.assertTrue(page.ready)
            # Only the drawn box is laid out: the canvas no longer reserves the
            # full 6 x 2 grid around a single selected plot.
            self.assertEqual(len(page.figure.axes), 1)
            self.assertEqual(sum(ax.axison for ax in page.figure.axes), 1)
            self.assertIn("1 / 1 radius plots drawn", page.status.text())
            # The wafer-map selection keeps every box; the two selectors are independent.
            self.assertEqual(len(window.plot_page.selector.selected_cells()), 12)
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_radius_row_titles_do_not_collide_at_large_fonts(self):
        """A row's title must stay clear of the axis label of the row above."""
        for size in ("12", "14", "16"):
            with self.subTest(font=size):
                window = MainWindow()
                try:
                    window.load_path(ROOT / "sample_data" / "OCD_measurement_data.csv")
                    self.select_parameters(window, {"OCD_H1", "OCD_H2", "OCD_H3"})
                    window.tabs.setCurrentIndex(2)
                    page = window.radius_page
                    page.font_size.setCurrentText(size)
                    page.selector.selectAll()
                    page.draw_plot()
                    APP.processEvents()
                    self.assertTrue(page.ready, page.status.text())
                    page.figure.canvas.draw()
                    renderer = page.figure.canvas.get_renderer()
                    rows = {}
                    for axis in page.figure.axes:
                        rows.setdefault(round(axis.get_position().y0, 3), []).append(axis)
                    ordered = [rows[key] for key in sorted(rows, reverse=True)]
                    self.assertEqual(len(ordered), 6)
                    for upper, lower in zip(ordered, ordered[1:]):
                        label_bottom = min(axis.xaxis.label.get_window_extent(renderer).y0
                                           for axis in upper)
                        title_top = max(max(text.get_window_extent(renderer).y1
                                            for text in (axis.title, *axis._wafer_title_details))
                                        for axis in lower)
                        self.assertLess(title_top, label_bottom,
                                        f"font {size}: radius row title overlaps the label above")
                finally:
                    window.model.undo.setClean()
                    window.close()
                    window.deleteLater()
                    APP.processEvents()

    def test_radius_canvas_shrinks_to_the_drawn_boxes(self):
        window = MainWindow()
        try:
            window.load_path(ROOT / "sample_data" / "OCD_measurement_data.csv")
            self.select_parameters(window, {"NGOF", "OCD_H1"})
            page = window.radius_page
            self.assertEqual((page.selector.rowCount(), page.selector.columnCount()), (6, 2))
            page.selector.clearSelection()
            for row in (0, 1):
                for column in (0, 1):
                    page.selector.item(row, column).setSelected(True)
            page.draw_plot()
            self.assertTrue(page.ready, page.status.text())
            self.assertEqual(page.base_size, (2 * 460, 2 * 370 + 30))
            self.assertEqual(len(page.figure.axes), 4)
            self.assertIn("4 / 4 radius plots drawn", page.status.text())
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_replacing_data_after_first_draw_refreshes_radius_without_selector(self):
        window = MainWindow()
        try:
            window.load_path(ROOT / "sample_data" / "OCD_measurement_data.csv")
            self.select_parameters(window, {"OCD_H1", "OCD_H2"})
            page = window.radius_page
            page.selector.clearSelection()
            page.selector.item(1, 1).setSelected(True)
            page.draw_plot()
            self.assertTrue(page.ready, page.status.text())
            first_values = page.figure.axes[0].collections[0].get_offsets()[:, 1].copy()
            selected_cells = page.selector.selected_cells()

            replacement = window._frame.copy()
            replacement["OCD_H2"] = (
                pd.to_numeric(replacement["OCD_H2"]) + 100
            )
            window.set_table(replacement, "replacement.csv")

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not page.ready:
                QTest.qWait(20)
            window.tabs.setCurrentIndex(2)
            APP.processEvents()

            self.assertTrue(page.ready, page.status.text())
            self.assertEqual(page.selector.selected_cells(), selected_cells)
            self.assertIs(page.stack.currentWidget(), page.scroll)
            refreshed = page.figure.axes[0].collections[0].get_offsets()[:, 1]
            np.testing.assert_allclose(refreshed, first_values + 100)
            self.assertNotIn("select the plots", page.status.text().lower())
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_changing_radius_boxes_after_first_draw_refreshes_without_draw_click(self):
        window = MainWindow()
        try:
            window.load_path(ROOT / "sample_data" / "OCD_measurement_data.csv")
            self.select_parameters(window, {"OCD_H1", "OCD_H2"})
            page = window.radius_page
            first_cell = (page.selector.wafers[0], page.selector.metrics[0])
            page.selector.set_selected_cells({first_cell})
            page.draw_plot()
            self.assertTrue(page.ready, page.status.text())
            replacement_cell = (
                page.selector.wafers[1], page.selector.metrics[1]
            )

            page.selector.set_selected_cells({replacement_cell})
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and (
                not page.ready or page.drawn_cells != {replacement_cell}
            ):
                QTest.qWait(20)

            self.assertTrue(page.ready, page.status.text())
            self.assertEqual(page.drawn_cells, {replacement_cell})
            self.assertIs(page.stack.currentWidget(), page.scroll)
            self.assertNotIn("click Draw selected", page.status.text())
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_restored_radius_draw_state_redraws_without_draw_click(self):
        window = MainWindow()
        reopened = MainWindow()
        try:
            window.load_path(ROOT / "sample_data" / "OCD_measurement_data.csv")
            self.select_parameters(window, {"OCD_H1", "OCD_H2"})
            page = window.radius_page
            selected_cell = (page.selector.wafers[0], page.selector.metrics[0])
            page.selector.set_selected_cells({selected_cell})
            page.draw_plot()
            self.assertTrue(page.ready, page.status.text())
            saved_state = window.selection_state()

            reopened.set_table(window._frame.copy(), "reopened.wkb")
            reopened.restore_selection(saved_state)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not reopened.radius_page.ready:
                QTest.qWait(20)

            restored = reopened.radius_page
            self.assertTrue(restored.has_drawn_once)
            self.assertEqual(restored.drawn_cells, {selected_cell})
            self.assertIs(restored.stack.currentWidget(), restored.scroll)
            self.assertNotIn("click Draw selected", restored.status.text())
        finally:
            for workspace in (window, reopened):
                workspace.model.undo.setClean()
                workspace.close()
                workspace.deleteLater()
            APP.processEvents()


if __name__ == "__main__":
    unittest.main()
