"""v4.1.0 user workflows: reversible views, safe edits and plot inspection."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np
import pandas as pd
from PyQt6.QtCore import QPointF, QTimer, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QCheckBox, QLineEdit, QPushButton

from metrology_app.matching_window import MatchingWindow
from metrology_app.correlation_window import CorrelationWindow
from metrology_app.dynamic_window import DynamicWindow
from metrology_app.match_group_ui import ProjectedSheetModel
from metrology_app.plot import ValueLabels
from metrology_app.settings import get_settings, save_settings
from metrology_app.window import MainWindow

APP = QApplication.instance() or QApplication([])


class V41Workflows(unittest.TestCase):
    def setUp(self):
        saved = get_settings()
        self.addCleanup(save_settings, saved)

    def close(self, window):
        window.document.force_close = True
        window.close()
        window.deleteLater()
        APP.processEvents()

    def match(self):
        window = MatchingWindow()
        self.addCleanup(self.close, window)
        window.set_reference_frame(pd.DataFrame({"CD Reference": [3., 5., 7., 9., 11., 13.]}))
        window.set_raw_frame(pd.DataFrame({"Wafer ID": ["W1"] * 3 + ["W2"] * 3,
                                           "Die Seq": [1, 2, 3] * 2, "CD": [1., 2., 3., 4., 5., 6.]}))
        window.run_analysis()
        return window

    def select(self, window, hide, exclude=True):
        errors = []
        def choose():
            dialog = APP.activeModalWidget()
            try:
                if exclude:
                    dialog.findChild(QLineEdit, "dataSelectionSearch").setText("W2")
                    next(button for button in dialog.findChildren(QPushButton)
                         if button.text() == "Uncheck Visible").click()
                dialog.hide_excluded.setChecked(hide)
                dialog.accept()
            except Exception as error:
                errors.append(error)
                dialog.reject()
        QTimer.singleShot(0, choose)
        window.data_selection_action.trigger()
        self.assertEqual(errors, [])

    def test_hidden_participation_is_reversible_and_edits_only_visible_source_rows(self):
        window = self.match()
        before = window.workspace_snapshot().frames
        self.select(window, True)
        for view in (window.order_view, window.reference_view, window.raw_view):
            self.assertIsInstance(view.model(), ProjectedSheetModel)
            self.assertEqual(view.model().rowCount(), 4)
        proxy = window.raw_view.model()
        proxy.paste_cells({(1, 2): "91.000", (2, 2): "92.000"}, bounds=(1, 2, 2, 2))
        self.assertEqual(window.raw_model.cells[(1, 2)], "91.000")
        self.assertEqual(window.raw_model.cells[(4, 2)], before["raw"].iloc[3, 2])
        self.select(window, False, exclude=False)
        self.assertIs(window.raw_view.model(), window.raw_model)
        self.assertEqual(window.result.source_rows, (0, 1, 2))
        self.assertEqual(len(window.raw_model.document_frame()), 6)

    def test_hidden_table_captions_report_visible_and_total_rows(self):
        window = self.match()
        self.select(window, True)
        for label, columns in ((window.order_source, 4), (window.reference_source, 1),
                               (window.raw_source, 3)):
            self.assertEqual(label.text(), f"3 visible / 6 rows × {columns} columns")
        self.select(window, False, exclude=False)
        for label, columns in ((window.order_source, 4), (window.reference_source, 1),
                               (window.raw_source, 3)):
            self.assertEqual(label.text(), f"6 rows × {columns} columns")

    def test_partial_visible_paste_keeps_counts_and_unhide_restores_untouched_rows(self):
        window = self.match()
        self.select(window, True)
        proxy = window.raw_view.model()
        proxy.paste_cells({(1, 2): "91.000", (2, 2): "92.000"}, bounds=(1, 2, 2, 2))
        self.assertEqual(window.raw_source.text(), "3 visible / 6 rows × 3 columns")
        self.select(window, False, exclude=False)
        self.assertEqual(window.raw_model.document_frame()["CD"].tolist(),
                         ["91.000", "92.000", "3.0", "4.0", "5.0", "6.0"])
        self.assertEqual(window.raw_source.text(), "6 rows × 3 columns")

    def test_workbook_captions_follow_replacement_growth_and_undo(self):
        window = self.match()
        window.set_raw_frame(pd.DataFrame({"Wafer ID": ["W1"] * 4, "CD": [1, 2, 3, 4]}))
        self.assertEqual(window.raw_source.text(), "4 rows × 2 columns")
        self.assertEqual(window.order_source.text(), "4 rows × 4 columns")
        window.raw_model.edit({(0, 2): "New parameter", (5, 2): "5.000"})
        self.assertEqual(window.raw_source.text(), "5 rows × 3 columns")
        self.assertEqual(window.order_source.text(), "5 rows × 4 columns")
        window.raw_model.undo.undo()
        self.assertEqual(window.raw_source.text(), "4 rows × 2 columns")

    def test_order_caption_keeps_actual_rows_when_a_draft_has_more_flags_than_raw(self):
        window = self.match()
        window.group_controls.order_model.edit({(8, 0): "0"})
        self.assertEqual(window.order_source.text(), "8 rows × 4 columns")
        self.assertEqual(window.raw_source.text(), "6 rows × 3 columns")

    def test_analysis_counts_include_blank_source_rows_and_survive_invalid_headers(self):
        window = MainWindow()
        self.addCleanup(self.close, window)
        window.set_table(pd.DataFrame({"Wafer ID": ["W1", "", "W1"], "CD": ["1", "", "3"]}), "Fixture")
        self.assertEqual(window.data_badge.text(), "3 rows × 2 columns")
        window.model.edit({(0, 1): "Wafer ID"})
        window.recognize()
        self.assertEqual(window.data_badge.text(), "3 rows × 2 columns")
        self.assertEqual(window.model.document_shape(), window.model.document_frame().shape)
        window.set_table(pd.DataFrame(), "Empty")
        self.assertEqual(window.data_badge.text(), "0 rows × 0 columns")

    def test_analysis_table_sizes_refresh_on_edits_without_waiting_for_recognition(self):
        frame = pd.DataFrame({"Wafer ID": ["W1"] * 3, "Die Seq": [1, 2, 3], "CD": [1, 2, 3]})
        for kind in (MainWindow, CorrelationWindow, DynamicWindow):
            with self.subTest(kind=kind.__name__):
                window = kind()
                self.addCleanup(self.close, window)
                window.set_table(frame, "Fixture")
                columns = len(window.model.document_frame().columns)
                self.assertEqual(window.data_badge.text(), f"3 rows × {columns} columns")
                window.model.edit({(0, columns): "New parameter", (4, columns): "4.000"})
                self.assertEqual(window.data_badge.text(), f"4 rows × {columns + 1} columns")
                window.model.undo.undo()
                self.assertEqual(window.data_badge.text(), f"3 rows × {columns} columns")

    def test_correlation_reference_size_refreshes_on_edits_replacement_and_undo(self):
        window = CorrelationWindow()
        self.addCleanup(self.close, window)
        window.set_reference_table(pd.DataFrame({"Wafer ID": ["W1"] * 3, "CD": [1, 2, 3]}))
        window.reference_model.edit({(0, 2): "New parameter", (4, 2): "4.000"})
        self.assertEqual(window.reference_footer.text(), "4 rows × 3 columns")
        window.recognize()
        self.assertEqual(window.reference_footer.text(), "4 rows × 3 columns")
        window.reference_model.undo.undo()
        self.assertEqual(window.reference_footer.text(), "3 rows × 2 columns")
        window.set_reference_table(pd.DataFrame({"CD": [1, 2]}))
        self.assertEqual(window.reference_footer.text(), "2 rows × 1 columns")

    def test_linked_analysis_captions_distinguish_visible_rows_from_total(self):
        window = self.match()
        self.select(window, True)
        child = window.open_stage_workspace("preview")
        self.assertEqual(child.data_badge.text(), "3 visible / 6 rows × 3 columns")
        child.full_data_action.trigger()
        self.assertEqual(child.data_badge.text(), "6 rows × 3 columns")
        correlation = window.open_correlation_workspace()
        correlation.set_reference_table(window.reference_model.document_frame())
        correlation.update_plan()
        self.assertTrue(correlation.data_badge.text().startswith("3 visible / 6 rows"))
        self.assertTrue(correlation.reference_footer.text().startswith("3 visible / 6 rows"))

    def test_projected_paste_overflow_and_replace_cannot_touch_hidden_rows(self):
        window = self.match()
        self.select(window, True)
        before = window.raw_model.document_frame()
        proxy = window.raw_view.model()
        with self.assertRaises(ValueError):
            proxy.paste_cells({(4, 2): "99"}, bounds=(1, 2, 4, 2))
        with self.assertRaises(ValueError):
            proxy.replace_matrix([["CD"], ["99"]])
        pd.testing.assert_frame_equal(window.raw_model.document_frame(), before)

    def test_partial_paste_maps_noncontiguous_visible_rows_and_undo_restores_them(self):
        window = self.match()
        errors = []
        def choose():
            dialog = APP.activeModalWidget()
            try:
                dialog.model.checked.difference_update((dialog.model.ids[1], dialog.model.ids[4]))
                dialog.hide_excluded.setChecked(True)
                dialog.accept()
            except Exception as error:
                errors.append(error)
                dialog.reject()
        QTimer.singleShot(0, choose)
        window.data_selection_action.trigger()
        self.assertEqual(errors, [])
        proxy = window.raw_view.model()
        self.assertEqual([proxy.headerData(row, Qt.Orientation.Vertical) for row in range(5)],
                         ["1", "2", "4", "5", "7"])
        for view in (window.order_view, window.reference_view, window.raw_view):
            self.assertEqual(view.model().hidden_rows_before(2), (3, 3))
            self.assertEqual(view.model().hidden_rows_before(4), (6, 6))
        before = window.raw_model.document_frame()
        APP.clipboard().setText("91.000\n92.000\n93.000")
        window.raw_view.setCurrentIndex(proxy.index(1, 2))
        window.raw_view.paste()
        values = window.raw_model.document_frame()["CD"].tolist()
        self.assertEqual(values, ["91.000", "2.0", "92.000", "93.000", "5.0", "6.0"])
        window.raw_model.undo.undo()
        pd.testing.assert_frame_equal(window.raw_model.document_frame(), before)
        APP.clipboard().setText("CD\n91.000\n92.000\n93.000\n94.000")
        window.raw_view.setCurrentIndex(proxy.index(0, 2))
        window.raw_view.paste()
        self.assertEqual(window.raw_source.text(), "4 visible / 6 rows × 3 columns")
        self.select(window, False, exclude=False)
        self.assertEqual(window.raw_model.document_frame()["CD"].tolist(),
                         ["91.000", "2.0", "92.000", "93.000", "5.0", "94.000"])
        self.assertEqual(window.raw_source.text(), "6 rows × 3 columns")

    def test_hidden_selection_survives_workspace_restore_and_unhide_in_child(self):
        window = self.match()
        self.select(window, True)
        snapshot = window.workspace_snapshot()
        window.restore_workspace(snapshot)
        self.assertEqual(window.raw_view.model().rowCount(), 4)
        child = window.open_correlation_workspace()
        child.set_reference_table(window.reference_model.document_frame(), "Manual Ref")
        child.update_plan()
        self.assertEqual(child.raw_sheet.model().rowCount(), 4)
        self.assertEqual(child.reference_sheet.model().rowCount(), 4)
        self.select(window, False, exclude=False)
        self.assertIs(child.raw_sheet.model(), child.raw_model)
        self.assertIs(child.reference_sheet.model(), child.reference_model)
        self.assertEqual(len(child.raw_model.document_frame()), 6)
        self.assertEqual(window.result.source_rows, (0, 1, 2))

    def test_partial_exclusion_refreshes_map_and_radius_membership_without_reloading_sources(self):
        window = self.match()
        child = window.open_stage_workspace("preview")
        before = child.model.document_frame()
        retained = MainWindow()
        self.addCleanup(self.close, retained)
        retained.set_table(before, "Retained editor")
        retained_source = retained._frame
        errors = []
        def choose():
            dialog = APP.activeModalWidget()
            try:
                dialog.model.checked.remove(dialog.model.ids[1])
                dialog.hide_excluded.setChecked(True)
                dialog.accept()
            except Exception as error:
                errors.append(error)
                dialog.reject()
        QTimer.singleShot(0, choose)
        window.data_selection_action.trigger()
        self.assertEqual(errors, [])
        retained.set_workbook_participation(window.current_workbook())
        self.assertIs(retained._frame, retained_source)
        self.assertEqual(child.participating_positions(child.model.frame()), {0, 2, 3, 4, 5})
        self.assertEqual(child.sheet.model().hidden_rows_before(2), (3, 3))
        for page in (child.plot_page, child.radius_page, retained.plot_page, retained.radius_page):
            rows = set().union(*(page.selection["groups"][key] for key in page.selection["wafers"]))
            self.assertEqual(rows, {0, 2, 3, 4, 5})
        pd.testing.assert_frame_equal(child.model.document_frame(), before)

    def test_child_table_obeys_hidden_workbook_scope_and_full_data_restores_rows(self):
        window = self.match()
        self.select(window, True)
        child = window.open_stage_workspace("preview")
        child.set_copy_from_wkb(True)
        self.assertEqual(child.sheet.model().rowCount(), 4)
        self.assertIsInstance(child.sheet.model(), ProjectedSheetModel)
        self.assertEqual(len(child.plot_page.selection["wafers"]), 1)
        child.full_data_action.trigger()
        self.assertIs(child.sheet.model(), child.model)
        self.assertEqual(len(child.model.document_frame()), 6)
        self.assertEqual(len(child.plot_page.selection["wafers"]), 2)

    def test_statistics_are_default_hover_not_a_checkbox_or_title(self):
        window = self.match()
        group = window.plot_groups["CD"]
        self.assertFalse(any(check.text() == "Statistics" for check in group["card"].findChildren(QCheckBox)))
        for name in ("trend", "bias"):
            plot = group["plots"][name]
            self.assertIn("Mean:", plot.getViewBox().toolTip())
            self.assertIn("σ:", plot.getViewBox().toolTip())
            self.assertFalse(hasattr(plot, "statistics_label"))
        group["plots"]["trend"].card_checkbox.setChecked(False)
        self.assertIn("Mean: 3.5", group["plots"]["trend"].getViewBox().toolTip())

    def test_leaving_a_measurement_point_restores_statistics_tooltip(self):
        window = self.match()
        window.show()
        APP.processEvents()
        plot = window.plot_groups["CD"]["plots"]["trend"]
        item = plot.listDataItems()[0]
        item.scatter.hoverEvent(SimpleNamespace(exit=False, pos=lambda: QPointF(item.xData[0], item.yData[0])))
        self.assertIn("Die: 1", plot.getViewBox().toolTip())
        self.assertNotIn("Mean:", plot.getViewBox().toolTip())
        item.scatter.hoverEvent(SimpleNamespace(exit=True))
        self.assertIn("Mean:", plot.getViewBox().toolTip())

    def test_classified_boundaries_distinguish_group_from_wafer_in_child(self):
        window = self.match()
        window.match_type.setCurrentText("NOVA")
        raw = pd.DataFrame({"Wafer ID": ["W1"] * 3 + ["W2"] * 3 + ["W3"] * 3,
                            "Die Seq": [1, 2, 3] * 3, "CD": list(range(1, 10))})
        window.set_reference_frame(pd.DataFrame({"CD Reference": list(range(2, 20, 2))}))
        window.set_raw_frame(raw)
        window.group_controls.restore({"enabled": True}, pd.DataFrame({"TestFlag": [0] * 6 + [1] * 3}))
        window.run_analysis()
        child = window.open_correlation_workspace()
        page = child.sequence_page
        page.selector.selectAll()
        page.draw_plot()
        self.assertTrue(page.ready, page.status.text())
        plot = page.plot_widgets[0]
        self.assertEqual(plot.group_boundaries.positions, (5.5,))
        self.assertEqual(plot.wafer_boundaries.positions, (2.5,))
        self.assertEqual(plot.group_boundaries.pen.widthF(), 2)
        self.assertEqual(plot.wafer_boundaries.pen.widthF(), 1)
        self.assertIn("Mean:", plot.getViewBox().toolTip())
        self.assertFalse(any(check.text() == "Show statistics" for check in page.findChildren(QCheckBox)))

    def test_wafer_boundaries_are_thin_grey_and_behind_measurements(self):
        window = self.match()
        for name in ("trend", "bias"):
            plot = window.plot_groups["CD"]["plots"][name]
            boundary = plot.wafer_boundaries
            self.assertEqual(boundary.pen.widthF(), 1.)
            self.assertEqual(boundary.pen.color().name(), "#929292")
            self.assertLess(boundary.zValue(), plot.listDataItems()[0].zValue())

    def test_group_and_all_parameter_trend_cards_are_exclusive_and_use_distinct_fits(self):
        window = self.match()
        window.match_type.setCurrentText("NOVA")
        window.set_reference_frame(pd.DataFrame({"CD Reference": [3., 5., 7., 30., 40., 50.]}))
        window.group_controls.restore({"enabled": True}, pd.DataFrame({"TestFlag": [0] * 3 + [1] * 3}))
        window.run_analysis()
        page = window.group_plot_page
        page.use_group_card.setChecked(True)
        self.assertFalse(page.card.isChecked())
        block = next(iter(page.plot_groups.values()))
        curve = next(item for item in block["plots"]["trend"].listDataItems() if item.name() == "PMISH")
        scoped = block["result"]
        raw = scoped.series("CD")["Raw"].to_numpy(float)
        local = scoped.plot_fits["CD"]
        np.testing.assert_allclose(curve.yData, raw * local.slope + local.intercept)
        page.card.setChecked(True)
        self.assertFalse(page.use_group_card.isChecked())
        block = next(iter(page.plot_groups.values()))
        curve = next(item for item in block["plots"]["trend"].listDataItems() if item.name() == "PMISH")
        overall = window.result.card("CD")
        np.testing.assert_allclose(curve.yData, raw * overall.slope + overall.intercept)

    def test_raw_card_floats_and_returns_with_the_same_live_editor(self):
        window = self.match()
        window.show()
        APP.processEvents()
        editor, model = window.raw_view, window.raw_model
        QTest.mouseDClick(window.raw_card, Qt.MouseButton.LeftButton)
        self.assertTrue(window.raw_card.window().isWindow())
        self.assertIsNot(window.raw_card.window(), window)
        self.assertIs(window.raw_view, editor)
        model.edit({(1, 2): "100.000"})
        QTest.mouseDClick(window.raw_card, Qt.MouseButton.LeftButton)
        self.assertIs(window.raw_card.parentWidget(), window.inputs_splitter)
        self.assertIs(window.raw_view.model(), model)
        self.assertEqual(model.cells[(1, 2)], "100.000")
        model.undo.undo()
        self.assertEqual(model.cells[(1, 2)], "1.0")

    def test_decimals_round_half_up_and_are_global_not_workspace_state(self):
        labels = ValueLabels(np.zeros((4, 2)), [2.675, -2.675, 1.005, -1.005], 8)
        self.assertEqual(labels.labels, ["2.68", "-2.68", "1.01", "-1.01"])
        save_settings({"point_value_decimals": 2})
        first, second = MainWindow(), MainWindow()
        self.addCleanup(self.close, first)
        self.addCleanup(self.close, second)
        first.plot_page.point_decimals.setValue(4)
        self.assertEqual(get_settings()["point_value_decimals"], 4)
        self.assertEqual(second.plot_page.point_decimals.value(), 4)
        snapshot = first.workspace_snapshot()
        self.assertNotIn("point_decimals", snapshot.states["ui"]["pages"]["plot_page"]["controls"])
        legacy = deepcopy(snapshot)
        legacy.states["ui"]["pages"]["plot_page"]["controls"]["point_decimals"] = 1
        first.restore_workspace(legacy)
        self.assertEqual(first.plot_page.point_decimals.value(), 4)
