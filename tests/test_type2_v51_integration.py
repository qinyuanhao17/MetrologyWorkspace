"""Type2/Mark2 workflows retained when adopting v5.1.0 Spectra integration."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import pandas as pd
from openpyxl import Workbook
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from metrology_app.mark2 import import_excel
from metrology_app.mark2_plotting import HierarchyAxis
from metrology_app.matching import ParameterMapping
from metrology_app.matching_window import MatchingWindow
from metrology_app.sme_spectra import LoadResult
from tests.test_spectra_viewer import make_spectrum

APP = QApplication.instance() or QApplication([])
IDENTITY = ["Cur SME File Path", "Wafer ID", "Lot ID", "Tool SN", "PAD Name", "Die Seq", "FIELD X", "FIELD Y"]


def sources():
    spectra = tuple(make_spectrum(die, wafer=wafer) for wafer in ("W1", "W2") for die in (1, 2, 3))
    raw = pd.DataFrame([
        [f"C:/fixtures/{s.identity.wafer}_202610311000{s.identity.die_seq:02d}000.sme",
         s.identity.wafer, "L1", "A03-090", "P1", str(s.identity.die_seq), "-1", "5", f"{i + 1}.000"]
        for i, s in enumerate(spectra)], columns=[*IDENTITY, "CD"])
    ref = pd.DataFrame({"Ref Wafer": raw["Wafer ID"], "Ref Die": raw["Die Seq"],
                        "REF CD": [f"{2 * i + 3}.0000" for i in range(6)]}).iloc[[4, 2, 0, 3, 1]].reset_index(drop=True)
    config = {"identity_columns": IDENTITY, "columns": ["Product", "Wafer", "Die"],
              "selected": ["Product", "Die"], "order_mode": "hierarchy",
              "records": [{"identity": raw.iloc[i][IDENTITY].tolist(), "values": [product, label, raw.iloc[i]["Die Seq"]]}
                          for i, (product, label) in enumerate(zip(["A", "B", "A", "A", "B", "A"],
                                                                  ["Pool", "Pool", "Other", "Pool", "Other", "Other"]))]}
    return raw, ref, config, spectra


class Type2V51IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.raw, self.ref, self.config, self.spectra = sources()
        self.window = MatchingWindow()
        self.window.document.force_close = True
        self.addCleanup(self.close_window)
        self.window.apply_analysis_settings({"workbook_type": "type2"}, refresh=False)
        self.window.set_raw_frame(self.raw)
        self.window.set_reference_frame(self.ref)
        self.window.set_matching_keys({"reference": ["Ref Wafer", "Ref Die"], "raw": ["Wafer ID", "Die Seq"]})
        self.window._populate_mappings([ParameterMapping("CD", "REF CD", "CD")])
        self.window.group_controls.change("mark2", self.config)
        self.window.group_controls.mark2_enabled.setChecked(True)
        self.window.percent_bias.setChecked(True)
        self.window.run_analysis()

    def close_window(self):
        for child in tuple(self.window._stage_windows):
            child.document.force_close = True
            child.close()
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def open_spectra(self):
        viewer = self.window.open_spectra_workspace()
        viewer.apply_load_result(LoadResult(self.spectra, ()), replace=True)
        viewer.set_spectrum_checks({s.key: True for s in self.spectra})
        return viewer

    def test_single_tag_metrics_fit_across_wafers_draw_and_restore_wafer_choices(self):
        overall = self.window.result.card("CD")
        self.window._wafer_checked("CD", 0, True)
        wafer_choice = deepcopy(self.window._single_wafer_checks)
        combo = self.window.metrics_group_combo
        combo.setCurrentIndex(combo.findData("Product"))
        group = self.window.plot_groups["CD"]
        summary = group["wafer_summary"]
        self.assertEqual(summary["Wafer"].tolist(), ["A", "B"])
        self.assertEqual(summary["Valid pairs"].tolist(), [3, 2])
        np.testing.assert_allclose(summary["Slope"], [2, 2])
        np.testing.assert_allclose(summary["Intercept"], [1, 1])
        np.testing.assert_allclose(summary["R²"], [1, 1])
        self.assertIn("Mark2 · Product", group["wafer_model"].frame)
        self.window._wafer_checked("CD", 0, True)
        detail = group["wafer_details"]["A"]
        self.assertEqual(detail["source_raw"]["Wafer ID"].tolist(), ["W1", "W1", "W2", "W2"])
        self.assertEqual(len(detail["source_raw"]), 4)
        self.assertEqual(detail["result"].card("CD").valid_pairs, 3)
        for name in ("trend", "bias", "bias-percent"):
            self.assertIsInstance(detail["plots"][name].getAxis("bottom"), HierarchyAxis)
        self.assertTrue(detail["result"].series("CD")["Reference"].isna().any())
        self.assertEqual(self.window.result.card("CD"), overall)
        combo.setCurrentIndex(0)
        self.assertEqual(self.window._single_wafer_checks, wafer_choice)
        self.assertEqual(len(group["wafer_summary"]), 2)
        self.assertEqual(len(group["wafer_details"]), 1)
        combo.setCurrentIndex(combo.findData("Product"))
        self.assertTrue(group["wafer_model"].frame["Draw"].iloc[0])
        pd.testing.assert_frame_equal(self.window.raw_model.document_frame(), self.raw)
        pd.testing.assert_frame_equal(self.window.reference_model.document_frame(), self.ref)

    def test_custom_wafer_header_is_separate_and_group_preference_survives_save_recovery(self):
        with TemporaryDirectory() as directory:
            table = Workbook()
            sheet = table.active
            sheet.append([*IDENTITY, None, *self.config["columns"]])
            for record in self.config["records"]:
                sheet.append([*record["identity"], None, *record["values"]])
            path = Path(directory) / "labels.xlsx"
            table.save(path)
            imported = import_excel(path)
            self.window.group_controls.change("mark2", imported)
            self.window.run_analysis()
            combo = self.window.metrics_group_combo
            combo.setCurrentIndex(combo.findData("Wafer"))
            self.assertEqual(combo.currentText(), "Mark2 · Wafer")
            self.assertEqual(self.window.plot_groups["CD"]["wafer_summary"]["Wafer"].tolist(), ["Pool", "Other"])
            self.window._wafer_checked("CD", 0, True)
            saved = self.window.save_workbook(Path(directory) / "grouped.mwkb")
            reopened = MatchingWindow()
            reopened.document.force_close = True
            try:
                reopened.load_workbook(saved)
                self.assertEqual(reopened.metrics_group_combo.currentData(), "Wafer")
                self.assertEqual(reopened.metrics_group_combo.itemData(0), None)
                self.assertEqual(reopened.plot_groups["CD"]["wafer_summary"]["Wafer"].tolist(), ["Pool", "Other"])
                self.assertTrue(reopened.plot_groups["CD"]["wafer_model"].frame["Draw"].iloc[0])
                self.assertFalse(reopened.document.is_dirty())
                self.window.metrics_group_combo.setCurrentIndex(self.window.metrics_group_combo.findData("Product"))
                self.window.document.recovery_path = Path(directory) / "recovery.mwkb"
                self.window.document.write_recovery()
                reopened.document.recover(self.window.document.recovery_path)
                self.assertEqual(reopened.metrics_group_combo.currentData(), "Product")
                reopened.metrics_group_combo.setCurrentIndex(0)
                self.assertTrue(reopened.plot_groups["CD"]["wafer_summary"]["Wafer"].iloc[0].startswith("W1"))
            finally:
                reopened.close()
                reopened.deleteLater()

    def test_spectra_info_uses_id_aligned_reference_and_keeps_unmatched_raw(self):
        viewer = self.open_spectra()
        info = viewer.spectra_info()
        self.assertEqual(info.issues, ())
        self.assertEqual(info.source_rows, tuple(range(6)))
        self.assertEqual(info.with_flags["REF CD"].tolist(), ["3.0000", "5.0000", "7.0000", "9.0000", "11.0000", ""])
        self.assertEqual(info.with_flags["Ref Die"].tolist(), ["1", "2", "3", "1", "2", ""])
        window = viewer.open_spectra_info()
        self.assertEqual(window.problems, ())
        self.assertEqual(window.table_frame()["REF CD"].tolist(), info.with_flags["REF CD"].tolist())
        pd.testing.assert_frame_equal(self.window.reference_model.document_frame(), self.ref)

    def test_selection_script_and_copy_to_spectra_use_aligned_reference_filter_context(self):
        config = deepcopy(self.window.group_controls.state["data_selection"])
        config["excluded"] = [config["records"][i]["id"] for i in (1, 5)]
        config.update(view_filter_groups=[[{"column": "Reference / REF CD", "minimum": 8}]],
                      view_filter_row_bools=[[]], view_filter_group_bools=[], view_show="filtered",
                      view_search="", hide_excluded=True)
        for state in (self.window.group_controls.state, self.window.group_controls.state["applied"]):
            state["data_selection"] = deepcopy(config)
        self.window.group_controls.refresh()
        self.window.run_analysis(apply_groups=False)
        script = json.loads(self.window.selection_script())
        self.assertEqual([r["values"]["Reference / REF CD"] for r in script["records"]],
                         ["3.0000", "5.0000", "7.0000", "9.0000", "11.0000", ""])
        self.assertEqual([r["use"] for r in script["records"]], [True, False, True, True, True, False])
        viewer = self.open_spectra()
        self.assertTrue(viewer.copy_wkb_selection())
        self.assertEqual({s.key for s in viewer.checked_spectra()}, {self.spectra[i].key for i in (0, 2, 3, 4)})
        self.assertEqual(viewer._data_selection_view["filters"], config["view_filter_groups"])
        self.assertEqual(viewer.spectra_info().with_flags["REF CD"].tolist(), ["3.0000", "7.0000", "9.0000", "11.0000"])

    def test_reference_more_rows_than_raw_does_not_extend_flags_or_prevent_selection(self):
        extra = pd.DataFrame({"Ref Wafer": ["unused", "unused", "unused"], "Ref Die": ["7", "8", "9"],
                              "REF CD": ["17.0000", "19.0000", "21.0000"]})
        self.window.set_reference_frame(pd.concat([self.ref, extra], ignore_index=True))
        self.window.run_analysis()
        script = json.loads(self.window.selection_script())
        self.assertEqual(len(script["records"]), len(self.raw))
        errors = []

        def inspect_dialog():
            dialog = APP.activeModalWidget()
            try:
                self.assertEqual(len(dialog.plan.order_frame), len(self.raw))
                self.assertEqual(len(dialog.plan.reference), len(self.raw))
            except Exception as error:
                errors.append(error)
            finally:
                dialog.reject()

        QTimer.singleShot(0, inspect_dialog)
        self.window.select_analysis_data()
        self.assertEqual(errors, [])
        viewer = self.open_spectra()
        self.assertEqual(viewer.spectra_info().with_flags["REF CD"].tolist(),
                         ["3.0000", "5.0000", "7.0000", "9.0000", "11.0000", ""])


if __name__ == "__main__":
    unittest.main()
