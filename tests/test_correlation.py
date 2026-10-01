"""Pairwise lmfit analysis and loadable correlation workspace tests."""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QKeySequence, QPalette, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel

from metrology_app.correlation_page import fit_numeric_pair, pairwise_linear_fits
from metrology_app.correlation_window import CorrelationWindow
from metrology_app.matching import ParameterMapping
from metrology_app.appearance import MAX_COPY_PIXELS, configure_fonts
from metrology_app import settings as settings_module
from metrology_app.settings import get_settings
from metrology_app.window import MainWindow as WaferMapWindow


ROOT = Path(__file__).resolve().parents[1]
APP = QApplication.instance() or QApplication([])
configure_fonts(APP)  # same font registration the launcher installs


class CorrelationTests(unittest.TestCase):
    def setUp(self):
        self._saved_overlay = get_settings().get("trend_overlay", {})
        settings_module._current["trend_overlay"] = {}
        self._settings_patch = patch("metrology_app.sequence_page.save_settings")
        self._settings_patch.start()

    def tearDown(self):
        self._settings_patch.stop()
        settings_module._current["trend_overlay"] = self._saved_overlay

    @staticmethod
    def linear_frame(size=12):
        x = np.linspace(-2, 2, size)
        return pd.DataFrame({"Wafer ID": ["W1"] * size, "A": x, "B": 2 * x + 1, "C": 3 * x - 1})

    @staticmethod
    def select_parameters(window, names):
        tree = window.parameter_list
        tree.blockSignals(True)
        for index in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(index)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(0, Qt.CheckState.Checked if item.text(0) in names
                                   else Qt.CheckState.Unchecked)
        tree.blockSignals(False)
        window.update_plan()

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

    def test_workbook_sources_use_the_standard_tool_and_match_colours(self):
        reference = pd.DataFrame({
            "Wafer ID": ["Reference"] * 5,
            "PAD Name": ["Reference PAD"] * 5,
            "Die Seq": [101, 102, 103, 104, 105],
            "DP Ref": [10.0, 11.0, 12.0, 13.0, 14.0],
            "EW Ref": [20.0, 22.0, 24.0, 26.0, 28.0],
        })
        raw = pd.DataFrame({
            "Wafer ID": ["W1"] * 5,
            "PAD Name": ["P1"] * 5,
            "Die Seq": [1, 2, 3, 4, 5],
            "DP Raw": [9.0, 10.0, 11.0, 12.0, 13.0],
            "EW Raw": [19.0, 20.0, 23.0, 25.0, 27.0],
            "Raw only": [100, 101, 102, 103, 104],
        })
        mappings = (
            ParameterMapping("DP", "DP Ref", "DP Raw"),
            ParameterMapping("EW", "EW Ref", "EW Raw"),
        )
        window = CorrelationWindow()
        try:
            window.set_sources(reference, raw, mappings, "Preview")

            self.assertEqual(
                [window.tabs.tabText(index) for index in range(window.tabs.count())],
                ["1. Ref Data", "2. Raw Data", "3. Correlation", "4. Trend"],
            )
            self.assertEqual(tuple(window.raw_model.frame()), tuple(raw))
            self.assertEqual(
                window.reference_model.frame()["Wafer ID"].tolist(),
                raw["Wafer ID"].astype(str).tolist(),
            )
            self.assertEqual(
                window.reference_model.frame()["PAD Name"].tolist(),
                raw["PAD Name"].astype(str).tolist(),
            )
            self.assertEqual(
                window.reference_model.frame()["Die Seq"].tolist(),
                raw["Die Seq"].astype(str).tolist(),
            )
            self.assertEqual(window.selection["metrics"], ["DP", "EW"])
            self.assertEqual(len(window.selection["wafers"]), 2)

            window.correlation_page.selector.selectAll()
            window.correlation_page.draw_plot()
            self.assertEqual(len(window.correlation_page.plot_widgets), 2)
            reference_items = {
                item.name(): item
                for item in window.correlation_page.plot_widgets[0]
                .getPlotItem().listDataItems()
            }
            raw_items = {
                item.name(): item
                for item in window.correlation_page.plot_widgets[1]
                .getPlotItem().listDataItems()
            }
            self.assertEqual(
                reference_items["Reference fit"].opts["pen"].color().name(),
                "#ed7d31",
            )
            self.assertEqual(
                raw_items["Raw Data fit"].opts["pen"].color().name(),
                "#5b9bd5",
            )

            window.sequence_page.selector.selectAll()
            window.sequence_page.draw_plot()
            self.assertEqual(len(window.sequence_page.plot_widgets), 4)
            self.assertEqual(
                window.sequence_page.plot_widgets[0]
                .getPlotItem().getAxis("bottom").labelText,
                "Die Seq",
            )
            trend_items = {
                item.name(): item
                for item in window.sequence_page.plot_widgets[0]
                .getPlotItem().listDataItems()
            }
            self.assertEqual(
                trend_items["Reference"].opts["pen"].color().name(),
                "#ed7d31",
            )
            raw_trend_items = {
                item.name(): item
                for item in window.sequence_page.plot_widgets[2]
                .getPlotItem().listDataItems()
            }
            self.assertEqual(
                raw_trend_items["Raw Data"].opts["pen"].color().name(),
                "#5b9bd5",
            )
        finally:
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_loading_a_regular_table_leaves_workbook_source_mode(self):
        reference = pd.DataFrame({
            "DP Ref": [1.0, 2.0, 3.0],
            "EW Ref": [2.0, 4.0, 6.0],
        })
        raw = pd.DataFrame({
            "DP Raw": [1.1, 2.1, 3.1],
            "EW Raw": [2.2, 4.2, 6.2],
        })
        mappings = (
            ParameterMapping("DP", "DP Ref", "DP Raw"),
            ParameterMapping("EW", "EW Ref", "EW Raw"),
        )
        window = CorrelationWindow()
        try:
            window.set_sources(reference, raw, mappings, "Preview")
            window.set_table(self.linear_frame(), "standalone.csv")

            self.assertNotIn("sources", window.selection)
            self.assertNotIn("Source", window.model.frame().columns)
        finally:
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_standalone_ref_and_raw_tabs_build_row_aligned_source_plots(self):
        reference = pd.DataFrame({
            "Wafer ID": ["wrong"] * 3,
            "PAD Name": ["wrong"] * 3,
            "Die Seq": [90, 91, 92],
            "DP": [1.0, 2.0, 3.0],
            "EW": [2.0, 4.0, 6.0],
        })
        raw = pd.DataFrame({
            "Wafer ID": ["W1"] * 3,
            "PAD Name": ["P1", "P2", "P3"],
            "Die Seq": [1, 2, 3],
            "DP": [1.1, 2.1, 3.1],
            "EW": [2.2, 4.2, 6.2],
            "Raw only": [7, 8, 9],
        })
        window = CorrelationWindow()
        try:
            window.set_reference_table(reference, "reference.csv")
            window.set_table(raw, "raw.csv")
            self.assertIn("Raw only", window.raw_model.frame().columns)
            aligned = window.reference_model.frame()
            self.assertEqual(aligned["Wafer ID"].tolist(), ["W1"] * 3)
            self.assertEqual(aligned["PAD Name"].tolist(), ["P1", "P2", "P3"])
            self.assertEqual(aligned["Die Seq"].astype(str).tolist(), ["1", "2", "3"])
            self.assertEqual([source["name"] for source in window.selection["sources"]],
                             ["Reference", "Raw Data"])
            window.tabs.setCurrentIndex(2)
            window.correlation_page.selector.selectAll()
            window.correlation_page.draw_plot()
            self.assertEqual(len(window.correlation_page.plot_widgets), 4)
        finally:
            window.raw_model.undo.setClean()
            window.reference_model.undo.setClean()
            window.close()

    def test_toolbars_fit_the_smallest_window(self):
        """No toolbar control may be overlapped or clipped at the 1180 x 760 minimum."""
        window = CorrelationWindow()
        try:
            window.show()
            window.resize(1180, 760)
            for index in (2, 3):
                window.tabs.setCurrentIndex(index)
                APP.processEvents()
                page = window.tabs.widget(index)
                rows = self.toolbar_rows(page)
                self.assertTrue(rows, page.objectName())
                for row in rows:
                    widgets = [row.itemAt(position).widget() for position in range(row.count())]
                    widgets = [widget for widget in widgets if widget is not None]
                    self.assertLessEqual(row.minimumSize().width(), page.width(),
                                         f"{page.objectName()} toolbar needs "
                                         f"{row.minimumSize().width()} px")
                    spans = [(widget.geometry().x(),
                              widget.geometry().x() + widget.geometry().width())
                             for widget in widgets]
                    for (_, left_end), (right_start, _) in zip(spans, spans[1:]):
                        self.assertLessEqual(left_end, right_start,
                                             f"{page.objectName()} toolbar overlaps")
                    for widget, (_, end) in zip(widgets, spans):
                        self.assertLessEqual(end, page.width(),
                                             f"{page.objectName()} toolbar is clipped")
                        fixed = widget.minimumWidth() == widget.maximumWidth()
                        floor = widget.minimumWidth() if fixed else max(
                            widget.minimumWidth(), widget.minimumSizeHint().width())
                        self.assertGreaterEqual(widget.geometry().width(), floor,
                                                f"{page.objectName()} squeezed a control")
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_plot_guidance_uses_control_tooltips_not_inline_hint_rows(self):
        window = CorrelationWindow()
        try:
            expectations = (
                (window.correlation_page, "Drag to select fits"),
                (window.sequence_page, "Drag to select curves"),
            )
            for page, selection_help in expectations:
                self.assertIn(selection_help, page.select_button.toolTip())
                self.assertIn("Ctrl+scroll to zoom", page.reset_button.toolTip())
                self.assertIn("Ordinary scrolling moves the page", page.reset_button.toolTip())
                labels = [label.text() for label in page.findChildren(QLabel)]
                self.assertFalse(any(
                    text.startswith(selection_help) or text.startswith("Ctrl+scroll to zoom")
                    for text in labels
                ))
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_interactive_grids_fit_their_selected_columns(self):
        """Configured plot columns stay fully visible and keep readable light panel chrome."""
        window = CorrelationWindow()
        try:
            window.show()
            window.resize(1180, 760)
            x = np.linspace(-2, 2, 80)
            frame = pd.DataFrame({"Wafer ID": ["W1"] * len(x),
                                  "Die Seq": np.arange(len(x))})
            for index in range(6):
                frame[f"Measurement {index + 1}"] = (index + 1) * x + index
            window.set_table(frame, "Clipboard")
            window.update_plan()

            window.tabs.setCurrentIndex(2)
            page = window.correlation_page
            page.min_rsq.setValue(0.0)
            page.draw_plot()
            APP.processEvents()
            self.assertEqual(page.columns.currentText(), "3")
            self.assertEqual(page.interactive_scroll.horizontalScrollBar().maximum(), 0)
            for host in page.panel_hosts:
                background = host.palette().color(QPalette.ColorRole.Window)
                self.assertGreater(background.lightness(), 200)

            window.tabs.setCurrentIndex(3)
            page = window.sequence_page
            page.columns.setCurrentText("2")
            page.draw_plot()
            APP.processEvents()
            self.assertEqual(page.interactive_scroll.horizontalScrollBar().maximum(), 0)
            for host in page.panel_hosts:
                background = host.palette().color(QPalette.ColorRole.Window)
                self.assertGreater(background.lightness(), 200)
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_interactive_grid_zooms_one_plot_and_resets(self):
        """Page scrolling wins unless Ctrl explicitly requests plot zoom."""
        window = CorrelationWindow()
        try:
            window.resize(760, 520)
            window.show()
            window.set_table(self.linear_frame(), "Clipboard")
            window.update_plan()
            window.tabs.setCurrentIndex(2)
            page = window.correlation_page
            page.draw_plot()
            APP.processEvents()
            self.assertTrue(page.ready, page.status.text())
            self.assertEqual(len(page.plot_widgets), 3)
            self.assertEqual(len(page.home_views), 3)
            page.plot_host.setMinimumHeight(900)
            APP.processEvents()

            first, second = page.plot_widgets[0], page.plot_widgets[1]
            view = first.getPlotItem().getViewBox()
            drawn = view.viewRange()
            other = second.getPlotItem().getViewBox().viewRange()
            scroll_bar = page.interactive_scroll.verticalScrollBar()
            self.assertGreater(scroll_bar.maximum(), 0)
            scroll_bar.setValue(0)
            center = first.rect().center()
            QTest.mouseMove(first.viewport(), center)
            APP.processEvents()
            page_wheel = QWheelEvent(
                QPointF(center), QPointF(first.mapToGlobal(center)),
                QPoint(0, 0), QPoint(0, -120), Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase, False,
            )
            APP.sendEvent(first.viewport(), page_wheel)
            APP.processEvents()
            self.assertEqual(view.viewRange(), drawn)
            self.assertGreater(scroll_bar.value(), 0)

            scroll = scroll_bar.value()
            zoom_wheel = QWheelEvent(
                QPointF(center), QPointF(first.mapToGlobal(center)),
                QPoint(0, 0), QPoint(0, 120), Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.ControlModifier,
                Qt.ScrollPhase.NoScrollPhase, False,
            )
            APP.sendEvent(first.viewport(), zoom_wheel)
            APP.processEvents()
            self.assertTrue(zoom_wheel.isAccepted())
            self.assertNotEqual(view.viewRange(), drawn)
            self.assertEqual(second.getPlotItem().getViewBox().viewRange(), other)
            self.assertEqual(scroll_bar.value(), scroll)

            page.reset_views()
            APP.processEvents()
            self.assertEqual(view.viewRange(), drawn)
            self.assertEqual(second.getPlotItem().getViewBox().viewRange(), other)

            page.columns.setCurrentText("2")
            QTest.qWait(220)
            APP.processEvents()
            self.assertEqual(len(page.plot_widgets), 3)
            self.assertEqual(len(page.home_views), 3)
            # Two columns: the panels regroup into two draggable rows.
            grid = page.plot_host
            self.assertEqual([splitter.count() for splitter in grid.row_splitters], [2, 1])
            self.assertIs(grid.row_splitters[1].widget(0), page.panel_hosts[2])
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_box_selection_narrows_the_fits(self):
        """Boxes choose which columns and measurement sets a fit is built from."""
        window = CorrelationWindow()
        try:
            x = np.linspace(-2, 2, 12)
            frame = pd.DataFrame({"Wafer ID": ["W1"] * 6 + ["W2"] * 6, "A": x,
                                  "B": 2 * x + 1, "C": 3 * x - 1, "D": -x + 2})
            window.set_table(frame, "Clipboard")
            window.update_plan()
            window.tabs.setCurrentIndex(2)
            page = window.correlation_page
            boxes = page.selector
            self.assertEqual((boxes.rowCount(), boxes.columnCount()), (2, 4))
            self.assertEqual(len(boxes.selected_cells()), 8)  # every box starts selected
            page.min_rsq.setValue(.5)

            # Two columns over both measurement sets.
            boxes.clearSelection()
            for row in (0, 1):
                for column in (0, 1):
                    boxes.item(row, column).setSelected(True)
            page.draw_plot()
            APP.processEvents()
            self.assertTrue(page.ready, page.status.text())
            self.assertEqual(len(page.all_fits), 1)
            self.assertEqual(len(page.all_fits[0].x), 12)
            self.assertIn("4 / 8 selected", page.summary.text())

            # Dropping one measurement set halves the fitted rows.
            boxes.item(1, 0).setSelected(False)
            boxes.item(1, 1).setSelected(False)
            page.draw_plot()
            APP.processEvents()
            self.assertTrue(page.ready, page.status.text())
            self.assertEqual(len(page.all_fits[0].x), 6)

            # One column cannot be paired up.
            boxes.clearSelection()
            boxes.item(0, 0).setSelected(True)
            page.draw_plot()
            self.assertFalse(page.ready)
            self.assertIn("at least 2 numeric columns", page.status.text())

            # Without any box the page asks for a selection instead of drawing.
            boxes.clearSelection()
            page.draw_plot()
            self.assertIn("Select at least one fit box", page.status.text())
            self.assertIs(page.stack.currentWidget(), page.selector_panel)
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_trend_copy_stays_pasteable_for_a_tall_array(self):
        """Copying fifteen curves must not build a 160 megapixel image."""
        window = CorrelationWindow()
        try:
            window.load_path(ROOT / "sample_data" / "OCD_measurement_data.csv")
            window.check_all(window.parameter_list, True)
            window.check_all(window.wafer_list, True)
            window.update_plan()
            window.tabs.setCurrentIndex(3)
            page = window.sequence_page
            page.selector.selectAll()
            page.draw_plot()
            APP.processEvents()
            self.assertTrue(page.ready, page.status.text())
            self.assertGreaterEqual(len(page.metrics), 10)

            # Copy uses the existing PyQtGraph grid and must not build the
            # expensive Matplotlib export mirror.
            self.assertFalse(page.figure.axes)
            page.copy_png()
            copied = APP.clipboard().image()
            self.assertFalse(copied.isNull())
            self.assertLessEqual(copied.width() * copied.height(),
                                 MAX_COPY_PIXELS * 1.02)
            self.assertIn("capped", page.status.text())
            cached = page._copy_image
            page.copy_png()
            self.assertIs(page._copy_image, cached)
            self.assertFalse(page.figure.axes)
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_trend_box_selection_limits_the_curve(self):
        """Boxes choose which parameters and measurement sets a curve is drawn from."""
        window = CorrelationWindow()
        try:
            window.load_path(ROOT / "sample_data" / "OCD_measurement_data.csv")
            self.select_parameters(window, {"OCD_H1", "OCD_H2"})
            window.check_all(window.wafer_list, True)
            window.update_plan()
            window.tabs.setCurrentIndex(3)
            page = window.sequence_page
            boxes = page.selector
            self.assertEqual((boxes.rowCount(), boxes.columnCount()), (6, 2))
            self.assertEqual(len(boxes.selected_cells()), 12)

            boxes.clearSelection()
            for row in (0, 1, 2):  # first three measurement sets, first parameter only
                boxes.item(row, 0).setSelected(True)
            page.draw_plot()
            APP.processEvents()
            self.assertTrue(page.ready, page.status.text())
            self.assertEqual(len(page.plot_widgets), 1)
            x, _values = page.plot_widgets[0].getPlotItem().listDataItems()[0].getData()
            self.assertEqual(len(x), 240)
            self.assertEqual((x[0], x[-1]), (0.0, 239.0))
            self.assertIn("1 of 2 parameters", page.status.text())

            page.show_selector()
            self.assertIs(page.stack.currentWidget(), page.selector_panel)
            boxes.clearSelection()
            page.draw_plot()
            self.assertIn("Select at least one curve box", page.status.text())
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_correlation_copy_uses_the_interactive_grid_and_cache(self):
        window = CorrelationWindow()
        try:
            window.set_table(self.linear_frame(24), "Copy fixture")
            page = window.correlation_page
            page.min_rsq.setValue(0)
            page.draw_plot()
            APP.processEvents()
            self.assertTrue(page.ready, page.status.text())
            self.assertFalse(page.figure.axes)
            page.copy_png()
            self.assertFalse(APP.clipboard().image().isNull())
            cached = page._copy_image
            page.copy_png()
            self.assertIs(page._copy_image, cached)
            self.assertFalse(page.figure.axes)
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_panel_heading_owns_its_space_above_the_plot(self):
        """The two-line heading must not print over the plotting area."""
        window = CorrelationWindow()
        try:
            window.show()
            window.resize(1520, 950)
            x = np.linspace(-2, 2, 12)
            frame = pd.DataFrame({"Wafer ID": ["W1"] * 12, "A": x, "B": 2 * x + 1,
                                  "C": 3 * x - 1, "D": -x + 2})
            window.set_table(frame, "Clipboard")
            window.update_plan()
            window.tabs.setCurrentIndex(2)
            page = window.correlation_page
            page.min_rsq.setValue(.5)
            page.draw_plot()
            APP.processEvents()
            self.assertTrue(page.plot_widgets)
            for host, widget in zip(page.panel_hosts, page.plot_widgets):
                heading = host.layout().itemAt(0).widget()
                self.assertIn("vs", heading.text())
                self.assertGreaterEqual(heading.geometry().bottom(),
                                        heading.sizeHint().height() - 2)
                # The heading sits completely above the plot widget.
                self.assertLessEqual(heading.geometry().bottom(), widget.geometry().top())
                self.assertGreaterEqual(widget.geometry().height(),
                                        widget.minimumHeight())
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_panel_borders_are_draggable_and_drag_zooms(self):
        """Dragging a panel boundary resizes it; dragging inside a plot box-zooms."""
        window = CorrelationWindow()
        try:
            window.show()
            window.resize(1520, 950)
            x = np.linspace(-2, 2, 12)
            frame = pd.DataFrame({"Wafer ID": ["W1"] * 12, "A": x, "B": 2 * x + 1,
                                  "C": 3 * x - 1, "D": -x + 2})
            window.set_table(frame, "Clipboard")
            window.update_plan()
            window.tabs.setCurrentIndex(2)
            page = window.correlation_page
            page.min_rsq.setValue(.5)
            page.draw_plot()
            APP.processEvents()
            self.assertEqual(len(page.plot_widgets), 6)

            grid = page.plot_host
            # Panels may be pushed completely out of view and dragged back.
            self.assertTrue(grid.childrenCollapsible())
            self.assertEqual([splitter.count() for splitter in grid.row_splitters], [3, 3])

            # Dragging one boundary resizes the panels and keeps rows aligned.
            first, second = page.plot_widgets[0], page.plot_widgets[1]
            row = grid.row_splitters[0]
            row.moveSplitter(600, 1)
            APP.processEvents()
            self.assertNotEqual(row.sizes()[0], row.sizes()[1])
            self.assertEqual(grid.row_splitters[1].sizes(), row.sizes())
            self.assertGreater(first.width(), second.width())

            # Dragging the boundary onto its neighbour hides that panel, and the
            # same boundary brings it back.
            row.moveSplitter(0, 1)
            APP.processEvents()
            self.assertEqual(row.sizes()[0], 0)
            # The panel host collapses to nothing, so the plot is clipped away.
            self.assertEqual(page.panel_hosts[0].width(), 0)
            row.setSizes([460, 460, 460])
            APP.processEvents()
            self.assertGreater(page.panel_hosts[0].width(), 0)

            # A double click on the boundary restores the default layout.
            handle = row.handle(1)
            QTest.mouseDClick(handle, Qt.MouseButton.LeftButton, pos=handle.rect().center())
            APP.processEvents()
            self.assertEqual(len(set(row.sizes())), 1)
            self.assertEqual(grid.row_splitters[1].sizes(), row.sizes())

            # Left drag selects a region and zooms into it.
            view = first.getPlotItem().getViewBox()
            self.assertEqual(view.state["mouseMode"], pg.ViewBox.RectMode)
            before = view.viewRange()
            rect = first.rect()
            start = QPoint(int(rect.width() * .3), int(rect.height() * .3))
            end = QPoint(int(rect.width() * .7), int(rect.height() * .7))
            QTest.mousePress(first.viewport(), Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(first.viewport(), end, delay=20)
            QTest.mouseRelease(first.viewport(), Qt.MouseButton.LeftButton, pos=end)
            APP.processEvents()
            zoomed = view.viewRange()
            self.assertLess(zoomed[0][1] - zoomed[0][0], .9 * (before[0][1] - before[0][0]))
            page.reset_views()
            APP.processEvents()
            self.assertEqual(view.viewRange(), before)
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_die_seq_plot_uses_real_missing_sequence_numbers(self):
        """The curve is continuous; wafers are appended and labelled below the axis."""
        window = CorrelationWindow()
        try:
            window.load_path(ROOT / "sample_data" / "OCD_measurement_data.csv")
            self.select_parameters(window, {"OCD_H1", "OCD_H2"})
            window.tabs.setCurrentIndex(3)
            page = window.sequence_page
            page.draw_plot()
            page.ensure_export_figure()   # the export mirror is built on demand
            APP.processEvents()
            self.assertTrue(page.ready, page.status.text())
            self.assertEqual(len(page.plot_widgets), 2)
            self.assertEqual([wafer for _center, wafer in page.wafer_ticks],
                             ["AIT0137.00-19", "AIT0137.00-19", "AIT0161.00-10",
                              "AIT0161.00-10", "AIT0161.00-11", "AIT0161.00-11"])
            self.assertEqual([center for center, _wafer in page.wafer_ticks],
                             [39.5, 119.5, 199.5, 279.5, 359.5, 439.5])

            first = page.plot_widgets[0]
            x, values = first.getPlotItem().listDataItems()[0].getData()
            self.assertEqual(len(x), 480)
            self.assertEqual(len(values), 480)
            np.testing.assert_allclose(np.diff(x), 1.0)  # one line, no gap between sets
            boundaries = [float(item.value()) for item in first.getPlotItem().items
                          if isinstance(item, pg.InfiniteLine)]
            self.assertEqual(boundaries, [79.5, 159.5, 239.5, 319.5, 399.5])

            view = first.getPlotItem().getViewBox()
            drawn = view.viewRange()
            other = page.plot_widgets[1].getPlotItem().getViewBox().viewRange()
            center = first.rect().center()
            QTest.mouseMove(first.viewport(), center)
            APP.processEvents()
            wheel = QWheelEvent(QPointF(center), QPointF(first.mapToGlobal(center)),
                                QPoint(0, 0), QPoint(0, 120), Qt.MouseButton.NoButton,
                                Qt.KeyboardModifier.ControlModifier,
                                Qt.ScrollPhase.NoScrollPhase, False)
            APP.sendEvent(first.viewport(), wheel)
            APP.processEvents()
            self.assertNotEqual(view.viewRange(), drawn)
            self.assertEqual(page.plot_widgets[1].getPlotItem().getViewBox().viewRange(), other)
            page.reset_views()
            APP.processEvents()
            self.assertEqual(view.viewRange(), drawn)
            page.copy_png()
            self.assertFalse(APP.clipboard().image().isNull())
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_trend_auto_range_keeps_tight_x_extent_and_visible_right_frame(self):
        """Auto Range must not restore side gaps or collapse the right plot border."""
        window = CorrelationWindow()
        try:
            window.show()
            window.resize(1180, 760)
            window.load_path(ROOT / "sample_data" / "OCD_measurement_data.csv")
            self.select_parameters(window, {"OCD_H1"})
            window.tabs.setCurrentIndex(3)
            page = window.sequence_page
            page.draw_plot()
            APP.processEvents()

            plot = page.plot_widgets[0].getPlotItem()
            view = plot.getViewBox()
            _positions, values = plot.listDataItems()[0].getData()
            midpoint = float(np.nanmean(values))
            view.setYRange(midpoint - .1, midpoint + .1, padding=0)
            plot.autoBtnClicked()
            APP.processEvents()

            x_range = view.viewRange()[0]
            self.assertAlmostEqual(x_range[0], page.x_range[0])
            self.assertAlmostEqual(x_range[1], page.x_range[1])
            y_range = view.viewRange()[1]
            self.assertLessEqual(y_range[0], float(np.nanmin(values)))
            self.assertGreaterEqual(y_range[1], float(np.nanmax(values)))
            right_axis = plot.getAxis("right")
            self.assertTrue(right_axis.isVisible())
            self.assertGreater(right_axis.geometry().width(), 0)
            self.assertGreater(view.border.widthF(), 0)
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_missing_die_sequence_numbers_stay_real(self):
        frame = pd.DataFrame({
            "Wafer ID": ["W1", "W1", "W1", "W2", "W2"],
            "Die Seq": [1, 4, 9, 2, 8],
            "FIELD X": [0, 1, 2, 0, 1], "FIELD Y": [0, 0, 0, 1, 1],
            "Value A": [10, 11, 12, 20, 21], "Value B": [3, 5, 4, 8, 9],
        })
        window = CorrelationWindow()
        try:
            window.set_table(frame, "Missing Die Seq fixture")
            page = window.sequence_page
            page.draw_plot()
            page.ensure_export_figure()   # the export mirror is built on demand
            self.assertTrue(page.ready, page.status.text())
            self.assertEqual(page.figure.axes[0]._die_sequence_values, [[1, 4, 9], [2, 8]])
            self.assertEqual(page.figure.axes[0]._wafer_ids, ["W1", "W2"])
            visible_ticks = {text.get_text() for text in page.figure.axes[0].get_xticklabels()}
            self.assertTrue({"1", "4", "9", "2", "8"}.issubset(visible_ticks))
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_first_cell_paste_auto_selects_numeric_columns(self):
        window = CorrelationWindow()
        try:
            window.sheet.setCurrentIndex(window.model.index(0, 0))
            APP.clipboard().setText(
                "Wafer ID\tX(mm)\tY(mm)\tMSE\tGOF\tNGOF\tLBH\tregIter\tCINDEX\tValue A\tValue B\n"
                "W1\t0\t0\t1\t1\t0.9\t0\t10\t1\t10\t30\n"
                "W2\t1\t1\t2\t1\t0.9\t0\t11\t1\t20\t40"
            )
            window.sheet.paste()
            window.recognize()
            self.assertEqual(set(window.selection["metrics"]), {"Value A", "Value B"})
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_module_specific_defaults_for_new_table(self):
        frame = pd.DataFrame({
            "Wafer ID": ["W1", "W2"], "X(mm)": [0, 1], "Y(mm)": [0, 1],
            "MSE": [1, 2], "GOF": [1, 1], "CINDEX": [4, 5],
            "Value A": [10, 20], "Value B": [30, 40],
        })
        wafer, correlation = WaferMapWindow(), CorrelationWindow()
        try:
            wafer.set_table(frame, "Clipboard")
            correlation.set_table(frame, "Clipboard")
            self.assertEqual(len(wafer.selection["wafers"]), 2)
            self.assertEqual(len(correlation.selection["wafers"]), 2)
            self.assertEqual(wafer.selection["metrics"], [])
            self.assertEqual(set(correlation.selection["metrics"]), {"Value A", "Value B"})
        finally:
            for window in (wafer, correlation):
                window.model.undo.setClean()
                window.close()
                window.deleteLater()
            APP.processEvents()

    def test_lmfit_pair_and_rsq_sorting(self):
        x = np.linspace(-5, 5, 31)
        frame = pd.DataFrame({"A": x, "B": 2 * x + 1, "C": x ** 2})
        fit = fit_numeric_pair(frame, "A", "B")
        self.assertAlmostEqual(fit.slope, 2)
        self.assertAlmostEqual(fit.intercept, 1)
        self.assertAlmostEqual(fit.rsquared, 1)
        fits, errors = pairwise_linear_fits(frame, ["A", "B", "C"])
        self.assertFalse(errors)
        self.assertEqual((fits[0].x_name, fits[0].y_name), ("A", "B"))
        self.assertEqual([fit.rsquared for fit in fits],
                         sorted((fit.rsquared for fit in fits), reverse=True))

    def test_invalid_pairs_are_skipped(self):
        frame = pd.DataFrame({"A": [1, 2, 3], "B": [4, 4, 4], "C": [1, None, None]})
        fits, errors = pairwise_linear_fits(frame, ["A", "B", "C"])
        self.assertEqual(fits, [])
        self.assertEqual(len(errors), 3)

    def test_more_than_sixteen_selected_columns_can_be_drawn(self):
        x = np.linspace(-2, 2, 12)
        frame = pd.DataFrame({"Wafer ID": ["W1"] * len(x), "A": x, "B": 3 * x + 2})
        for index in range(15):
            frame[f"Constant {index}"] = index
        window = CorrelationWindow()
        try:
            window.set_table(frame, "Clipboard")
            self.assertEqual(len(window.selection["metrics"]), 17)
            window.tabs.setCurrentIndex(2)
            page = window.correlation_page
            page.draw_plot()
            page.ensure_export_figure()   # the export mirror is built on demand
            self.assertTrue(page.ready, page.status.text())
            self.assertEqual(len(page.all_fits), 1)
            self.assertEqual(len(page.figure.axes), 1)
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_window_reuses_data_tab_and_draws_ranked_array(self):
        window = CorrelationWindow()
        try:
            window.load_path(ROOT / "sample_data" / "OCD_measurement_data.csv")
            self.assertEqual(window.tabs.count(), 4)
            self.assertEqual(window.tabs.tabText(0), "1. Ref Data")
            self.assertEqual(window.tabs.tabText(1), "2. Raw Data")
            self.assertEqual(window.tabs.tabText(2), "3. Correlation")
            self.assertEqual(window.tabs.tabText(3), "4. Trend")
            self.assertGreater(window.sheet.model().rowCount(), 0)
            self.assertEqual(len(window.selection["metrics"]), 15)
            tree = window.parameter_list
            tree.blockSignals(True)
            for index in range(tree.topLevelItemCount()):
                item = tree.topLevelItem(index)
                if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                    item.setCheckState(0, Qt.CheckState.Checked if item.text(0) in
                                       {"OCD_H1", "OCD_H2", "OCD_H3"} else Qt.CheckState.Unchecked)
            tree.blockSignals(False)
            window.update_plan()
            window.tabs.setCurrentIndex(2)
            page = window.correlation_page
            page.draw_plot()
            page.ensure_export_figure()   # the export mirror is built on demand
            self.assertTrue(page.ready, page.status.text())
            self.assertEqual(page.copy_shortcut.key(), QKeySequence(QKeySequence.StandardKey.Copy))
            self.assertEqual(page.min_rsq.value(), .5)
            self.assertEqual(len(page.all_fits), 3)
            self.assertEqual(len(page.fits), 1)
            scores = [fit.rsquared for fit in page.fits]
            self.assertEqual(scores, sorted(scores, reverse=True))
            self.assertTrue(all(score > .5 for score in scores))
            self.assertEqual(len(page.figure.axes), 1)
            self.assertIn("vs", page.figure.axes[0].get_title(loc="center"))
            self.assertIn("R² > 0.50", page.status.text())
            self.assertEqual(page.resolution.currentText(), get_settings()["resolution"])
            page.min_rsq.setValue(.1)
            QTest.qWait(220)
            self.assertEqual(len(page.fits), 2)
            page.min_rsq.setValue(.95)
            QTest.qWait(220)
            self.assertFalse(page.ready)
            self.assertEqual(page.fits, [])
            self.assertEqual(len(page.all_fits), 3)
            self.assertGreaterEqual(page.figure.texts[0].get_fontsize(), 15)
            page.min_rsq.setValue(.5)
            QTest.qWait(220)
            self.assertTrue(page.ready)
            self.assertEqual(len(page.fits), 1)
            page.copy_png()
            self.assertFalse(APP.clipboard().image().isNull())

            window.tabs.setCurrentIndex(3)
            sequence = window.sequence_page
            sequence.draw_plot()
            sequence.ensure_export_figure()   # the export mirror is built on demand
            self.assertTrue(sequence.ready, sequence.status.text())
            self.assertEqual(sequence.wafer_column, "Wafer ID")
            self.assertEqual(sequence.die_column, "Die Seq")
            self.assertEqual(len(sequence.figure.axes), 3)
            self.assertEqual({axis.get_title() for axis in sequence.figure.axes},
                             {"OCD_H1", "OCD_H2", "OCD_H3"})
            self.assertTrue(all(axis._die_sequence_values for axis in sequence.figure.axes))
            self.assertTrue(all(axis._wafer_ids for axis in sequence.figure.axes))
            self.assertTrue(all(axis.get_xlabel() == "Die Seq" for axis in sequence.figure.axes))
            self.assertEqual(sequence.copy_shortcut.key(), QKeySequence(QKeySequence.StandardKey.Copy))
        finally:
            window.model.undo.setClean()
            window.close()
            window.deleteLater()
            APP.processEvents()

    def _overlay_page(self, metrics=("DP [nm]", "EW [V]")):
        frame = pd.DataFrame({
            "Wafer ID": ["W1"] * 4 + ["W2"] * 4,
            "Die Seq": [1, 2, 3, 4] * 2,
            "DP [nm]": [1.0, 2.0, np.nan, 4.0, 5.0, 6.0, 7.0, 8.0],
            "EW [V]": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0],
            "TG [nm]": [2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0],
        })
        window = CorrelationWindow()
        window.set_table(frame, "Overlay fixture")
        self.select_parameters(window, set(metrics))
        window.tabs.setCurrentIndex(3)
        page = window.sequence_page
        page.overlay = {}
        page.selector.selectAll()
        page.draw_plot()
        APP.processEvents()
        return window, page

    def test_trend_context_menu_offers_overlay_for_checked_parameters(self):
        window, page = self._overlay_page()
        try:
            menu = page.build_panel_menu(page.plot_widgets[0], "DP [nm]")
            actions = {action.text(): action for action in menu.actions()}
            self.assertIn("叠加对比…", actions)
            self.assertTrue(actions["叠加对比…"].isEnabled())
            self.assertIn("解除对比", actions)
            self.assertFalse(actions["解除对比"].isEnabled())
        finally:
            window.model.undo.setClean()
            window.close()

    def test_overlay_merges_two_panels_into_one_widget_with_two_axes(self):
        window, page = self._overlay_page()
        try:
            self.assertTrue(page.set_overlay("DP [nm]", "EW [V]"))
            self.assertEqual(len(page.plot_widgets), 1)
            self.assertEqual(len(page.plot_widgets[0].secondary_views), 1)
            heading = page.panel_hosts[0].findChild(QLabel)
            self.assertIn("DP [nm] + EW [V]", heading.text())
        finally:
            window.model.undo.setClean()
            window.close()

    def test_overlay_uses_the_same_measurement_sets_for_both_parameters(self):
        window, page = self._overlay_page()
        try:
            page.set_overlay("DP [nm]", "EW [V]")
            widget = page.plot_widgets[0]
            primary_x = widget.getPlotItem().listDataItems()[0].getData()[0]
            secondary_x = widget.secondary_views[0].addedItems[0].getData()[0]
            np.testing.assert_array_equal(primary_x, secondary_x)
        finally:
            window.model.undo.setClean()
            window.close()

    def test_unlink_overlay_restores_one_panel_per_parameter(self):
        window, page = self._overlay_page()
        try:
            page.set_overlay("DP [nm]", "EW [V]")
            page.unlink_overlay("DP [nm]")
            self.assertEqual(len(page.plot_widgets), 2)
            self.assertFalse(page.overlay)
        finally:
            window.model.undo.setClean()
            window.close()

    def test_third_parameter_overlay_is_rejected(self):
        window, page = self._overlay_page(("DP [nm]", "EW [V]", "TG [nm]"))
        try:
            self.assertTrue(page.set_overlay("DP [nm]", "EW [V]"))
            self.assertFalse(page.set_overlay("DP [nm]", "TG [nm]"))
            self.assertIn("仅支持两个参数", page.status.text())
        finally:
            window.model.undo.setClean()
            window.close()

    def test_separate_panel_mode_still_renders_one_widget_per_parameter(self):
        window, page = self._overlay_page()
        try:
            self.assertEqual(len(page.plot_widgets), 2)
            self.assertFalse(page.overlay)
        finally:
            window.model.undo.setClean()
            window.close()

    def test_export_figure_mirrors_the_overlay_and_keeps_wafer_labels(self):
        window, page = self._overlay_page()
        try:
            page.set_overlay("DP [nm]", "EW [V]")
            page.ensure_export_figure()
            self.assertEqual(len(page.figure.axes), 2)
            for axis in page.figure.axes:
                self.assertTrue(axis._die_sequence_values)
                self.assertTrue(axis._wafer_ids)
                self.assertTrue(hasattr(axis, "_wafer_group_labels"))
        finally:
            window.model.undo.setClean()
            window.close()


if __name__ == "__main__":
    unittest.main()
