"""Plot captions are presentation choices, never measurement identities."""
import os
from pathlib import Path
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from metrology_app.matching_window import MatchingWindow
from metrology_app.settings import get_settings, save_settings

APP = QApplication.instance() or QApplication([])


class PlotLabelTests(unittest.TestCase):
    def setUp(self):
        previous = get_settings()
        save_settings({"trend_overlay": {}, "trend_source_overlay": None})
        self.addCleanup(save_settings, previous)
        self.window = MatchingWindow()
        self.addCleanup(APP.processEvents)
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.close, self.window)
        self.window.document.timer.stop()
        self.window.match_type.setCurrentText("NOVA")
        self.raw = pd.DataFrame({
            "Wafer ID": ["W001"] * 18,
            "PAD Name": ["ARRAY"] * 9 + ["CELL"] * 9,
            "Lot ID": ["L001"] * 9 + ["L002"] * 9,
            "Die Seq": list(range(1, 10)) * 2,
            "FIELD X": [-1, 0, 1] * 6,
            "FIELD Y": [-1] * 3 + [0] * 3 + [1] * 3 + [-1] * 3 + [0] * 3 + [1] * 3,
            "CD Raw": [f"{value:.3f}" for value in range(1, 10)] * 2,
        }).astype(str)
        self.window.set_reference_frame(pd.DataFrame({"CD Reference": list(range(3, 20, 2)) * 2}))
        self.window.set_raw_frame(self.raw)
        self.window.mapping_table.item(0, 1).setText("Depth")
        self.window.mapping_table.cellWidget(0, 3).setCurrentText("CD Raw")
        self.window.mapping_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        self.window.run_analysis()

    @staticmethod
    def close(window):
        window.document.force_close = True
        window.close()

    def child(self, kind):
        child = (self.window.open_correlation_workspace() if kind == "correlation"
                 else self.window.open_stage_workspace("preview"))
        child.document.timer.stop()
        return child

    def test_parameter_mapping_names_title_match_and_trend_with_matching_y_label(self):
        block = self.window.plot_groups["Depth"]
        self.assertEqual(block["match_title"].text(), "Depth")
        self.assertEqual(block["plots"]["trend"].title_label.text(), "Depth")
        self.assertEqual(block["plots"]["trend"].getAxis("left").labelText, "Depth")
        child = self.child("correlation")
        page = child.sequence_page
        page.selector.selectAll()
        page.draw_plot()
        self.assertTrue(page.ready, page.status.text())
        self.assertEqual(page.plot_widgets[0].getAxis("left").labelText, "Reference · CD Reference")
        self.assertEqual(page.plot_widgets[1].getAxis("left").labelText, "Raw Data · CD Raw")
        page.ensure_export_figure()
        for axis in page.figure.axes:
            if axis.axison:
                self.assertEqual(axis.get_ylabel(), axis.get_title())
        pd.testing.assert_frame_equal(self.window.raw_model.frame(), self.raw)

    def test_original_order_label_switches_keep_measurements_and_drawn_values(self):
        window = self.window
        correlation = self.child("correlation")
        trend = correlation.sequence_page
        trend.selector.selectAll()
        trend.draw_plot()
        maps = self.child("map")
        for index in range(maps.parameter_list.topLevelItemCount()):
            item = maps.parameter_list.topLevelItem(index)
            if item.text(0) == "Depth":
                item.setCheckState(0, Qt.CheckState.Checked)
        maps.update_plan()
        map_page, radius = maps.plot_page, maps.radius_page
        for page in (map_page, radius):
            page.selector.selectAll()
        map_page.draw_maps()
        deadline = time.monotonic() + 30
        while map_page.worker is not None and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(.01)
        self.assertIsNotNone(map_page.result, map_page.empty.text() + map_page.status.text())
        radius.draw_plot()
        self.assertTrue(radius.ready, radius.status.text())
        before = window.workspace_snapshot(include_drafts=True)
        result = window.result
        widgets = list(trend.plot_widgets)
        axis_spans = [[(start, end) for start, end, _ in widget._wafer_axis.spans] for widget in widgets]
        arrays = [item.getData() for widget in widgets for item in widget.listDataItems()]
        surfaces = [scene.get("surface") for scene in map_page.result["scenes"]]
        offsets = [axis.collections[0].get_offsets().copy() for axis in radius.figure.axes if axis.axison]
        spans = window.plot_groups["Depth"]["plots"]["trend"].getAxis("bottom").spans
        self.assertEqual([text for _, _, text in spans], ["W001\nLOT: L001\nPAD: ARRAY", "W001\nLOT: L002\nPAD: CELL"])
        for widget in widgets:
            self.assertEqual({text for _, _, text in widget._wafer_axis.spans},
                             {"W001\nLOT: L001\nPAD: ARRAY", "W001\nLOT: L002\nPAD: CELL"})
        self.assertEqual([plot.axes._wafer_title_details[0].get_text() for plot, _ in map_page.artists],
                         ["W001 · PAD: ARRAY · LOT: L001", "W001 · PAD: CELL · LOT: L002"])
        self.assertEqual([axis._wafer_title_details[0].get_text() for axis in radius.figure.axes if axis.axison],
                         ["W001 · PAD: ARRAY · LOT: L001", "W001 · PAD: CELL · LOT: L002"])
        trend.ensure_export_figure()
        self.assertTrue(all("LOT: " in text.get_text() and "PAD: " in text.get_text()
                            for axis in trend.figure.axes if axis.axison
                            for text in axis._wafer_group_labels if text.get_visible()))
        for name in ("trend", "map", "radius"):
            for field in ("pad", "lot"):
                window.plot_label_checks[name][field].click()
        APP.processEvents()
        self.assertIs(window.result, result)
        self.assertEqual(trend.plot_widgets, widgets)
        for widget, ranges in zip(widgets, axis_spans):
            self.assertEqual([(start, end) for start, end, _ in widget._wafer_axis.spans], ranges)
            self.assertEqual({text for _, _, text in widget._wafer_axis.spans}, {"W001"})
        self.assertEqual([text for _, _, text in window.plot_groups["Depth"]["plots"]["trend"].getAxis("bottom").spans], ["W001", "W001"])
        self.assertEqual([plot.axes._wafer_title_details[0].get_text() for plot, _ in map_page.artists], ["W001", "W001"])
        self.assertEqual([axis._wafer_title_details[0].get_text() for axis in radius.figure.axes if axis.axison], ["W001", "W001"])
        for old, scene in zip(surfaces, map_page.result["scenes"]):
            self.assertIs(old, scene.get("surface"))
        for old, axis in zip(offsets, (axis for axis in radius.figure.axes if axis.axison)):
            np.testing.assert_array_equal(old, axis.collections[0].get_offsets())
        for old, item in zip(arrays, (item for widget in widgets for item in widget.listDataItems())):
            for values, current in zip(old, item.getData()):
                np.testing.assert_array_equal(values, current)
        after = window.workspace_snapshot(include_drafts=True)
        self.assertEqual(before.states["match"]["grouping_state"], after.states["match"]["grouping_state"])
        for name, frame in before.frames.items():
            pd.testing.assert_frame_equal(frame, after.frames[name])
        self.assertEqual(map_page.selector.selected_cells(), map_page.drawn_cells)
        trend.ensure_export_figure()
        self.assertTrue(all(text.get_text() == "W001" for axis in trend.figure.axes if axis.axison
                            for text in axis._wafer_group_labels if text.get_visible()))
        map_page.scale_bar.click()
        map_page.apply_plot_style()
        self.assertEqual([plot.axes._wafer_title_details[0].get_text() for plot, _ in map_page.artists], ["W001", "W001"])

    def test_group_show_wafer_switches_only_wafer_captions_not_group_labels(self):
        window = self.window
        window.group_controls.restore({"enabled": True, "mark_enabled": False,
                                       "head_names": {"0": "Optical A"},
                                       "show_wafer_groups": ["All:0"]},
                                      pd.DataFrame({"TestFlag": [0] * 18}))
        window.run_analysis()
        block = window.group_plot_page.plot_groups[("All:0", "Depth")]
        plot = block["plots"]["trend"]
        child = self.child("correlation")
        child.sequence_page.selector.selectAll()
        child.sequence_page.draw_plot()
        group_labels = list(plot._group_tick_data[1])
        curves = list(plot.listDataItems())
        boundaries = [line.value() for line in plot._group_boundaries]
        data = window.result.group_series("Depth", trend=True).copy()
        wafer_list = block["note"].toolTip()
        plot.setXRange(2, 9, padding=0)
        view = plot.getViewBox().viewRange()
        self.assertEqual([label for _, _, label in plot._group_tick_data[2]],
                         ["W001\nLOT: L001\nPAD: ARRAY", "W001\nLOT: L002\nPAD: CELL"])
        window.plot_label_checks["trend"]["pad"].click()
        self.assertEqual([label for _, _, label in plot._group_tick_data[2]],
                         ["W001\nLOT: L001", "W001\nLOT: L002"])
        self.assertEqual(plot._group_tick_data[1], group_labels)
        self.assertEqual([line.value() for line in plot._group_boundaries], boundaries)
        self.assertEqual(plot.listDataItems(), curves)
        np.testing.assert_allclose(plot.getViewBox().viewRange(), view)
        self.assertEqual(block["note"].toolTip(), wafer_list)
        self.assertEqual({text for widget in child.sequence_page.plot_widgets
                          for _, _, text in widget._wafer_axis.spans}, {"Optical A"})
        pd.testing.assert_frame_equal(window.result.group_series("Depth", trend=True), data)
        window.plot_label_checks["trend"]["lot"].click()
        self.assertEqual([label for _, _, label in plot._group_tick_data[2]], ["W001", "W001"])
        window.plot_label_checks["trend"]["pad"].click()
        self.assertEqual([label for _, _, label in plot._group_tick_data[2]], ["W001\nPAD: ARRAY", "W001\nPAD: CELL"])
        self.assertEqual(plot._group_tick_data[1], group_labels)

    def test_workbook_restores_label_choices_and_old_workbooks_default_to_full_captions(self):
        window = self.window
        window.plot_label_checks["trend"]["lot"].click()
        window.plot_label_checks["map"]["pad"].click()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "captions.wkb"
            window.save_workbook(path)
            restored = MatchingWindow()
            self.addCleanup(restored.deleteLater)
            self.addCleanup(self.close, restored)
            restored.load_workbook(path)
            self.assertFalse(restored.plot_label_checks["trend"]["lot"].isChecked())
            self.assertFalse(restored.plot_label_checks["map"]["pad"].isChecked())
            self.assertTrue(restored.plot_label_checks["radius"]["lot"].isChecked())
            child = restored.open_correlation_workspace()
            child.sequence_page.selector.selectAll()
            child.sequence_page.draw_plot()
            self.assertEqual(child.sequence_page.plot_widgets[0]._wafer_axis.spans[0][2], "W001\nPAD: ARRAY")
            snapshot = restored.workspace_snapshot()
            snapshot.states["match_ui"].pop("plot_labels")
            restored.restore_workspace(snapshot)
            self.assertTrue(all(box.isChecked() for fields in restored.plot_label_checks.values() for box in fields.values()))
            pd.testing.assert_frame_equal(restored.raw_model.frame(), self.raw)

    def test_invalid_display_settings_do_not_replace_the_open_workbook(self):
        snapshot = self.window.workspace_snapshot()
        snapshot.states["match_ui"]["plot_labels"] = {"trend": {"pad": "false"}}
        before = self.window.raw_model.frame().copy()
        with self.assertRaisesRegex(ValueError, "plot label"):
            self.window.restore_workspace(snapshot)
        pd.testing.assert_frame_equal(self.window.raw_model.frame(), before)
