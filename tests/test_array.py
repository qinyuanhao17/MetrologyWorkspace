"""Array preparation and plot-tab end-to-end regression tests."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from matplotlib import colormaps
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QImage, QKeySequence, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QLabel, QPushButton

from metrology_app.array_plot import ArrayOptions, draw_array, prepare_array
from metrology_app.appearance import MAX_COPY_PIXELS, configure_fonts, export_dpi
from metrology_app.window import MainWindow
from metrology_app.appearance import screen_render_scale
from metrology_app.settings import get_settings

ROOT = Path(__file__).resolve().parents[1]
APP = QApplication.instance() or QApplication([])
configure_fonts(APP)  # same font registration the launcher installs


class ArrayTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({"Wafer": ["001"] * 4 + ["002"] * 4,
                                   "X": [0, 1, 0, 1] * 2, "Y": [0, 0, 1, 1] * 2,
                                   "H": [1, 2, 3, 4, 7, 8, 9, 10], "W": [10, 20, 30, 40] * 2})
        self.selection = {"wafer_column": "Wafer", "wafers": ["002", "001"], "metrics": ["W", "H"]}

    def test_order_and_shared_scale(self):
        result = prepare_array(self.frame, self.selection, ArrayOptions("X", "Y", shared_scale=True))
        self.assertEqual(result["shape"], (2, 2))
        self.assertEqual([(s["wafer"], s["metric"]) for s in result["scenes"]],
                         [("002", "W"), ("002", "H"), ("001", "W"), ("001", "H")])
        self.assertEqual(result["scenes"][1]["options"].limits, (1, 10))
        self.assertTrue(all(not s["error"] for s in result["scenes"]))

    def test_independent_scale_is_default(self):
        result = prepare_array(self.frame, self.selection, ArrayOptions("X", "Y"))
        self.assertTrue(all(scene["options"].limits is None for scene in result["scenes"]))
        self.assertEqual(result["settings"].cmap, "turbo")

    def test_duplicates_rejected_without_averaging(self):
        repeated = pd.concat([self.frame, self.frame], ignore_index=True)
        result = prepare_array(repeated, self.selection, ArrayOptions("X", "Y"))
        self.assertTrue(all("Duplicate" in s["error"] for s in result["scenes"]))
        repeated["Group"] = ["A"] * 8 + ["B"] * 8
        result = prepare_array(repeated, self.selection, ArrayOptions("X", "Y"))
        self.assertTrue(all("Duplicate" in s["error"] for s in result["scenes"]))

    def test_only_selected_cells_are_computed(self):
        self.selection["cells"] = [("001", "H")]
        result = prepare_array(self.frame, self.selection, ArrayOptions("X", "Y"))
        self.assertEqual(result["selected_count"], 1)
        self.assertEqual(sum(bool(s.get("skip")) for s in result["scenes"]), 3)
        self.assertIsNone(result["scenes"][3]["options"].limits)
        self.assertTrue(all("surface" not in s for s in result["scenes"][:3]))
        self.selection["cells"] = []
        with self.assertRaisesRegex(ValueError, "at least one map"):
            prepare_array(self.frame, self.selection, ArrayOptions("X", "Y"))

    def test_contour_lines_and_point_outline(self):
        selection = {"wafer_column": "Wafer", "wafers": ["001"], "metrics": ["H"]}
        result = prepare_array(self.frame, selection,
                               ArrayOptions("X", "Y", contour=True, point_outline=True))
        figure = Figure(figsize=(4, 4))
        artists = draw_array(figure, result, 10)
        plot, scene = artists[0]
        self.assertTrue(any(hasattr(collection, "levels") for collection in plot.axes.collections))
        self.assertIsNone(plot.point_markers.get_array())
        self.assertTrue(plot.point_markers.get_linewidths()[0] > 0)

    def test_large_font_keeps_outer_labels_inside_the_canvas(self):
        selection = {"wafer_column": "Wafer", "wafers": ["001"], "metrics": ["H"]}
        result = prepare_array(self.frame, selection, ArrayOptions("X", "Y"))
        figure = Figure(figsize=(5, 4))
        canvas = FigureCanvasAgg(figure)
        artists = draw_array(figure, result, 16)
        canvas.draw()
        renderer = canvas.get_renderer()
        ax = artists[0][0].axes
        height = figure.get_size_inches()[1] * figure.dpi
        self.assertGreaterEqual(ax.yaxis.label.get_window_extent(renderer).x0, 0)
        self.assertGreaterEqual(ax.xaxis.label.get_window_extent(renderer).y0, 0)
        title_top = max([ax.title.get_window_extent(renderer).y1]
                        + [text.get_window_extent(renderer).y1 for text in ax._wafer_title_details])
        self.assertLessEqual(title_top, height)

    def test_manual_colour_scale_limits(self):
        selection = {"wafer_column": "Wafer", "wafers": ["001"], "metrics": ["H"]}
        result = prepare_array(self.frame, selection, ArrayOptions("X", "Y", limits=(3.0, None)))
        figure = Figure(figsize=(4, 4))
        artists = draw_array(figure, result, 10)
        self.assertEqual(artists[0][0].axes.images[0].get_clim(), (3.0, 4.0))
        auto = prepare_array(self.frame, selection, ArrayOptions("X", "Y"))
        auto_figure = Figure(figsize=(4, 4))
        auto_artists = draw_array(auto_figure, auto, 10)
        self.assertEqual(auto_artists[0][0].axes.images[0].get_clim(), (1.0, 4.0))

    def test_map_opacity_option(self):
        selection = {"wafer_column": "Wafer", "wafers": ["001"], "metrics": ["H"]}
        result = prepare_array(self.frame, selection, ArrayOptions("X", "Y", opacity=0.5))
        figure = Figure(figsize=(4, 4))
        artists = draw_array(figure, result, 10)
        self.assertEqual(artists[0][0].axes.images[0].get_alpha(), 0.5)
        clear = prepare_array(self.frame, selection, ArrayOptions("X", "Y"))
        clear_figure = Figure(figsize=(4, 4))
        clear_artists = draw_array(clear_figure, clear, 10)
        self.assertEqual(clear_artists[0][0].axes.images[0].get_alpha(), 1.0)

    def test_palette_range_bar_changes_the_colours(self):
        from metrology_app.color_range_bar import ColorRangeBar

        bar = ColorRangeBar()
        bar.set_colormap(colormaps["turbo"])
        bar.resize(200, 26)
        bar.show()
        APP.processEvents()
        self.assertEqual(bar.range(), (0.0, 1.0))
        bar.set_range(0.30, 1.0)
        seen = []
        bar.changed.connect(lambda low, high: seen.append((low, high)))
        start = QPoint(int(bar.x_of(0.30)), bar.height() // 2)
        bar.set_range(0.30, 1.0)
        QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(bar, QPoint(int(bar.x_of(0.55)), bar.height() // 2), delay=10)
        QTest.mouseRelease(bar, Qt.MouseButton.LeftButton,
                           pos=QPoint(int(bar.x_of(0.55)), bar.height() // 2))
        APP.processEvents()
        self.assertGreater(bar.range()[0], 0.4)
        self.assertTrue(seen)
        bar.set_range(0.7, 0.71)
        self.assertGreaterEqual(bar.range()[1] - bar.range()[0], bar.GAP - 1e-9)

        selection = {"wafer_column": "Wafer", "wafers": ["001"], "metrics": ["H"]}
        auto = prepare_array(self.frame, selection, ArrayOptions("X", "Y"))
        narrow = prepare_array(self.frame, selection, ArrayOptions("X", "Y", cmap_range=(0.5, 0.9)))
        auto_figure, narrow_figure = Figure(figsize=(4, 4)), Figure(figsize=(4, 4))
        auto_artists = draw_array(auto_figure, auto, 10)
        narrow_artists = draw_array(narrow_figure, narrow, 10)
        self.assertFalse(np.allclose(auto_artists[0][0].axes.images[0].get_cmap()(0.0)[:3],
                                     narrow_artists[0][0].axes.images[0].get_cmap()(0.0)[:3]))

    def test_missing_metric_keeps_array_cell(self):
        self.frame.loc[self.frame.Wafer == "002", "H"] = np.nan
        result = prepare_array(self.frame, self.selection, ArrayOptions("X", "Y"))
        self.assertEqual(len(result["scenes"]), 4)
        self.assertIn("No valid", result["scenes"][1]["error"])
        self.assertIsNone(result["scenes"][3]["options"].limits)

    def test_geometry_mask_validation_and_cancellation(self):
        options = ArrayOptions("X", "Y", diameter=4, fill_edge=False, shared_scale=False)
        result = prepare_array(self.frame, self.selection, options)
        self.assertEqual(result["geometry"], (0, 0, 2))
        for scene in result["scenes"]:
            surface, edge = scene["surface"][-2:]
            self.assertTrue(surface.mask[edge].all())
            self.assertIsNone(scene["options"].limits)
        options.diameter = -1
        with self.assertRaisesRegex(ValueError, "Diameter"):
            prepare_array(self.frame, self.selection, options)
        self.assertIsNone(prepare_array(self.frame, self.selection, ArrayOptions("X", "Y"), cancelled=lambda: True))


class PlotWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.window = MainWindow()
        self.window.show()
        self.window.load_path(ROOT / "sample_data" / "OCD_measurement_data.csv")

    def tearDown(self):
        self.window.model.undo.setClean()
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def wait_render(self):
        page = self.window.plot_page
        start = time.monotonic()
        while page.worker is not None and time.monotonic() - start < 25:
            QTest.qWait(20)
        self.assertIsNone(page.worker, "Background render did not complete")

    def unique_fixture(self):
        # Test-only in-memory input: the app must never silently filter the real CSV.
        frame = self.window._frame
        self.window.set_table(frame[frame['PAD Name'] == frame['PAD Name'].iloc[0]], "Single-measurement test fixture")
        self.select_metrics("OCD_H1", "OCD_H2", "OCD_H3")

    def test_selector_guidance_uses_control_tooltips_not_inline_hint_rows(self):
        expectations = (
            (self.window.plot_page, "Drag to select maps"),
            (self.window.radius_page, "Drag to select plots"),
        )
        for page, guidance in expectations:
            self.assertIn(guidance, page.select_button.toolTip())
            self.assertFalse(any(
                label.text().startswith(guidance)
                for label in page.findChildren(QLabel)
            ))

    def select_metrics(self, *names):
        chosen = set(names)
        tree = self.window.parameter_list
        tree.blockSignals(True)
        for index in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(index)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(0, Qt.CheckState.Checked if item.text(0) in chosen else Qt.CheckState.Unchecked)
        tree.blockSignals(False)
        self.window.update_plan()

    @staticmethod
    def toolbar_rows(page):
        """Return the horizontal control rows of a workspace page, outermost first."""
        rows = []

        def collect(layout):
            for index in range(layout.count()):
                child = layout.itemAt(index).layout()
                if child is None:
                    continue
                if isinstance(child, QHBoxLayout):
                    rows.append(child)
                collect(child)

        collect(page.layout())
        return rows

    def test_toolbar_rows_fit_the_smallest_window(self):
        """No toolbar label may be squeezed, overlapped or clipped at 1180 x 760."""
        self.window.resize(1180, 760)
        for index in (1, 2):
            self.window.tabs.setCurrentIndex(index)
            APP.processEvents()
            page = self.window.tabs.widget(index)
            rows = self.toolbar_rows(page)
            self.assertTrue(rows, page.objectName())
            for row in rows:
                widgets = [row.itemAt(position).widget() for position in range(row.count())]
                widgets = [widget for widget in widgets if widget is not None]
                self.assertLessEqual(row.minimumSize().width(), page.width(),
                                     f"{page.objectName()} toolbar needs {row.minimumSize().width()} px")
                spans = [(widget.geometry().x(),
                          widget.geometry().x() + widget.geometry().width()) for widget in widgets]
                for (_, left_end), (right_start, _) in zip(spans, spans[1:]):
                    self.assertLessEqual(left_end, right_start, f"{page.objectName()} toolbar overlaps")
                for widget, (_, end) in zip(widgets, spans):
                    self.assertLessEqual(end, page.width(), f"{page.objectName()} toolbar is clipped")
                    fixed = widget.minimumWidth() == widget.maximumWidth()
                    floor = widget.minimumWidth() if fixed else max(widget.minimumWidth(),
                                                                    widget.minimumSizeHint().width())
                    self.assertGreaterEqual(widget.geometry().width(), floor,
                                            f"{page.objectName()} squeezed a control")
            self.assertGreaterEqual(page.summary.geometry().width(), page.summary.sizeHint().width(),
                                    f"{page.objectName()} clipped its summary")

    def test_row_titles_do_not_collide_at_large_fonts(self):
        """A row's three-line title must stay clear of the row above's axis label."""
        for size in ("12", "14", "16"):
            with self.subTest(font=size):
                self.unique_fixture()
                w, page = self.window, self.window.plot_page
                w.tabs.setCurrentIndex(1)
                w.resize(1520, 950)
                APP.processEvents()
                page.font_size.setCurrentText(size)
                QTest.qWait(250)
                page.selector.selectAll()
                page.draw_maps()
                self.wait_render()
                page.figure.canvas.draw()
                renderer = page.figure.canvas.get_renderer()
                axes = [plot.axes for plot, _scene in page.artists]
                rows = {}
                for axis in axes:
                    rows.setdefault(round(axis.get_position().y0, 3), []).append(axis)
                ordered = [rows[key] for key in sorted(rows, reverse=True)]  # top row first
                for upper, lower in zip(ordered, ordered[1:]):
                    label_bottom = min(axis.xaxis.label.get_window_extent(renderer).y0
                                       for axis in upper)
                    title_top = max(max(text.get_window_extent(renderer).y1
                                        for text in (axis.title, *axis._wafer_title_details))
                                    for axis in lower)
                    self.assertLess(title_top, label_bottom,
                                    f"font {size}: row title overlaps the axis label above")
                footer = page.figure._supxlabel
                if footer is not None:
                    footer_top = footer.get_window_extent(renderer).y1
                    label_bottom = min(axis.xaxis.label.get_window_extent(renderer).y0
                                       for axis in ordered[-1])
                    self.assertGreater(label_bottom, footer_top,
                                       f"font {size}: bottom row overlaps the footer note")

    def test_checkbox_toggles_repaint_without_a_full_draw(self):
        """Overlay, outline, contour and colour toggles stay on the blit path."""
        w, page = self.window, self.window.plot_page
        w.check_all(w.wafer_list, True)
        self.select_metrics("NGOF", "OCD_H1")
        w.tabs.setCurrentIndex(1)
        APP.processEvents()
        page.selector.selectAll()
        page.draw_maps()
        self.wait_render()
        APP.processEvents()
        self.assertIsNotNone(page._background)
        self.assertIsNotNone(page._empty)

        with patch.object(page.canvas, "draw") as redraw:
            page.labels.setChecked(not page.labels.isChecked())
            page.points.setChecked(not page.points.isChecked())
            page.contour.setChecked(not page.contour.isChecked())
            page.point_outline.setChecked(not page.point_outline.isChecked())
            page.opacity.setCurrentText("80%")
            page.color_map.setCurrentText("Viridis")
            QTest.qWait(400)
            APP.processEvents()
            redraw.assert_not_called()
        self.assertTrue(page.artists[0][0].contours.get_visible())
        self.assertEqual(page.artists[0][0].image.get_alpha(), .8)

    def test_option_redraw_keeps_the_view(self):
        """Toggling Fill edge must not resize, rescale or scroll the canvas."""
        w, page = self.window, self.window.plot_page
        w.check_all(w.wafer_list, True)
        self.select_metrics("NGOF", "OCD_H1")
        w.tabs.setCurrentIndex(1)
        w.resize(1520, 950)
        APP.processEvents()
        page.selector.selectAll()
        page.draw_maps()
        self.wait_render()
        APP.processEvents()

        page.zoom.setCurrentText("200%")
        APP.processEvents()
        page.scroll.horizontalScrollBar().setValue(120)
        page.scroll.verticalScrollBar().setValue(260)
        APP.processEvents()
        canvas = (page.canvas.width(), page.canvas.height())
        scale = page.scroll.transform().m11()
        self.assertGreater(page.scroll.verticalScrollBar().maximum(), 0)

        page.fill_edge.setChecked(not page.fill_edge.isChecked())
        self.wait_render()
        APP.processEvents()
        QTest.qWait(50)
        self.assertEqual((page.canvas.width(), page.canvas.height()), canvas)
        self.assertAlmostEqual(page.scroll.transform().m11(), scale, places=6)
        self.assertEqual(page.scroll.horizontalScrollBar().value(), 120)
        self.assertEqual(page.scroll.verticalScrollBar().value(), 260)

    def test_canvas_shrinks_to_the_drawn_boxes(self):
        """A sub-block selection must not leave the rest of the array as blank canvas."""
        w, page = self.window, self.window.plot_page
        w.check_all(w.wafer_list, True)
        self.select_metrics("NGOF", "OCD_H1")
        w.tabs.setCurrentIndex(1)
        boxes = page.selector
        self.assertEqual((boxes.rowCount(), boxes.columnCount()), (6, 2))

        boxes.clearSelection()
        for row in (0, 1):
            for column in (0, 1):
                boxes.item(row, column).setSelected(True)
        page.draw_maps()
        self.wait_render()
        self.assertEqual(page.result["shape"], (2, 2))
        self.assertEqual(len(page.artists), 4)
        self.assertFalse(any(scene.get("skip") for scene in page.result["scenes"]))
        width, height = page.figure.get_size_inches()
        self.assertAlmostEqual(width * 100, 2 * 460)
        self.assertAlmostEqual(height * 100, 2 * 420 + 30)

        # Scattered boxes keep their relative order: only the rows and columns
        # that hold a drawn box reach the canvas, the gaps between them stay.
        boxes.clearSelection()
        boxes.item(0, 0).setSelected(True)
        boxes.item(5, 1).setSelected(True)
        page.draw_maps()
        self.wait_render()
        self.assertEqual(page.result["shape"], (2, 2))
        self.assertEqual(len(page.artists), 2)
        self.assertEqual(sum(bool(scene.get("skip")) for scene in page.result["scenes"]), 2)

    def test_compact_layout_and_simple_column_names(self):
        w = self.window
        self.assertEqual(w.tabs.tabText(0), "1. Data")
        self.assertFalse(any(c.text() == "Data workspace" for c in w.findChildren(QLabel)))
        self.assertIn("Wafer ID / Lot ID / PAD Name", w.group_picker.text())
        paste = next(b for b in w.findChildren(QPushButton) if b.text() == "Paste table")
        self.assertEqual(paste.parentWidget().objectName(), "sheetCard")
        # The table takes the bulk of a normal-sized workspace window; the
        # startup window itself now adapts to the display, so size it here.
        w.resize(1520, 950)
        QTest.qWait(50)
        self.assertGreater(w.sheet.height(), 600)
        labels = [c.text() for c in w.findChildren(QLabel)]
        self.assertNotIn("LOCAL", labels)
        self.assertNotIn("Wafer Insight", labels)
        self.assertNotIn("Group by", labels)
        self.assertNotIn("Center X", labels)
        controls = [b for b in w.findChildren(QPushButton) if b.text() in ("New", "Open file", "Paste table", "Save CSV")]
        self.assertEqual({(b.width(), b.height()) for b in controls}, {(104, 34)})
        self.assertFalse(any(b.objectName() == "planCard" for b in w.findChildren(QPushButton)))
        longest = max(w.measurements[0].label.splitlines(), key=len)
        self.assertGreater(w.wafer_list.columnWidth(0), w.wafer_list.fontMetrics().horizontalAdvance(longest) + 24)

    def test_render_selected_and_full_export(self):
        self.unique_fixture()
        w, page = self.window, self.window.plot_page
        settings = get_settings()
        self.assertEqual(page.shared.isChecked(), bool(settings["shared_scale"]))
        self.assertEqual(page.color_map.currentData(), settings["color_map"])
        self.assertIn("Rainbow", [page.color_map.itemText(i) for i in range(page.color_map.count())])
        self.assertGreaterEqual(page.color_map.count(), 13)
        self.assertTrue(all(page.color_map.itemData(i) in colormaps
                            for i in range(page.color_map.count())))
        self.assertEqual(page.labels.isChecked(), bool(settings["point_values"]))
        self.assertEqual(page.points.isChecked(), bool(settings["measurement_points"]))
        page.labels.setChecked(True)
        page.points.setChecked(True)
        self.assertEqual((page.x_column.currentText(), page.y_column.currentText()), ("X(mm)", "Y(mm)"))
        w.tabs.setCurrentIndex(1)
        self.assertIsNone(page.worker)
        page.draw_maps()
        self.wait_render()
        self.assertIsNotNone(page.result, page.empty.text())
        self.assertEqual(page.resolution.currentText(), settings["resolution"])
        screen_scale = {"Standard": 1, "High": 1.5, "Ultra": 2}[page.resolution.currentText()]
        screen_scale = screen_render_scale(3 * 460, 3 * 420 + 30, screen_scale)
        self.assertEqual(page.canvas.width(), round(3 * 460 * screen_scale))
        self.assertEqual(page.result["shape"], (3, 3))
        self.assertEqual(len(page.artists), 9)
        self.assertTrue(all(len(scene["layer"]) == 80 for scene in page.result["scenes"]))
        self.assertTrue(all(all(s.get_visible() for s in plot.axes.spines.values()) for plot, _ in page.artists))
        self.assertEqual(len(page.figure.axes), 18)  # 9 maps + 9 colorbars
        self.assertIsNone(page.figure._suptitle)
        self.assertTrue(page.copy_button.isEnabled())
        self.assertEqual(page.copy_shortcut.key(), QKeySequence(QKeySequence.StandardKey.Copy))
        page.copy_png()
        copied = APP.clipboard().image()
        self.assertFalse(copied.isNull())
        export_scale = {"Standard": 2, "High": 3, "Ultra": 4}[page.resolution.currentText()]
        # The copy follows the chosen quality, but an array this tall is capped
        # so the clipboard image stays pasteable.
        expected_dpi = export_dpi(page.figure, export_scale * 100, MAX_COPY_PIXELS)
        self.assertEqual(copied.width(), round(3 * 460 * expected_dpi / 100))
        if expected_dpi < export_scale * 100:
            self.assertIn("capped", page.status.text())
        page.font_size.setCurrentText("14")
        QTest.qWait(250)
        axis = page.artists[0][0].axes
        self.assertEqual(axis.title.get_fontsize(), 14)
        self.assertEqual(axis.title.get_fontweight(), "bold")
        self.assertTrue(all(text.get_ha() == "center" for text in axis._wafer_title_details))
        self.assertEqual(axis.xaxis.label.get_fontsize(), 13)
        self.assertEqual(axis.get_xticklabels()[0].get_fontsize(), 12)
        self.assertTrue(page.artists[0][0].value_labels.get_visible())
        self.assertTrue(page.artists[0][0].point_markers.get_visible())
        page.labels.setChecked(False)
        page.points.setChecked(False)
        QTest.qWait(200)   # the overlay toggles are merged into one fast repaint
        self.assertFalse(page.artists[0][0].value_labels.get_visible())
        self.assertFalse(page.artists[0][0].point_markers.get_visible())
        self.assertIsNotNone(page.result)
        page.labels.setChecked(True)
        page.points.setChecked(True)
        QTest.qWait(200)
        # View zoom touches only the Qt view transform, never the render.
        page.zoom.setCurrentText("100%")
        APP.processEvents()
        with patch.object(page.canvas, "draw") as redraw:
            page.zoom_by_wheel(120)
            self.assertEqual(page.zoom.currentText(), "125%")
            page.zoom_by_wheel(-120)
            self.assertEqual(page.zoom.currentText(), "100%")
            APP.processEvents()
            redraw.assert_not_called()
        page.zoom.setCurrentText("Fit width")
        w.resize(1180, 760)
        QTest.qWait(100)
        self.assertEqual(page.scroll.horizontalScrollBar().maximum(), 0)
        page.zoom.setCurrentText("200%")
        QTest.qWait(100)
        self.assertGreater(page.scroll.horizontalScrollBar().maximum(), 0)
        page.scroll.horizontalScrollBar().setValue(page.scroll.horizontalScrollBar().minimum())
        horizontal = page.scroll.horizontalScrollBar().value()
        vertical = page.scroll.verticalScrollBar().value()
        page.points.setChecked(not page.points.isChecked())
        QTest.qWait(20)
        # Toggling an overlay repaints it in place: the view must not move.
        self.assertEqual(page.scroll.horizontalScrollBar().value(), horizontal)
        self.assertEqual(page.scroll.verticalScrollBar().value(), vertical)

        # Resolution supersamples the screen raster and drives the export DPI,
        # exactly as before; Export… additionally offers vector output.
        page.resolution.setCurrentText("Standard")
        self.assertEqual(page.canvas.width(), 3 * 460)
        self.assertIsNotNone(page.result)
        page.resolution.setCurrentText("High")
        zoom_wheel = QWheelEvent(QPointF(20, 20), QPointF(20, 20), QPoint(), QPoint(0, 120),
                                 Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier,
                                 Qt.ScrollPhase.ScrollUpdate, False)
        self.assertTrue(page.eventFilter(page.canvas, zoom_wheel))
        self.assertEqual(page.zoom.currentText(), "250%")
        page.scroll.verticalScrollBar().setValue(0)
        wheel = QWheelEvent(QPointF(20, 20), QPointF(20, 20), QPoint(), QPoint(0, -120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                            Qt.ScrollPhase.ScrollUpdate, False)
        self.assertTrue(page.eventFilter(page.canvas, wheel))
        self.assertGreater(page.scroll.verticalScrollBar().value(), 0)
        page.zoom.setCurrentText("Fit width")
        QTest.qWait(100)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "array.png"
            with patch.object(QFileDialog, "getSaveFileName",
                              return_value=(str(path), "PNG image (*.png)")):
                page.export_image()
            self.assertGreater(path.stat().st_size, 100000)
            page.resolution.setCurrentText("Ultra")
            large = Path(folder) / "array_ultra.png"
            with patch.object(QFileDialog, "getSaveFileName",
                              return_value=(str(large), "PNG image (*.png)")):
                page.export_image()
            self.assertGreater(QImage(str(large)).width(), QImage(str(path)).width())
            page.resolution.setCurrentText("Standard")

            # Vector output: axes, text and iso-lines stay vector; only the
            # interpolated colour field is embedded as a raster layer.
            svg = Path(folder) / "array.svg"
            with patch.object(QFileDialog, "getSaveFileName",
                              return_value=(str(svg), "SVG vector (*.svg)")):
                page.export_image()
            markup = svg.read_text(encoding="utf-8", errors="replace")
            self.assertIn("<svg", markup[:4000])
            self.assertIn("<path", markup)          # axes, text and points stay vector
            # Only the interpolated colour field is rasterised: one embedded
            # image per map and colour bar, not one bitmap of the whole figure.
            self.assertEqual(markup.count("<image"), 2 * len(page.artists))
            pdf = Path(folder) / "array.pdf"
            with patch.object(QFileDialog, "getSaveFileName",
                              return_value=(str(pdf), "PDF vector (*.pdf)")):
                page.export_image()
            self.assertEqual(pdf.read_bytes()[:4], b"%PDF")
        page.resolution.setCurrentText("High")
        page.show_selector()
        page.selector.clearSelection()
        page.selector.item(1, 1).setSelected(True)
        self.assertIsNone(page.result)
        self.assertFalse(page.export_button.isEnabled())
        page.draw_maps()
        self.wait_render()
        self.assertEqual(len(page.artists), 1)
        # The canvas is laid out for the drawn boxes only, so a single selected
        # box no longer reserves the whole 3 x 3 array.
        self.assertEqual(page.result["shape"], (1, 1))
        self.assertEqual(page.result["selected_count"], 1)
        self.assertEqual(sum(ax.axison for ax in page.figure.axes), 2)  # Selected map + colorbar
        previous_result = page.result
        expected_fill = not page.fill_edge.isChecked()
        page.fill_edge.setChecked(expected_fill)
        self.assertIs(page.stack.currentWidget(), page.scroll)
        self.assertIs(page.result, previous_result)
        self.wait_render()
        self.assertIs(page.stack.currentWidget(), page.scroll)
        self.assertIsNot(page.result, previous_result)
        self.assertEqual(page.result["settings"].fill_edge, expected_fill)
        page.color_map.setCurrentText("Plasma")
        QTest.qWait(300)
        self.assertTrue(page.artists[0][0].axes.images[0].get_cmap().name.startswith("plasma"))
        page.color_map.setCurrentText("Rainbow")
        QTest.qWait(300)
        self.assertTrue(page.artists[0][0].axes.images[0].get_cmap().name.startswith("rainbow"))
        self.assertEqual(page.color_range.range(), (0.0, 1.0))
        with patch("metrology_app.plot_page.save_settings") as persist:
            page.color_range.set_range(.2, .8, notify=True)
            QTest.qWait(400)
            persist.assert_called_once_with({
                "color_map": "rainbow", "color_range_low": .2, "color_range_high": .8,
            })
        page.scale_bar.setChecked(False)
        QTest.qWait(300)
        self.assertIsNone(page.artists[0][0].colorbar)
        # One drawn box keeps one panel; only its colorbar disappears.
        self.assertEqual(len(page.figure.axes), 1)
        page.diameter.setCurrentText("invalid")
        page.draw_maps()
        self.assertIsNone(page.result)
        self.assertEqual(page.stack.currentIndex(), 0)

    def test_saved_color_range_is_restored(self):
        from metrology_app.plot_page import PlotPage

        preferences = dict(get_settings(), color_map="rainbow",
                           color_range_low=.18, color_range_high=.82)
        with patch("metrology_app.plot_page.get_settings", return_value=preferences):
            page = PlotPage()
        try:
            self.assertEqual(page.color_map.currentData(), "rainbow")
            self.assertEqual(page.color_range.range(), (.18, .82))
        finally:
            page.stop()
            page.deleteLater()
            APP.processEvents()

    def test_changed_selection_discards_running_job(self):
        self.unique_fixture()
        w, page = self.window, self.window.plot_page
        w.tabs.setCurrentIndex(1)
        page.draw_maps()
        w.wafer_list.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
        self.wait_render()
        self.assertIsNone(page.result)
        self.assertTrue(page.dirty)
        page.draw_maps()
        self.wait_render()
        self.assertEqual(page.result["shape"], (2, 3))
        w.model.edit({(1, 10): "1.234"})
        w.recognize()
        self.assertIsNone(page.result)
        self.assertFalse(page.export_button.isEnabled())

    def test_map_array_click_drag_and_ctrl_selection(self):
        w, page = self.window, self.window.plot_page
        self.select_metrics("OCD_H1", "OCD_H2", "OCD_H3")
        w.tabs.setCurrentIndex(1)
        page.show_selector()
        QTest.qWait(50)
        self.assertEqual(w.tabs.currentIndex(), 1)
        self.assertIs(page.stack.currentWidget(), page.selector_panel)
        boxes = page.selector
        boxes.clearSelection()
        start, end = (boxes.visualItemRect(boxes.item(r, c)).center() for r, c in ((0, 0), (1, 1)))
        QTest.mousePress(boxes.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(boxes.viewport(), end, delay=30)
        QTest.mouseRelease(boxes.viewport(), Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(len(boxes.selected_cells()), 4)
        extra = boxes.visualItemRect(boxes.item(2, 2)).center()
        QTest.mouseClick(boxes.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, pos=extra)
        self.assertEqual(len(boxes.selected_cells()), 5)
        boxes.clearSelection()
        page.draw_maps()
        self.assertIn("Select at least one map", page.empty.text())

    def test_real_csv_auto_groups_all_measurements(self):
        page = self.window.plot_page
        self.select_metrics("OCD_H1", "OCD_H2", "OCD_H3")
        self.assertEqual(self.window.wafer_list.topLevelItemCount(), 6)
        self.assertTrue(all(len(m.rows) == 80 for m in self.window.measurements))
        self.window.tabs.setCurrentIndex(1)
        page.draw_maps()
        self.wait_render()
        self.assertEqual(len(page.artists), 18)
        self.assertEqual(page.result["shape"], (6, 3))
        self.assertTrue(all(len(scene['layer']) == 80 for scene in page.result["scenes"]))
        self.assertTrue(page.export_button.isEnabled())
        self.assertIn("300 mm", page.result["size_summary"])
        self.assertEqual(page.artists[0][0].axes.get_xlim(), (-150, 150))
        np.testing.assert_allclose(page.artists[0][0].axes.get_xticks(),
                                   [-150, -100, -50, 0, 50, 100, 150])
        first, second = page.result['scenes'][0], page.result['scenes'][3]
        self.assertNotEqual(first['label'], second['label'])
        self.assertFalse(np.allclose(first['layer'].value, second['layer'].value))


if __name__ == "__main__":
    unittest.main()
