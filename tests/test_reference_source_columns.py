"""Reference sources retain their own headers, values and aligned Raw identities."""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pandas as pd
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from metrology_app.correlation_window import CorrelationWindow
from metrology_app.matching import ParameterMapping
from metrology_app.matching_window import MatchingWindow
from metrology_app.match_groups import row_ids
from metrology_app.workspace_store import save_workspace

APP = QApplication.instance() or QApplication([])


class ReferenceSourceColumnTests(unittest.TestCase):
    def setUp(self):
        self.window = CorrelationWindow()
        self.raw = pd.DataFrame({"Wafer ID": ["W001"] * 3, "Lot ID": ["L001"] * 3,
                                 "PAD Name": ["ARRAY"] * 3, "Die Seq": ["001", "003", "008"],
                                 "OCD_DEPTH1_1": ["1.000", "2.000", "3.000"],
                                 "OCD_DEPTH1_2": ["3.000", "5.000", "7.000"]})
        self.reference = pd.DataFrame({"OCD_DEPTH1": ["2.000000000001", "4.000", "6.000"],
                                       "W_Recess_Reference": ["8.500", "9.500", "10.500"],
                                       "CINDEX": ["0.700", "0.800", "0.900"]})

    def tearDown(self):
        self.window.document.force_close = True
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def test_ref_data_uses_raw_identity_and_complete_original_reference_columns_not_mapping_names(self):
        expected = pd.concat([self.raw.iloc[:, :4], self.reference], axis=1)
        reference = self.reference.assign(**{"Wafer ID": ["Wrong wafer"] * 3,
                                             "Lot ID": ["Wrong lot"] * 3,
                                             "PAD Name": ["Wrong pad"] * 3,
                                             "Die Seq": ["900", "901", "902"]})
        for mappings in (
            (ParameterMapping("OCD_DEPTH1 2", "OCD_DEPTH1", "OCD_DEPTH1_2"),),
            (ParameterMapping("First calibration", "OCD_DEPTH1", "OCD_DEPTH1_1"),
             ParameterMapping("Second calibration", "OCD_DEPTH1", "OCD_DEPTH1_2")),
            (),
        ):
            with self.subTest(mappings=mappings):
                self.window.set_sources(reference, self.raw, mappings)
                pd.testing.assert_frame_equal(self.window.reference_model.document_frame(), expected)
                pd.testing.assert_frame_equal(self.window.raw_model.document_frame(), self.raw)
                self.assertEqual(self.window.selected(self.window.reference_parameter_list), ["OCD_DEPTH1", "W_Recess_Reference"])
                self.assertIn("CINDEX", [self.window.reference_parameter_list.topLevelItem(i).text(0)
                                        for i in range(self.window.reference_parameter_list.topLevelItemCount())])

    def test_original_reference_names_keep_workbook_head_classification(self):
        parent = MatchingWindow()
        try:
            parent.set_reference_frame(self.reference)
            parent.set_raw_frame(self.raw)
            parent.mapping_table.item(0, 1).setText("OCD_DEPTH1 2")
            parent.mapping_table.cellWidget(0, 3).setCurrentText("OCD_DEPTH1_2")
            parent.mapping_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
            parent.group_controls.restore({"enabled": True, "mark_enabled": False,
                                           "head_names": {"0": "Head A", "1": "Head B"}},
                                          pd.DataFrame({"TestFlag": [0, 0, 1]}))
            parent.run_analysis()
            child = parent.open_correlation_workspace()
            page = child.sequence_page
            page.selector.selectAll()
            page.draw_plot()
            self.assertTrue(page.ready, page.status.text())
            self.assertEqual({label for plot in page.plot_widgets for _, _, label in plot._wafer_axis.spans},
                             {"Head A", "Head B"})
            pd.testing.assert_frame_equal(child.reference_model.document_frame(),
                                          pd.concat([self.raw.iloc[:, :4], self.reference], axis=1))
            pd.testing.assert_frame_equal(child.raw_model.document_frame(), self.raw)
        finally:
            parent.document.force_close = True
            parent.close()
            parent.deleteLater()
            APP.processEvents()

    def test_legacy_linked_reference_aliases_reopen_as_source_names_without_losing_draw_choices(self):
        parent = MatchingWindow()
        restored = None
        try:
            parent.set_reference_frame(self.reference)
            parent.set_raw_frame(self.raw)
            alias = "OCD_DEPTH1_2"  # Also a real Raw column: never rename its Raw source choice.
            parent.mapping_table.item(0, 1).setText(alias)
            parent.mapping_table.cellWidget(0, 3).setCurrentText("OCD_DEPTH1_2")
            parent.mapping_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
            parent.run_analysis()
            child = parent.open_correlation_workspace()
            snapshot = parent.workspace_snapshot(include_drafts=True)
            scope = next(name for name in snapshot.states if name.startswith("correlation."))
            saved = snapshot.states[scope]
            saved["data_override"] = False
            ui = saved["ui"]
            ui["copy_from_wkb"] = True
            selection = ui["selection"]
            selection.pop("reference_column_names", None)
            ref_key = selection["reference"]["wafers"][0]
            raw_key = selection["raw"]["wafers"][0]
            selection["reference"]["metrics"] = [alias, "W_Recess_Reference"]
            selection["trend_draw"] = {"enabled": True,
                "cells": [["Reference", ref_key, alias], ["Raw Data", raw_key, alias]]}
            selection["correlation_draw"] = {"enabled": True,
                "cells": [["Reference", ref_key, alias], ["Reference", ref_key, "W_Recess_Reference"]]}
            ui["pages"]["sequence_page"].update({"pending_draw": False, "parameter_filter": alias,
                "boxes": [[["Reference", ref_key], alias], [["Raw Data", raw_key], alias]],
                "source_overlay": [{"source": "Reference", "metric": alias,
                                    "comparisons": [{"source": "Raw Data", "metric": alias}]}]})
            ui["pages"]["correlation_page"].update({"pending_draw": False,
                "boxes": [[["Reference", ref_key], alias], [["Reference", ref_key], "W_Recess_Reference"]],
                "axis_directions": [{"sources": ["Reference"], "x": alias, "y": "W_Recess_Reference"}]})
            snapshot.frames[f"{scope}.reference_data"] = child.reference_model.document_frame().rename(columns={"OCD_DEPTH1": alias})
            with TemporaryDirectory() as folder:
                path = Path(folder) / "legacy-reference-alias.wkb"
                save_workspace(path, snapshot)
                restored = MatchingWindow()
                restored.load_workbook(path)
                reopened = restored.open_correlation_workspace()
                expected = pd.concat([self.raw.iloc[:, :4], self.reference], axis=1)
                pd.testing.assert_frame_equal(reopened.reference_model.document_frame(), expected)
                pd.testing.assert_frame_equal(reopened.raw_model.document_frame(), self.raw)
                page = reopened.sequence_page
                self.assertTrue(page.ready, page.status.text())
                self.assertEqual(page.selector.selected_cells(),
                                 {(("Reference", ref_key), "OCD_DEPTH1"), (("Raw Data", raw_key), alias)})
                self.assertEqual(page.source_overlay, {("Reference", "OCD_DEPTH1"): [("Raw Data", alias)]})
                self.assertTrue(page.parameter_filter.matches(("OCD_DEPTH1",)))
                self.assertTrue(page.parameter_filter.matches((alias,)))
                self.assertEqual(reopened.correlation_page.axis_state(),
                                 [{"sources": ["Reference"], "x": "OCD_DEPTH1", "y": "W_Recess_Reference"}])
                restored.save_workbook(path)
                restored.document.force_close = True
                restored.close()
                restored.deleteLater()
                APP.processEvents()
                restored = MatchingWindow()
                restored.load_workbook(path)
                reopened = restored.open_correlation_workspace()
                pd.testing.assert_frame_equal(reopened.reference_model.document_frame(), expected)
                self.assertTrue(reopened.sequence_page.ready)
                self.assertEqual(reopened.sequence_page.selector.selected_cells(),
                                 {(("Reference", ref_key), "OCD_DEPTH1"), (("Raw Data", raw_key), alias)})
        finally:
            if restored is not None:
                restored.document.force_close = True
                restored.close()
                restored.deleteLater()
            parent.document.force_close = True
            parent.close()
            parent.deleteLater()
            APP.processEvents()

    def test_data_selection_and_full_data_keep_reference_rows_aligned_with_raw(self):
        parent = MatchingWindow()
        restored = None
        try:
            parent.set_reference_frame(self.reference)
            parent.set_raw_frame(self.raw)
            parent.mapping_table.item(0, 1).setText("OCD_DEPTH1 2")
            parent.mapping_table.cellWidget(0, 3).setCurrentText("OCD_DEPTH1_2")
            parent.mapping_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
            records = [{"key": key, "id": f"record{i}"} for i, key in enumerate(row_ids(self.raw))]
            parent.group_controls.restore({"enabled": False, "mark_enabled": False,
                                           "data_selection": {"records": records, "excluded": ["record1"]}})
            parent.run_analysis()
            child = parent.open_correlation_workspace()
            expected = pd.concat([self.raw.iloc[[0, 2], :4], self.reference.iloc[[0, 2]]], axis=1).reset_index(drop=True)
            pd.testing.assert_frame_equal(child.reference_model.document_frame(), expected)
            pd.testing.assert_frame_equal(child.raw_model.document_frame(), self.raw.iloc[[0, 2]].reset_index(drop=True))
            child.full_data_action.trigger()
            full = pd.concat([self.raw.iloc[:, :4], self.reference], axis=1)
            pd.testing.assert_frame_equal(child.reference_model.document_frame(), full)
            pd.testing.assert_frame_equal(child.raw_model.document_frame(), self.raw)
            child.workbook_selection_action.trigger()
            pd.testing.assert_frame_equal(child.reference_model.document_frame(), expected)
            with TemporaryDirectory() as folder:
                path = Path(folder) / "aligned-reference.wkb"
                parent.save_workbook(path)
                restored = MatchingWindow()
                restored.load_workbook(path)
                reopened = restored.open_correlation_workspace()
                pd.testing.assert_frame_equal(reopened.reference_model.document_frame(), expected)
                pd.testing.assert_frame_equal(reopened.raw_model.document_frame(), self.raw.iloc[[0, 2]].reset_index(drop=True))
            pd.testing.assert_frame_equal(parent.reference_model.document_frame(), self.reference)
            pd.testing.assert_frame_equal(parent.raw_model.document_frame(), self.raw)
        finally:
            if restored is not None:
                restored.document.force_close = True
                restored.close()
                restored.deleteLater()
            parent.document.force_close = True
            parent.close()
            parent.deleteLater()
            APP.processEvents()
