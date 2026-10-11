"""Source-order presentation through analysis, visible controls and WKB storage."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from copy import deepcopy

import pandas as pd

from metrology_app.match_groups import GroupPlan, participation_ids, row_ids
from metrology_app.matching_window import MatchingWindow
from PyQt6.QtWidgets import QApplication


APP = QApplication.instance() or QApplication([])


def interleaved_sources():
    raw = pd.DataFrame({
        "Wafer ID": ["W1", "W2", "W1", "W1", "W2", "W1", "W1", "W3"],
        "Lot ID": ["L1", "L3", "L2", "L1", "L3", "L2", "L1", "L4"],
        "PAD Name": ["ARRAY", "ARRAY", "ARRAY", "CELL", "ARRAY", "ARRAY", "ARRAY", "ARRAY"],
        "Die Seq": ["4", "5", "9", "2", "1", "2", "1", "8"],
        "P": ["1.000", "2.000", "3.000", "4.000", "5.000", "6.000", "7.000", "8.000"],
    })
    reference = pd.DataFrame({"P Reference": [3., 5., 7., 9., 11., 13., 15., 17.]})
    return reference, raw


class TrendOrderTests(unittest.TestCase):
    def test_original_wafer_order_collects_lot_and_pad_in_first_source_order(self):
        _, raw = interleaved_sources()
        original = raw.copy(deep=True)
        plan = GroupPlan(raw, state={"trend_order": "wafers"})
        self.assertEqual(
            [row for span in plan.trend_spans() for row in span["rows"]],
            [0, 6, 1, 4, 2, 5, 3, 7],
        )
        self.assertFalse(plan.enabled)
        self.assertEqual(plan.included_rows, tuple(range(8)))
        pd.testing.assert_frame_equal(raw, original)

    def test_excluding_first_rows_does_not_change_original_wafer_order(self):
        _, raw = interleaved_sources()
        identifiers = participation_ids(raw, None)
        selection = {"records": [{"key": key, "id": identifier}
                                 for key, identifier in zip(row_ids(raw), identifiers)],
                     "excluded": [identifiers[0]]}
        plan = GroupPlan(raw, state={"trend_order": "wafers", "data_selection": selection})
        self.assertEqual([row for span in plan.trend_spans() for row in span["rows"]],
                         [6, 1, 4, 2, 5, 3, 7])
        self.assertEqual(plan.included_rows, (1, 2, 3, 4, 5, 6, 7))

    def test_missing_wafer_column_falls_back_to_original_rows(self):
        plan = GroupPlan(pd.DataFrame({"Lot ID": ["L2", "L1", "L2"], "P": [1, 2, 3]}),
                         state={"trend_order": "wafers"})
        self.assertEqual([row for span in plan.trend_spans() for row in span["rows"]], [0, 1, 2])


class TrendOrderWindowTests(unittest.TestCase):
    def setUp(self):
        self.window = MatchingWindow()
        self.window.document.confirm_close = lambda: True
        self.reference, self.raw = interleaved_sources()
        self.window.set_reference_frame(self.reference)
        self.window.set_raw_frame(self.raw)
        self.window.run_analysis()
        self.reference = self.window.reference_model.frame().copy(deep=True)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def test_source_orders_remain_available_when_classification_changes(self):
        controls = self.window.group_controls
        order = controls.order
        self.assertEqual([order.itemText(i) for i in range(order.count())],
                         ["Original row order", "Original Wafer order"])
        order.setCurrentIndex(order.findData("wafers"))
        controls.enabled.setChecked(True)
        self.assertEqual([order.itemText(i) for i in range(order.count())],
                         ["Group → Wafer → Die Seq", "Original row order", "Original Wafer order"])
        self.assertEqual(order.currentData(), "wafers")
        controls.enabled.setChecked(False)
        self.assertEqual([order.itemData(i) for i in range(order.count())], ["original", "wafers"])
        self.assertEqual(order.currentData(), "wafers")
        controls.apply_button.click()
        self.assertEqual(self.window.current_workbook().grouping_state["applied"]["trend_order"], "wafers")

    def test_ungrouped_trend_and_bias_collect_identities_without_changing_sources(self):
        window = self.window
        before = window.result.series("P")
        card = window.result.card("P")
        controls = window.group_controls
        controls.order.setCurrentIndex(controls.order.findData("wafers"))
        controls.apply_button.click()
        trend = window.plot_groups["P"]["plots"]["trend"]
        reference = next(curve for curve in trend.listDataItems() if curve.name() != "PMISH")
        self.assertEqual(reference.yData.tolist(), [3., 15., 5., 11., 7., 13., 9., 17.])
        self.assertEqual([(start, end) for start, end, _ in trend.getAxis("bottom").spans],
                         [(.5, 2.5), (2.5, 4.5), (4.5, 6.5), (6.5, 7.5), (7.5, 8.5)])
        bias = window.plot_groups["P"]["plots"]["bias"].listDataItems()[0]
        self.assertEqual(bias.yData.tolist(), before["Bias"].iloc[[0, 6, 1, 4, 2, 5, 3, 7]].tolist())
        self.assertEqual(window.result.card("P"), card)
        pd.testing.assert_frame_equal(window.result.series("P"), before)
        pd.testing.assert_frame_equal(window.raw_model.frame(), self.raw)
        pd.testing.assert_frame_equal(window.reference_model.frame(), self.reference)
        controls.order.setCurrentIndex(controls.order.findData("original"))
        controls.apply_button.click()
        trend = window.plot_groups["P"]["plots"]["trend"]
        self.assertEqual(next(curve for curve in trend.listDataItems() if curve.name() != "PMISH").yData.tolist(),
                         [3., 5., 7., 9., 11., 13., 15., 17.])

    def test_linked_trend_preserves_original_rows_inside_each_wafer_identity(self):
        controls = self.window.group_controls
        controls.order.setCurrentIndex(controls.order.findData("wafers"))
        controls.apply_button.click()
        child = self.window.open_correlation_workspace()
        page = child.sequence_page
        child.tabs.setCurrentWidget(page)
        child.resize(1600, 850)
        child.show()
        page.selector.selectAll()
        page.draw_plot()
        APP.processEvents()
        self.assertTrue(page.ready, page.status.text())
        self.assertEqual([plot.listDataItems()[0].yData.tolist() for plot in page.plot_widgets],
                         [[3., 15., 5., 11., 7., 13., 9., 17.], [1., 7., 2., 5., 3., 6., 4., 8.]])
        for plot in page.plot_widgets:
            self.assertEqual([(start, end) for start, end, _ in plot._wafer_axis.spans],
                             [(-.5, 1.5), (1.5, 3.5), (3.5, 5.5), (5.5, 6.5), (6.5, 7.5)])
            self.assertEqual([label for _, _, label in plot._wafer_axis.spans],
                             [label for _, _, label in self.window.plot_groups["P"]["plots"]["trend"].getAxis("bottom").spans])
        pd.testing.assert_frame_equal(child.raw_model.frame(), self.raw)

    def test_reordering_redraws_nonconstant_bias_and_bias_percent(self):
        window = self.window
        window.set_reference_frame(pd.DataFrame({"P Reference": [3., 5., 8., 9., 12., 13., 14., 17.]}))
        window.percent_bias.setChecked(True)
        window.run_analysis()
        before = window.result.series("P")
        window.group_controls.order.setCurrentIndex(window.group_controls.order.findData("wafers"))
        window.group_controls.apply_button.click()
        for plot_name, column in (("bias", "Bias"), ("bias-percent", "Bias %")):
            curve = window.plot_groups["P"]["plots"][plot_name].listDataItems()[0]
            self.assertEqual(curve.yData.tolist(), before[column].iloc[[0, 6, 1, 4, 2, 5, 3, 7]].tolist())
        window.group_controls.order.setCurrentIndex(window.group_controls.order.findData("original"))
        window.group_controls.apply_button.click()
        for plot_name, column in (("bias", "Bias"), ("bias-percent", "Bias %")):
            curve = window.plot_groups["P"]["plots"][plot_name].listDataItems()[0]
            self.assertEqual(curve.yData.tolist(), before[column].tolist())

    def test_group_scopes_keep_classification_in_original_wafer_order(self):
        controls = self.window.group_controls
        controls.restore({"enabled": True, "mark_enabled": False, "trend_order": "wafers",
                          "head_names": {"0": "Head A", "1": "Head B"},
                          "show_wafer_groups": ["All:0", "All:1"]},
                         pd.DataFrame({"TestFlag": [0, 1, 0, 1, 1, 0, 0, 1]}))
        self.window.run_analysis()
        self.assertEqual(self.window.result.group_plan.group_keys, ("All:0", "All:1"))
        for key, values in (("All:0", [3., 15., 7., 13.]), ("All:1", [5., 11., 9., 17.])):
            block = self.window.group_plot_page.plot_groups[(key, "P")]
            trend = block["plots"]["trend"]
            curve = next(curve for curve in trend.listDataItems() if curve.name() != "PMISH")
            self.assertEqual(curve.yData.tolist(), values)
            self.assertTrue(trend._group_axis.isVisible())
            self.assertEqual({text for _, _, text in trend._group_tick_data[1]},
                             {"Head A" if key == "All:0" else "Head B"})
        pd.testing.assert_frame_equal(self.window.raw_model.frame(), self.raw)

    def test_selected_child_keeps_full_source_first_appearance_after_exclusion(self):
        controls = self.window.group_controls
        state = deepcopy(controls.state)
        state.pop("applied", None)
        state["trend_order"] = "wafers"
        state["data_selection"]["excluded"] = [state["data_selection"]["records"][0]["id"]]
        controls.restore(state)
        self.window.run_analysis()
        child = self.window.open_correlation_workspace()
        child.tabs.setCurrentWidget(child.sequence_page)
        child.sequence_page.selector.selectAll()
        child.sequence_page.draw_plot()
        APP.processEvents()
        self.assertEqual([plot.listDataItems()[0].yData.tolist() for plot in child.sequence_page.plot_widgets],
                         [[15., 5., 11., 7., 13., 9., 17.], [7., 2., 5., 3., 6., 4., 8.]])
        pd.testing.assert_frame_equal(child.raw_model.frame(), self.raw.iloc[1:].reset_index(drop=True))

    def test_wkb_round_trip_retains_wafer_order_and_linked_plot_choices(self):
        controls = self.window.group_controls
        controls.order.setCurrentIndex(controls.order.findData("wafers"))
        controls.apply_button.click()
        child = self.window.open_correlation_workspace()
        child.tabs.setCurrentWidget(child.sequence_page)
        child.sequence_page.selector.selectAll()
        child.sequence_page.draw_plot()
        APP.processEvents()
        expected = [[3., 15., 5., 11., 7., 13., 9., 17.], [1., 7., 2., 5., 3., 6., 4., 8.]]
        with TemporaryDirectory() as folder:
            path = Path(folder) / "wafer-order.wkb"
            for _ in range(2):
                self.window.save_workbook(path)
                self.window.load_workbook(path)
                self.assertEqual(self.window.group_controls.order.currentData(), "wafers")
                page = self.window.open_correlation_workspace().sequence_page
                self.assertTrue(page.ready, page.status.text())
                self.assertTrue(page.selector.selected_cells())
                self.assertEqual([plot.listDataItems()[0].yData.tolist() for plot in page.plot_widgets], expected)
                pd.testing.assert_frame_equal(self.window.raw_model.frame(), self.raw)

    def test_linked_original_row_order_does_not_collect_interleaved_identities(self):
        controls = self.window.group_controls
        controls.order.setCurrentIndex(controls.order.findData("original"))
        controls.apply_button.click()
        child = self.window.open_correlation_workspace()
        child.tabs.setCurrentWidget(child.sequence_page)
        child.sequence_page.selector.selectAll()
        child.sequence_page.draw_plot()
        APP.processEvents()
        self.assertEqual([plot.listDataItems()[0].yData.tolist() for plot in child.sequence_page.plot_widgets],
                         [[3., 5., 7., 9., 11., 13., 15., 17.], [1., 2., 3., 4., 5., 6., 7., 8.]])
