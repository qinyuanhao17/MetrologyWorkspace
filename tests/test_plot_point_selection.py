"""Qt gestures preserve the separation between a plot mask and Data selection."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pandas as pd
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from metrology_app.appearance import SELECTION_HIGHLIGHT_COLOR
from metrology_app.plotting.interactive import InteractivePlotWidget
from metrology_app.plotting.selection import DataPointEdits
from metrology_app.window import MainWindow


APP = QApplication.instance() or QApplication([])


class PlotPointSelectionTests(unittest.TestCase):
    def setUp(self):
        self.plot = InteractivePlotWidget()
        self.addCleanup(self.plot.deleteLater)
        self.addCleanup(self.plot.close)
        self.plot.resize(550, 350)
        self.curve = self.plot.plot([1, 2, 3, 4], [2, 4, 6, 8], symbol="o")
        self.plot.set_point_rows(self.curve.scatter, np.arange(4))
        self.plot.setRange(xRange=(0, 5), yRange=(0, 10), padding=0)
        self.plot.show()
        APP.processEvents()

    def drag(self, a, b, modifiers=Qt.KeyboardModifier.NoModifier):
        view = self.plot.getViewBox()
        start, end = (self.plot.mapFromScene(view.mapViewToScene(QPointF(*xy))) for xy in (a, b))
        QTest.mousePress(self.plot.viewport(), Qt.MouseButton.LeftButton, modifiers, pos=start)
        QTest.mouseMove(self.plot.viewport(), end, delay=15)
        QTest.mouseRelease(self.plot.viewport(), Qt.MouseButton.LeftButton, modifiers, pos=end)
        APP.processEvents()

    def actions(self):
        menu = self.plot.getViewBox().getMenu(None)
        menu.aboutToShow.emit()
        return {action.text(): action for action in menu.actions()}

    def test_box_selection_keeps_remove_direct_uncheck_and_applied_uncheck_independent(self):
        excluded = {0}
        records = ["A", "B", "C", "D"]

        def set_checked(rows, checked):
            changed = rows & excluded if checked else rows - excluded
            excluded.difference_update(changed) if checked else excluded.update(changed)
            return changed

        self.plot.point_selection.data = DataPointEdits(set_checked, records=lambda: records)
        self.plot.point_selection.scope = "test-plot"
        initial = self.plot.getViewBox().viewRange()
        self.drag((2.5, 5), (3.5, 7))
        self.actions()["Uncheck Selection"].trigger()
        self.assertEqual(excluded, {0, 2})
        self.drag((.5, 1), (3.5, 7))
        self.assertEqual(self.plot.point_selection.data_keys(self.plot.point_selection.selected), {0, 1, 2})
        self.assertEqual(self.plot.getViewBox().viewRange(), initial)
        actions = self.actions()
        self.assertNotIn("Double-click", actions)
        self.assertIn("View All", actions)
        actions["Remove Selection"].trigger()
        np.testing.assert_equal(self.curve.yData, [8])
        self.assertEqual(len(self.curve.scatter.points()), 1)
        self.assertEqual(self.curve.scatter.points()[0].pos().x(), 4)
        self.assertEqual(excluded, {0, 2})
        self.actions()["Apply Remove to Uncheck"].trigger()
        self.assertEqual(excluded, {0, 1, 2})

        # A data refresh may replace every graphics item. Its local mask has
        # the same scope and source identities, independent of the checkbox.
        self.plot.removeItem(self.curve)
        replacement = self.plot.plot([1, 2, 3, 4], [2, 4, 6, 8], symbol="o")
        self.plot.set_point_rows(replacement.scatter, np.arange(4))
        self.actions()["Restore Applied Unchecks"].trigger()
        self.assertEqual(excluded, {0, 2})
        self.actions()["Restore Unchecked Selection"].trigger()
        self.assertEqual(excluded, {0})
        np.testing.assert_equal(replacement.yData, [8])
        self.assertEqual(len(replacement.scatter.points()), 1)
        self.actions()["Restore Removed Selection"].trigger()
        np.testing.assert_equal(replacement.yData, [2, 4, 6, 8])
        self.assertEqual(len(replacement.scatter.points()), 4)
        self.drag((1.5, 3), (3.5, 7), Qt.KeyboardModifier.ControlModifier)
        self.assertLess(self.plot.getViewBox().viewRange()[0][1] - self.plot.getViewBox().viewRange()[0][0],
                        initial[0][1] - initial[0][0])

    def test_menu_separates_the_three_edit_pairs_and_test_flag(self):
        self.plot.point_selection.data = DataPointEdits(lambda rows, _checked: rows, lambda _rows: None)
        menu = self.plot.getViewBox().getMenu(None)
        menu.aboutToShow.emit()
        texts = [None if action.isSeparator() else action.text() for action in menu.actions()]
        self.assertIn("View All", texts)
        self.assertTrue({"Undo point removal", "Redo point removal", "Restore all removed points"}.isdisjoint(texts))
        self.assertEqual(texts[texts.index("Remove Selection") - 1:], [
            None, "Remove Selection", "Restore Removed Selection",
            None, "Uncheck Selection", "Restore Unchecked Selection",
            None, "Apply Remove to Uncheck", "Restore Applied Unchecks",
            None, "Set Test Flag",
        ])

    def test_test_flag_action_writes_only_selected_source_rows(self):
        window = MainWindow()
        window.document.force_close = True
        self.addCleanup(window.close)
        window.set_table(pd.DataFrame({"Wafer ID": ["W1"] * 4, "Die Seq": [1, 2, 3, 4],
                                       "TestFlag": [0, 12, 0, 0],
                                       "CD": [2, 4, 6, 8]}), "Test rows")
        self.plot.point_selection.data = window._chart_edits
        self.drag((1.5, 3), (3.5, 7))
        flags = self.actions()["Set Test Flag"].menu()
        twelve = next(action for action in flags.actions() if action.text() == "12")
        twelve.trigger()
        self.assertEqual(window.model.document_frame()["TestFlag"].tolist(), ["0", "12", "12", "0"])

    def test_double_click_toggles_remove_and_shift_double_click_toggles_uncheck(self):
        excluded = set()
        records = ["A", "B", "C", "D"]

        def set_checked(rows, checked):
            changed = rows & excluded if checked else rows - excluded
            excluded.difference_update(changed) if checked else excluded.update(changed)
            return changed

        self.plot.point_selection.data = DataPointEdits(set_checked, records=lambda: records)
        self.plot.point_selection.scope = "toggle"
        view = self.plot.getViewBox()
        point = self.plot.mapFromScene(view.mapViewToScene(QPointF(2, 4)))
        self.assertTrue(self.plot.point_selection.double_click(point, Qt.KeyboardModifier.NoModifier))
        np.testing.assert_equal(self.curve.yData, [2, 6, 8])
        self.assertEqual(len(self.curve.scatter.points()), 3)
        self.assertTrue(self.plot.point_selection.double_click(point, Qt.KeyboardModifier.NoModifier))
        self.assertEqual(self.curve.yData[1], 4)
        self.assertEqual(len(self.curve.scatter.points()), 4)

        self.assertTrue(self.plot.point_selection.double_click(point, Qt.KeyboardModifier.ShiftModifier))
        self.assertEqual(excluded, {1})
        self.assertTrue(self.plot.point_selection.double_click(point, Qt.KeyboardModifier.ShiftModifier))
        self.assertEqual(excluded, set())

    def test_chart_selection_marker_uses_the_shared_high_contrast_color(self):
        self.assertEqual(SELECTION_HIGHLIGHT_COLOR.upper(), "#E53935")
        color = self.plot.point_selection.highlight.opts["pen"].color()
        self.assertEqual(color.name().upper(), SELECTION_HIGHLIGHT_COLOR.upper())
        linked = self.plot.point_selection.preview.opts["pen"].color()
        self.assertEqual(linked.name().upper(), "#F2B705")

    def test_matching_preview_points_reads_source_identities_once(self):
        records = Mock(return_value=("A", "B", "C", "D"))
        self.plot.point_selection.data = DataPointEdits(lambda rows, checked: rows, records=records)

        self.assertEqual(self.plot.point_selection.tokens_for_keys({"B", "D"}),
                         {(self.curve, 1), (self.curve, 3)})
        records.assert_called_once_with()

    def test_click_selects_and_links_the_same_parameter_with_an_enlarged_marker(self):
        other = InteractivePlotWidget()
        unrelated = InteractivePlotWidget()
        self.addCleanup(other.deleteLater)
        self.addCleanup(unrelated.deleteLater)
        for plot in (other, unrelated):
            plot.resize(550, 350)
            curve = plot.plot([1, 2, 3, 4], [3, 5, 7, 9], symbol="o")
            plot.set_point_rows(curve.scatter, np.arange(4))
            plot.setRange(xRange=(0, 5), yRange=(0, 10), padding=0)
            plot.show()
        APP.processEvents()
        edits = DataPointEdits(lambda rows, checked: rows, records=lambda: ["A", "B", "C", "D"])
        self.plot.point_selection.set_data(edits, ("Match", "Preview", "L3", "main", "match"))
        other.point_selection.set_data(edits, ("Match", "Preview", "L3", "main", "bias"))
        unrelated.point_selection.set_data(edits, ("Match", "Preview", "L4", "main", "bias"))
        view = self.plot.getViewBox()
        point = self.plot.mapFromScene(view.mapViewToScene(QPointF(2, 4)))
        QTest.mouseClick(self.plot.viewport(), Qt.MouseButton.LeftButton, pos=point)
        APP.processEvents()
        self.assertTrue(self.plot.point_selection.selected)
        self.assertFalse(other.point_selection.selected)
        self.assertFalse(unrelated.point_selection.selected)
        self.assertGreater(len(self.plot.point_selection.highlight.data), 0)
        self.assertGreater(len(other.point_selection.preview.data), 0)
        self.assertEqual(len(unrelated.point_selection.preview.data), 0)
        self.assertTrue(self.actions()["Remove Selection"].isEnabled())
        self.assertEqual(self.plot.point_selection.highlight.opts["size"], 16)

        blank = QPoint(2, 2)
        QTest.mouseClick(self.plot.viewport(), Qt.MouseButton.LeftButton, pos=blank)
        APP.processEvents()
        self.assertFalse(self.plot.point_selection.selected)
        self.assertFalse(other.point_selection.selected)
        self.assertEqual(len(self.plot.point_selection.highlight.data), 0)
        self.assertEqual(len(other.point_selection.preview.data), 0)

    def test_analysis_pages_register_and_preview_the_same_source_point(self):
        from PyQt6.QtTest import QTest
        from metrology_app.correlation_window import CorrelationWindow

        window = CorrelationWindow()
        window.document.force_close = True
        self.addCleanup(window.close)
        raw = pd.DataFrame({
            "Wafer ID": ["W1"] * 8,
            "Die Seq": list(range(1, 9)),
            "CD": range(8),
            "Depth": [value * 2 + 1 for value in range(8)],
        })
        window.set_table(raw, "Raw")
        window.set_reference_table(raw.assign(CD=[2, 4, 6, 8, 10, 12, 14, 16]))
        correlation, trend = window.correlation_page, window.sequence_page
        correlation.min_rsq.setValue(0)
        correlation.selector.selectAll()
        correlation.draw_plot()
        trend.selector.selectAll()
        trend.draw_plot()
        QTest.qWait(500)
        plots = correlation.plot_widgets + trend.plot_widgets
        self.assertTrue(plots)
        self.assertTrue(all(plot.point_selection in window._chart_edits._selections for plot in plots))

        key = window._chart_edits.records()[0]
        window._chart_edits.highlight({key}, None, rows={0})
        self.assertGreater(sum(len(plot.point_selection.preview.data) for plot in plots), 0)

    def open_match_map(self, raw, *, reorder=False):
        from metrology_app.matching import ParameterMapping
        from metrology_app.matching_window import MatchingWindow
        from tests.match_fixtures import configure_match_fixture

        owner = MatchingWindow()
        owner.document.force_close = True
        self.addCleanup(owner.close)
        owner.set_reference_frame(pd.DataFrame({"P1 Ref": np.arange(len(raw)) + 1.}))
        owner.set_raw_frame(raw)
        configure_match_fixture(owner, ParameterMapping("P1", "P1 Ref", "P1"))
        owner.run_analysis()
        child = owner.open_stage_workspace("preview")
        child.document.force_close = True
        child.set_table(raw.iloc[::-1].reset_index(drop=True) if reorder else raw, "Wafer map")
        child._set_checked_values(child.parameter_list, ["P0", "P1"])
        child.update_plan()
        return owner, child

    def test_match_and_map_windows_keep_separate_point_selections(self):
        from tests.test_wafer_static import finish_graphics, map_fixture

        raw, _ = map_fixture(1, 2)
        raw["Seq"] = np.arange(1, len(raw) + 1)
        owner, child = self.open_match_map(raw, reorder=True)
        child.resize(1250, 750)
        page = child.plot_page
        child.tabs.setCurrentWidget(page)
        page.selector.selectAll()
        page.draw_maps()
        finish_graphics(page)
        chart = owner.plot_groups["P1"]["plots"]["match"]
        curve = chart.listDataItems()[0]
        chart.point_selection.selected = {(curve, 0)}
        chart.point_selection._sync_shared_highlight()
        for linked_page in (page, child.radius_page):
            self.assertFalse(linked_page.scroll.chart_preview_rows)
        panel = page.map_grid.panels[0]
        self.paint_map_ring(panel).drawEllipse.assert_not_called()

        row = int(panel.point_rows()[10])
        self.click_map_panel(page, panel, 10)
        self.assertEqual(page.scroll.chart_preview_rows, {row})
        self.assertEqual(owner._chart_edits.preview_rows, {0})
        self.assertEqual(chart.point_selection.selected, {(curve, 0)})

    def test_map_and_radius_link_the_same_die_across_parameters_inside_one_window(self):
        from tests.test_wafer_static import finish_graphics, map_fixture

        raw, _ = map_fixture(2, 2)
        raw.loc[3, "P0"] = ""
        _, child = self.open_match_map(raw)
        child.resize(1350, 780)
        page, radius = child.plot_page, child.radius_page
        child.tabs.setCurrentWidget(radius)
        radius.selector.selectAll()
        radius.draw_plot()
        child.tabs.setCurrentWidget(page)
        page.selector.selectAll()
        page.draw_maps()
        finish_graphics(page)
        origin = next(panel for panel in page.map_grid.panels
                      if 11 in panel.point_rows() and panel.source["metric"] == "P0")
        linked = next(panel for panel in page.map_grid.panels
                      if 11 in panel.point_rows() and panel.source["metric"] == "P1")
        unrelated = next(panel for panel in page.map_grid.panels
                         if panel.source["wafer"] != origin.source["wafer"])
        radius_linked = next(panel for panel in radius.radius_grid.panels
                             if 11 in panel.point_rows() and panel.source["metric"] == "P1")

        self.assertEqual(origin.point_rows()[10], 11)
        self.click_map_panel(page, origin, 10)
        self.assertEqual(page.scroll.panel_point_state(origin)[0], {11})
        self.paint_map_ring(origin).drawEllipse.assert_not_called()
        self.paint_map_ring(linked).drawEllipse.assert_called_once_with(
            QPointF(*linked._pixel_positions[11]), 6, 6)
        self.paint_map_ring(radius_linked).drawEllipse.assert_called_once_with(
            QPointF(*radius_linked._pixel_positions[11]), 6, 6)
        self.paint_map_ring(unrelated).drawEllipse.assert_not_called()

        QTest.mouseClick(page.scroll.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
        self.assertFalse(page.scroll.panel_point_state(origin)[0])
        self.paint_map_ring(linked).drawEllipse.assert_not_called()
        self.paint_map_ring(radius_linked).drawEllipse.assert_not_called()

    @staticmethod
    def paint_map_ring(panel):
        from metrology_app.wafer_graphics import paint_chart_preview

        painter = Mock()
        paint_chart_preview(panel, painter)
        return painter

    @staticmethod
    def click_map_panel(page, panel, index):
        center = panel.mapToScene(QPointF(*panel._pixel_positions[index]))
        QTest.mouseClick(page.scroll.viewport(), Qt.MouseButton.LeftButton,
                         pos=page.scroll.mapFromScene(center))

    def test_wafer_maps_and_radius_paint_the_shared_linked_preview_ring(self):
        from metrology_app.window import MainWindow
        from metrology_app.wafer_graphics import paint_chart_preview

        window = MainWindow()
        window.document.force_close = True
        self.addCleanup(window.close)
        self.assertIn(window.plot_page.scroll, window._chart_edits._preview_listeners)
        self.assertIn(window.radius_page.scroll, window._chart_edits._preview_listeners)

        panel = SimpleNamespace(
            point_rows=lambda: np.array([3, 7]),
            _pixel_positions=np.array([[10.0, 20.0], [30.0, 40.0]]),
        )
        painter = Mock()
        paint_chart_preview(panel, painter, rows={7})
        painter.drawEllipse.assert_called_once()
