"""Pairwise lmfit analysis and loadable correlation workspace tests."""

import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QKeySequence, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QHBoxLayout

from wafermap.correlation_page import fit_numeric_pair, pairwise_linear_fits
from wafermap.correlation_window import CorrelationWindow
from wafermap.appearance import MAX_COPY_PIXELS, configure_fonts
from wafermap.settings import get_settings
from wafermap.window import MainWindow as WaferMapWindow


ROOT = Path(__file__).resolve().parents[1]
APP = QApplication.instance() or QApplication([])
configure_fonts(APP)  # same font registration the launcher installs


class CorrelationTests(unittest.TestCase):
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

    def test_toolbars_fit_the_smallest_window(self):
        """No toolbar control may be overlapped or clipped at the 1180 x 760 minimum."""
        window = CorrelationWindow()
        try:
            window.show()
            window.resize(1180, 760)
            for index in (1, 2):
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

    def test_interactive_grid_zooms_one_plot_and_resets(self):
        """Each pairwise plot zooms on its own; Reset views restores the drawn range."""
        window = CorrelationWindow()
        try:
            window.set_table(self.linear_frame(), "Clipboard")
            window.update_plan()
            window.tabs.setCurrentIndex(1)
            page = window.correlation_page
            page.draw_plot()
            APP.processEvents()
            self.assertTrue(page.ready, page.status.text())
            self.assertEqual(len(page.plot_widgets), 3)
            self.assertEqual(len(page.home_views), 3)

            first, second = page.plot_widgets[0], page.plot_widgets[1]
            view = first.getPlotItem().getViewBox()
            drawn = view.viewRange()
            other = second.getPlotItem().getViewBox().viewRange()
            scroll = page.interactive_scroll.verticalScrollBar().value()
            center = first.rect().center()
            QTest.mouseMove(first.viewport(), center)
            APP.processEvents()
            wheel = QWheelEvent(QPointF(center), QPointF(first.mapToGlobal(center)),
                                QPoint(0, 0), QPoint(0, 120), Qt.MouseButton.NoButton,
                                Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
            APP.sendEvent(first.viewport(), wheel)
            APP.processEvents()
            self.assertTrue(wheel.isAccepted())
            self.assertNotEqual(view.viewRange(), drawn)
            self.assertEqual(second.getPlotItem().getViewBox().viewRange(), other)
            self.assertEqual(page.interactive_scroll.verticalScrollBar().value(), scroll)

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
            window.tabs.setCurrentIndex(1)
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
            window.load_path(ROOT / "OCD_measurement_data.csv")
            window.check_all(window.parameter_list, True)
            window.check_all(window.wafer_list, True)
            window.update_plan()
            window.tabs.setCurrentIndex(2)
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
            window.load_path(ROOT / "OCD_measurement_data.csv")
            self.select_parameters(window, {"OCD_H1", "OCD_H2"})
            window.check_all(window.wafer_list, True)
            window.update_plan()
            window.tabs.setCurrentIndex(2)
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
            window.tabs.setCurrentIndex(1)
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
            window.tabs.setCurrentIndex(1)
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
            window.load_path(ROOT / "OCD_measurement_data.csv")
            self.select_parameters(window, {"OCD_H1", "OCD_H2"})
            window.tabs.setCurrentIndex(2)
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
                                Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
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
            window.tabs.setCurrentIndex(1)
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
            window.load_path(ROOT / "OCD_measurement_data.csv")
            self.assertEqual(window.tabs.count(), 3)
            self.assertEqual(window.tabs.tabText(0), "1. Data")
            self.assertEqual(window.tabs.tabText(1), "2. Correlation")
            self.assertEqual(window.tabs.tabText(2), "3. Trend")
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
            window.tabs.setCurrentIndex(1)
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

            window.tabs.setCurrentIndex(2)
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


if __name__ == "__main__":
    unittest.main()
