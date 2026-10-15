"""Wafer captions and scrollable trends through WKB and displayed plots."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd
import numpy as np
from PyQt6.QtCore import QPoint, QTimer, Qt
from PyQt6.QtGui import QFontMetricsF
from PyQt6.QtWidgets import QApplication, QCheckBox, QInputDialog, QLineEdit, QPushButton

from metrology_app.matching_window import MatchingWindow


APP = QApplication.instance() or QApplication([])


class TrendWaferLabelTests(unittest.TestCase):
    def test_expand_checkbox_uses_the_same_expand_wafers_name(self):
        child = self.parent.open_correlation_workspace()
        self.assertEqual(self.parent.expand_wafer_ids.text(), "Expand Wafers")
        self.assertEqual(child.sequence_page.expand_wafer_ids.text(), "Expand Wafers")

    def test_expand_collects_interleaved_wafer_identities_without_touching_sources(self):
        """Expanded Trends draw each Wafer / Lot / PAD identity as one range."""
        parent = self.parent
        raw = pd.DataFrame({
            "Wafer ID": ["W1", "W1", "W2", "W2", "W1", "W1", "W2", "W2"],
            "Lot ID": ["L1", "L2", "L1", "L2", "L1", "L2", "L1", "L2"],
            "PAD Name": ["ARRAY"] * 8,
            "Die Seq": [1, 1, 1, 1, 2, 2, 2, 2],
            "CD": [f"{value}.000" for value in range(1, 9)],
        })
        parent.set_reference_frame(pd.DataFrame({"CD Reference": 2 * np.arange(1, 9)}))
        parent.set_raw_frame(raw)
        parent.run_analysis()
        parent.resize(1600, 1000)
        parent.show()
        APP.processEvents()
        group = parent.plot_groups["CD"]
        trend = group["plots"]["trend"]

        def pmish():
            return next(item for item in trend.listDataItems() if item.name() == "PMISH")

        def identity_lines():
            axis = trend.getAxis("bottom")
            return [label.splitlines()[0] for _, _, label in axis.spans]

        curve = pmish()
        row_order = parent.result.series("CD")["Card Value"].to_numpy(float)
        collected = parent.result.group_series("CD", trend=True, collect_wafers=True)["Card Value"].to_numpy(float)
        np.testing.assert_array_equal(curve.yData, row_order)
        # Source order alternates Wafer and Lot, so each row is its own run.
        self.assertEqual(identity_lines(), ["W1", "W1", "W2", "W2", "W1", "W1", "W2", "W2"])
        self.assertEqual(parent.result.group_plan.state["trend_order"], "original")

        parent.expand_wafer_ids.click()
        APP.processEvents()
        self.assertIs(pmish(), curve, "Expansion must keep the drawn Trend curve")
        np.testing.assert_array_equal(curve.yData, collected)
        self.assertEqual(identity_lines(), ["W1", "W1", "W2", "W2"])
        self.assertEqual([label.splitlines()[1] for _, _, label in trend.getAxis("bottom").spans],
                         ["LOT: L1", "LOT: L2", "LOT: L1", "LOT: L2"])
        self.assertEqual(parent.result.group_plan.state["trend_order"], "original",
                         "Expansion is a display choice; the saved Trend order stays")

        parent.expand_wafer_ids.click()
        APP.processEvents()
        np.testing.assert_array_equal(curve.yData, row_order)
        self.assertEqual(identity_lines(), ["W1", "W1", "W2", "W2", "W1", "W1", "W2", "W2"])
        pd.testing.assert_frame_equal(parent.raw_model.frame(), raw.astype(str))

    def test_expand_uneven_wafers_is_compact_and_keeps_every_observation(self):
        counts = [1, 7, 83, 120] * 3
        raw = pd.DataFrame({
            "Wafer ID": [f"Wafer-2026-VERY-LONG-IDENTITY-{i:03}"
                         for i, count in enumerate(counts) for _ in range(count)],
            "Lot ID": ["L001"] * sum(counts), "PAD Name": ["ARRAY"] * sum(counts),
            "Die Seq": [str(die) for count in counts for die in range(1, count + 1)],
            "CD": [f"{value}.000" for value in range(1, sum(counts) + 1)],
        })
        parent = self.parent
        parent.set_reference_frame(pd.DataFrame({"CD Reference": 2 * np.arange(1, len(raw) + 1)}))
        parent.set_raw_frame(raw)
        parent.percent_bias.setChecked(True)
        parent.run_analysis()
        parent.resize(1600, 1000)
        parent.show()
        child = parent.open_correlation_workspace()
        page = self.draw_child(child)
        group = parent.plot_groups["CD"]
        plots = [group["plots"][name] for name in ("trend", "bias", "bias-percent")]
        plots += page.plot_widgets
        original = {plot: [(curve, curve.xData.copy(), curve.yData.copy())
                           for curve in plot.listDataItems()] for plot in plots}
        layout = group["plot_area"].saveState()
        selected = page.selector.selected_cells()
        parent.expand_wafer_ids.click()
        page.expand_wafer_ids.click()
        APP.processEvents()
        for plot in plots:
            axis = getattr(plot, "_wafer_axis", None) or plot.getAxis("bottom")
            metrics = QFontMetricsF(axis.style.get("tickFont") or plot.font())
            caption_budget = sum(max(metrics.horizontalAdvance(line) for line in label.splitlines()) + 16
                                 for _, _, label in axis.spans)
            self.assertLess(plot.minimumWidth(), 2 * len(raw) + caption_budget + 500,
                            "A one-point wafer must not stretch every other wafer")
            self.assertEqual([label for _, label in axis._tickLevels[0]],
                             [label for _, _, label in axis.spans])
            for curve, x, y in original[plot]:
                self.assertIn(curve, plot.listDataItems())
                np.testing.assert_array_equal(curve.yData, y)
                self.assertEqual(len(curve.xData), len(x))
                self.assertTrue(np.all(np.diff(curve.xData) > 0))
        self.assertGreater(group["plot_scroll"].horizontalScrollBar().maximum(), 0)
        self.assertGreater(page.interactive_scroll.horizontalScrollBar().maximum(), 0)
        self.assertEqual(page.selector.selected_cells(), selected)
        parent.expand_wafer_ids.click()
        page.expand_wafer_ids.click()
        APP.processEvents()
        self.assertEqual(group["plot_area"].saveState(), layout)
        self.assertEqual(page.interactive_scroll.horizontalScrollBar().maximum(), 0)
        for plot in plots:
            for curve, x, y in original[plot]:
                np.testing.assert_array_equal(curve.xData, x)
                np.testing.assert_array_equal(curve.yData, y)
        pd.testing.assert_frame_equal(parent.raw_model.frame(), raw)
        pd.testing.assert_frame_equal(child.raw_model.frame(), raw)

    def test_expanded_card_toggle_keeps_wafer_spacing_and_zoom(self):
        raw = self.raw.copy()
        raw["Wafer ID"] = ["W001"] + ["W002"] * 11
        self.parent.set_raw_frame(raw)
        self.parent.run_analysis()
        self.parent.expand_wafer_ids.setChecked(True)
        plot = self.parent.plot_groups["CD"]["plots"]["trend"]
        positions = plot.listDataItems()[0].xData.copy()
        plot.setXRange(2, 6, padding=0)
        view = plot.getViewBox().viewRange()
        plot.card_checkbox.click()
        APP.processEvents()
        for curve in plot.listDataItems():
            np.testing.assert_array_equal(curve.xData, positions)
        self.assertEqual(plot.getViewBox().viewRange(), view)
        np.testing.assert_array_equal(plot.listDataItems()[0].yData, np.arange(1, 13))
        plot.card_checkbox.click()
        for curve in plot.listDataItems():
            np.testing.assert_array_equal(curve.xData, positions)
        self.parent.expand_wafer_ids.setChecked(False)
        for curve in plot.listDataItems():
            np.testing.assert_array_equal(curve.xData, np.arange(1, 13))

    def test_group_wafer_expansion_keeps_classification_and_card_spacing(self):
        parent = self.parent
        raw = self.raw.copy()
        raw["Wafer ID"] = ["W001"] + ["W002"] * 11
        parent.set_raw_frame(raw)
        parent.group_controls.restore({"enabled": True, "mark_enabled": False,
                                       "head_names": {"0": "Optical A"},
                                       "show_wafer_groups": ["All:0"]},
                                      pd.DataFrame({"TestFlag": [0] * 12}))
        parent.run_analysis()
        before = parent.result.group_series("CD", trend=True).copy()
        block = parent.group_plot_page.plot_groups[("All:0", "CD")]
        plot = block["plots"]["trend"]
        source_x = plot.listDataItems()[0].xData.copy()
        parent.expand_wafer_ids.setChecked(True)
        positions = plot.listDataItems()[0].xData.copy()
        self.assertEqual([label for _, label in plot._wafer_axis._tickLevels[0]],
                         [label for _, _, label in plot._group_tick_data[2]])
        plot.card_checkbox.click()
        APP.processEvents()
        for curve in plot.listDataItems():
            np.testing.assert_array_equal(curve.xData, positions)
        parent.plot_label_checks["trend"]["lot"].click()
        self.assertEqual([label for _, _, label in plot._group_tick_data[1]], ["Optical A"])
        self.assertEqual([label for _, label in plot._wafer_axis._tickLevels[0]],
                         ["W001\nPAD: ARRAY", "W002\nPAD: ARRAY"])
        pd.testing.assert_frame_equal(parent.result.group_series("CD", trend=True), before)
        parent.expand_wafer_ids.setChecked(False)
        for curve in plot.listDataItems():
            np.testing.assert_array_equal(curve.xData, source_x)

    def test_expanded_comparison_uses_identical_spacing_on_both_y_axes(self):
        raw = self.raw.copy()
        raw["Wafer ID"] = ["W001"] + ["W002"] * 11
        self.parent.set_raw_frame(raw)
        self.parent.run_analysis()
        child = self.parent.open_correlation_workspace()
        page = self.draw_child(child)
        page.axis_mode.setCurrentIndex(page.axis_mode.findData("dual"))
        self.assertTrue(page.set_overlay("CD Reference", "CD", "Reference", "Raw Data"))
        plot = next(widget for widget in page.plot_widgets if widget.secondary_views)
        primary = plot.listDataItems()[0]
        comparison = next(item for item in plot.secondary_views[0].addedItems if hasattr(item, "xData"))
        source_x = primary.xData.copy()
        primary_y, comparison_y = primary.yData.copy(), comparison.yData.copy()
        page.expand_wafer_ids.setChecked(True)
        APP.processEvents()
        np.testing.assert_array_equal(primary.xData, comparison.xData)
        self.assertFalse(np.array_equal(primary.xData, source_x))
        np.testing.assert_array_equal(primary.yData, primary_y)
        np.testing.assert_array_equal(comparison.yData, comparison_y)
        plot.setXRange(2, 6, padding=0)
        ranges = plot.getViewBox().viewRange()[0]
        page.expand_wafer_ids.setChecked(False)
        page.expand_wafer_ids.setChecked(True)
        np.testing.assert_allclose(plot.getViewBox().viewRange()[0], ranges, rtol=0, atol=1e-10)
        page.expand_wafer_ids.setChecked(False)
        np.testing.assert_array_equal(primary.xData, source_x)
        np.testing.assert_array_equal(comparison.xData, source_x)

    def test_copy_png_refreshes_compact_spacing_even_when_the_grid_size_is_unchanged(self):
        raw = self.raw.copy()
        raw["Wafer ID"] = ["W001"] + ["W002"] * 11
        self.parent.set_raw_frame(raw)
        self.parent.run_analysis()
        page = self.draw_child(self.parent.open_correlation_workspace())
        page.copy_png()
        compact = APP.clipboard().image().copy()
        size = page.plot_host.size()
        page.expand_wafer_ids.click()
        APP.processEvents()
        self.assertEqual(page.plot_host.size(), size)
        page.copy_png()
        self.assertFalse(APP.clipboard().image().isNull())
        self.assertNotEqual(APP.clipboard().image(), compact,
                            "Copy PNG must show the new wafer spacing, not a cached compact image")

    def setUp(self):
        self.parent = MatchingWindow()
        self.addCleanup(self.close, self.parent)
        self.parent.match_type.setCurrentText("NOVA")
        self.raw = pd.DataFrame({
            "Wafer ID": ["W001"] * 6 + ["W002"] * 6,
            "Lot ID": ["L001"] * 12, "PAD Name": ["ARRAY"] * 12,
            "Die Seq": [str(value) for value in range(1, 7)] * 2,
            "CD": [f"{value}.000" for value in range(1, 13)],
        })
        self.parent.set_reference_frame(pd.DataFrame({"CD Reference": [2 * value for value in range(1, 13)]}))
        self.parent.set_raw_frame(self.raw)
        self.parent.run_analysis()

    @staticmethod
    def close(window):
        window.document.force_close = True
        window.close()
        window.deleteLater()
        APP.processEvents()

    def draw_child(self, child):
        page = child.sequence_page
        child.tabs.setCurrentWidget(page)
        child.resize(1600, 850)
        child.show()
        page.selector.selectAll()
        page.draw_plot()
        APP.processEvents()
        self.assertTrue(page.ready, page.status.text())
        return page

    def test_reopened_linked_trend_uses_current_workbook_classification(self):
        parent = self.parent
        parent.group_controls.mark_enabled.setChecked(True)
        parent.group_controls.apply_button.click()
        child = parent.open_correlation_workspace()
        page = self.draw_child(child)
        self.assertEqual({text for widget in page.plot_widgets
                          for _, _, text in widget._wafer_axis.spans}, {"Old"})
        with TemporaryDirectory() as folder:
            path = Path(folder) / "wafer-captions.wkb"
            parent.save_workbook(path)
            self.close(child)
            parent.group_controls.mark_enabled.setChecked(False)
            parent.group_controls.enabled.setChecked(False)
            parent.group_controls.apply_button.click()
            parent.save_workbook(path)
            reopened = MatchingWindow()
            self.addCleanup(self.close, reopened)
            reopened.load_workbook(path)
            restored = reopened.open_correlation_workspace()
            restored.tabs.setCurrentWidget(restored.sequence_page)
            restored.resize(1600, 850)
            restored.show()
            APP.processEvents()
            page = restored.sequence_page
            self.assertTrue(page.ready, page.status.text())
            self.assertEqual({text for widget in page.plot_widgets
                              for _, _, text in widget._wafer_axis.spans},
                             {"W001\nLOT: L001\nPAD: ARRAY", "W002\nLOT: L001\nPAD: ARRAY"})
            self.assertTrue(page.selector.selected_cells())
            self.assertFalse(page.selector.pending_draw)
            self.assertEqual([curve.yData.tolist() for widget in page.plot_widgets
                              for curve in widget.listDataItems()],
                             [[float(2 * value) for value in range(1, 13)],
                              [float(value) for value in range(1, 13)]])
            pd.testing.assert_frame_equal(restored.raw_model.frame(), self.raw)
            # The reconciled boxes must remain valid for the next Save/reopen.
            reopened.save_workbook(path)
            reopened.load_workbook(path)
            again = reopened.open_correlation_workspace().sequence_page
            self.assertTrue(again.ready, again.status.text())
            self.assertTrue(again.selector.selected_cells())

    def test_expand_child_trend_shows_every_wafer_and_scrolls_without_redrawing(self):
        count = 40
        raw = pd.DataFrame({
            "Wafer ID": [f"Wafer-2026-VERY-LONG-IDENTITY-{i // 6:03}" for i in range(6 * count)],
            "Lot ID": ["L001"] * (6 * count), "PAD Name": ["ARRAY"] * (6 * count),
            "Die Seq": [1, 2, 3, 4, 5, 6] * count,
            "CD": list(range(1, 6 * count + 1)),
        })
        self.parent.set_reference_frame(pd.DataFrame({"CD Reference": 2 * raw.CD}))
        self.parent.set_raw_frame(raw)
        self.parent.run_analysis()
        child = self.parent.open_correlation_workspace()
        page = self.draw_child(child)
        control = page.findChild(QCheckBox, "expandWaferIds")
        self.assertIsNotNone(control, "Trend needs an Expand wafer IDs checkbox")
        curves = [tuple(widget.listDataItems()) for widget in page.plot_widgets]
        views = [widget.getViewBox().viewRange() for widget in page.plot_widgets]
        selected = page.selector.selected_cells()
        control.click()
        APP.processEvents()
        bar = page.interactive_scroll.horizontalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        for widget, before, ranges in zip(page.plot_widgets, curves, views):
            self.assertEqual(tuple(widget.listDataItems()), before)
            self.assertEqual(widget.getViewBox().viewRange(), ranges)
            labels = [text for _, text in widget._wafer_axis._tickLevels[0]]
            self.assertEqual(labels, [text for _, _, text in widget._wafer_axis.spans])
        bar.setValue(bar.maximum())
        self.assertEqual(bar.value(), bar.maximum())
        self.assertEqual(page.selector.selected_cells(), selected)
        control.click()
        APP.processEvents()
        self.assertEqual(bar.maximum(), 0,
                         f"viewport={page.interactive_scroll.viewport().width()} grid={page.plot_host.width()} "
                         f"minimum={page.plot_host.minimumSizeHint().width()} columns={page.columns.currentText()} "
                         f"checked={control.isChecked()} enabled={control.isEnabled()} "
                         f"minwidth={page.plot_host.minimumWidth()} resizable={page.interactive_scroll.widgetResizable()}")
        for widget, before in zip(page.plot_widgets, curves):
            self.assertEqual(tuple(widget.listDataItems()), before)
        pd.testing.assert_frame_equal(child.raw_model.frame(), raw.astype(str))

    def test_expand_workbook_trend_and_bias_retains_curves_and_compact_docking(self):
        count = 40
        raw = pd.DataFrame({
            "Wafer ID": [f"Wafer-2026-VERY-LONG-IDENTITY-{i // 6:03}" for i in range(6 * count)],
            "Lot ID": ["L001"] * (6 * count), "PAD Name": ["ARRAY"] * (6 * count),
            "Die Seq": [1, 2, 3, 4, 5, 6] * count, "CD": list(range(1, 6 * count + 1)),
        })
        parent = self.parent
        parent.set_reference_frame(pd.DataFrame({"CD Reference": 2 * raw.CD}))
        parent.set_raw_frame(raw)
        parent.percent_bias.setChecked(True)
        parent.run_analysis()
        parent.resize(1600, 1000)
        parent.show()
        APP.processEvents()
        control = parent.results_tabs.cornerWidget().findChild(QCheckBox, "expandWaferIds") if parent.results_tabs.cornerWidget() else None
        self.assertIsNotNone(control, "All parameter plots needs an Expand wafer IDs checkbox")
        group = parent.plot_groups["CD"]
        area = group["plot_area"]
        layout = area.saveState()
        curves = {name: tuple(plot.listDataItems()) for name, plot in group["plots"].items()}
        match_width = group["plots"]["match"].width()
        control.click()
        APP.processEvents()
        scroll = group["plot_scroll"]
        self.assertGreater(scroll.horizontalScrollBar().maximum(), 0)
        self.assertEqual(group["plots"]["match"].width(), match_width)
        for name in ("trend", "bias", "bias-percent"):
            plot = group["plots"][name]
            self.assertEqual(tuple(plot.listDataItems()), curves[name])
            self.assertEqual([label for _, label in plot.getAxis("bottom")._tickLevels[0]],
                             [label for _, _, label in plot.getAxis("bottom").spans])
        control.click()
        APP.processEvents()
        self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
        self.assertEqual(area.saveState(), layout)
        for name, plot in group["plots"].items():
            self.assertEqual(tuple(plot.listDataItems()), curves[name])
        pd.testing.assert_frame_equal(parent.raw_model.frame(), raw.astype(str))

    def test_expand_choices_save_independently_and_old_wkb_defaults_are_compact(self):
        parent = self.parent
        first = parent.open_correlation_workspace()
        menu = parent.correlation_button.menu()
        menu.popup(parent.correlation_button.mapToGlobal(QPoint(0, parent.correlation_button.height())))
        APP.processEvents()
        action = next(action for action in menu.actions() if action.text() == "New window…")
        menu.hide()
        with patch.object(QInputDialog, "getText", return_value=("Second", True)):
            action.trigger()
        second = next(window for window in APP.topLevelWidgets() if "Second" in window.windowTitle())
        # New windows are blank manual editors; this expansion comparison
        # explicitly asks for a Workbook copy before drawing both windows.
        self.assertFalse(second.copy_from_wkb_action.isChecked())
        second.copy_from_wkb_action.trigger()
        for child in (first, second):
            self.draw_child(child)
        parent.expand_wafer_ids.setChecked(True)
        first.sequence_page.expand_wafer_ids.setChecked(True)
        self.assertFalse(second.sequence_page.expand_wafer_ids.isChecked())
        with TemporaryDirectory() as folder:
            path = Path(folder) / "expanded.wkb"
            parent.save_workbook(path)
            parent.load_workbook(path)
            self.assertTrue(parent.expand_wafer_ids.isChecked())
            first = parent.open_correlation_workspace()
            parent.correlation_button.click()
            second = next(window for window in APP.topLevelWidgets() if "Second" in window.windowTitle())
            self.assertTrue(first.sequence_page.expand_wafer_ids.isChecked())
            self.assertFalse(second.sequence_page.expand_wafer_ids.isChecked())
            self.assertTrue(first.sequence_page.ready)
            self.assertTrue(second.sequence_page.ready)
            legacy = parent.workspace_snapshot()
            legacy.states["match_ui"].pop("expand_wafer_ids")
            for scope, saved in legacy.states.items():
                if scope.startswith("correlation"):
                    saved["ui"]["pages"]["sequence_page"]["controls"].pop("expand_wafer_ids")
            parent.restore_workspace(legacy)
            self.assertFalse(parent.expand_wafer_ids.isChecked())
            first = parent.open_correlation_workspace()
            self.assertFalse(first.sequence_page.expand_wafer_ids.isChecked())

    def test_reopened_linked_trend_keeps_boxes_when_classification_is_enabled(self):
        parent = self.parent
        child = parent.open_correlation_workspace()
        self.draw_child(child)
        with TemporaryDirectory() as folder:
            path = Path(folder) / "classification-enabled.wkb"
            parent.save_workbook(path)
            self.close(child)
            parent.group_controls.mark_enabled.setChecked(True)
            parent.group_controls.apply_button.click()
            parent.save_workbook(path)
            parent.load_workbook(path)
            page = parent.open_correlation_workspace().sequence_page
            self.assertTrue(page.ready, page.status.text())
            self.assertEqual({text for widget in page.plot_widgets for _, _, text in widget._wafer_axis.spans}, {"Old"})
            self.assertTrue(page.selector.selected_cells())
            parent.save_workbook(path)
            parent.load_workbook(path)
            page = parent.open_correlation_workspace().sequence_page
            self.assertTrue(page.ready, page.status.text())
            self.assertTrue(page.selector.selected_cells())

    def test_current_groups_preserve_filtered_flags_and_child_full_data_scope(self):
        parent = self.parent
        parent.group_controls.restore({"enabled": True, "mark_enabled": False,
                                       "head_names": {"0": "Head A", "1": "Head B"}},
                                      pd.DataFrame({"TestFlag": [0] * 6 + [1] * 6}))
        parent.run_analysis()
        failures = []
        def exclude_second():
            dialog = APP.activeModalWidget()
            try:
                dialog.findChild(QLineEdit, "dataSelectionSearch").setText("W002")
                next(button for button in dialog.findChildren(QPushButton) if button.text() == "Uncheck Visible").click()
                dialog.accept()
            except Exception as error:
                failures.append(error)
                dialog.reject()
        QTimer.singleShot(0, exclude_second)
        parent.data_selection_action.trigger()
        self.assertEqual(failures, [])
        grouping = parent.workspace_snapshot().states["match"]["grouping_state"]
        child = parent.open_correlation_workspace()
        page = self.draw_child(child)
        self.assertEqual(len(child.raw_model.frame()), 6)
        self.assertEqual({label for widget in page.plot_widgets for _, _, label in widget._wafer_axis.spans}, {"Head A"})
        child.full_data_action.trigger()
        # Full data restores the tables, while preserving local sidebar
        # choices. Explicitly select both newly available source wafers.
        for tree in (child.reference_wafer_list, child.wafer_list):
            for index in range(tree.topLevelItemCount()):
                tree.topLevelItem(index).setCheckState(0, Qt.CheckState.Checked)
        page = self.draw_child(child)
        self.assertEqual(len(child.raw_model.frame()), 12)
        self.assertEqual({label for widget in page.plot_widgets for _, _, label in widget._wafer_axis.spans}, {"Head A", "Head B"})
        self.assertTrue(all(len(curve.yData) == 12 for widget in page.plot_widgets for curve in widget.listDataItems()))
        with TemporaryDirectory() as folder:
            path = Path(folder) / "group-full-scope.wkb"
            parent.save_workbook(path)
            parent.load_workbook(path)
            child = parent.open_correlation_workspace()
            self.assertTrue(child.full_data_action.isChecked())
            page = child.sequence_page
            self.assertTrue(page.ready, page.status.text())
            self.assertTrue(all(len(curve.yData) == 12 for widget in page.plot_widgets for curve in widget.listDataItems()))
            pd.testing.assert_frame_equal(child.raw_model.frame(), self.raw)
            self.assertEqual(parent.workspace_snapshot().states["match"]["grouping_state"], grouping)
            parent.save_workbook(path)
            parent.load_workbook(path)
            page = parent.open_correlation_workspace().sequence_page
            self.assertTrue(page.ready, page.status.text())
            self.assertTrue(page.selector.selected_cells())
