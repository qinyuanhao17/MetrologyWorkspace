"""Canonical Type2 wafer aliases preserve the literal source and classifications."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd
from openpyxl import Workbook, load_workbook
from PyQt6.QtWidgets import QApplication

from metrology_app.matching import ParameterMapping
from metrology_app.matching_window import MatchingWindow
from metrology_app.mark2 import labels_for_raw
from metrology_app.match_groups import row_ids
from metrology_app.wafer_id_mapping import apply, config, import_excel, original_raw
from metrology_app.workspace_store import load_workspace
from metrology_app.sme_spectra import LoadResult
from tests.test_type2_v51_integration import IDENTITY, sources

APP = QApplication.instance() or QApplication([])


def fixtures():
    raw, ref, labels, spectra = sources()
    targets = raw["Wafer ID"].tolist()
    raw["Wafer ID"] = ["OLD-" + value for value in targets]
    mapping = config({"identity_columns": IDENTITY,
                      "records": [{"identity": raw.iloc[i][IDENTITY].tolist(), "wafer_id": target}
                                  for i, target in enumerate(targets)]})
    for i, record in enumerate(labels["records"]):
        record["identity"] = raw.iloc[i][IDENTITY].tolist()
    return raw, ref, labels, spectra, mapping


class WaferMappingTests(unittest.TestCase):
    def test_import_reorder_numeric_coordinates_and_preserve_strings(self):
        raw, _, _, _, mapping = fixtures()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "mapping.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.append([*IDENTITY, None, "Wafer ID"])
            for record in reversed(mapping["records"]):
                sheet.append([*record["identity"], None, record["wafer_id"]])
            book.save(path)
            imported = import_excel(path)
        raw["FIELD X"] = "-1.000"
        result = apply(raw.iloc[::-1], imported)
        self.assertEqual(result["Wafer ID"].tolist(), ["W2"] * 3 + ["W1"] * 3)
        self.assertEqual(raw["Wafer ID"].iloc[0], "OLD-W1")
        pd.testing.assert_frame_equal(original_raw(result), raw.iloc[::-1])
        pd.testing.assert_frame_equal(original_raw(result.iloc[[1, 4]]), raw.iloc[::-1].iloc[[1, 4]])

    def test_missing_duplicate_and_conflicting_records_are_rejected(self):
        raw, _, _, _, mapping = fixtures()
        missing = deepcopy(mapping)
        missing["records"].pop()
        with self.assertRaisesRegex(ValueError, "no entry"):
            apply(raw, missing)
        duplicate = deepcopy(mapping)
        duplicate["records"].append(duplicate["records"][0])
        with self.assertRaisesRegex(ValueError, "Duplicate or conflicting"):
            config(duplicate)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            apply(pd.concat([raw, raw.iloc[[0]]]), mapping)
        wrong_lot = raw.copy()
        wrong_lot.loc[0, "Lot ID"] = "not-the-same-lot"
        with self.assertRaisesRegex(ValueError, "Lot ID"):
            apply(wrong_lot, mapping)
        canonical = apply(raw, mapping).copy()
        canonical.attrs.clear()
        with self.assertRaisesRegex(ValueError, "no entry"):
            apply(canonical, mapping, source_only=True)


class WaferMappingWindowTests(unittest.TestCase):
    def setUp(self):
        self.raw, self.ref, self.labels, self.spectra, self.mapping = fixtures()
        self.window = MatchingWindow()
        self.window.document.force_close = True
        self.addCleanup(self.close)
        self.window.apply_analysis_settings({"workbook_type": "type2"}, refresh=False)
        self.window.set_raw_frame(self.raw)
        self.window.set_reference_frame(self.ref)
        self.window.set_matching_keys({"reference": ["Ref Wafer", "Ref Die"], "raw": ["Wafer ID", "Die Seq"]})
        self.window._populate_mappings([ParameterMapping("CD", "REF CD", "CD")])
        self.window.group_controls.change("mark2", self.labels)
        self.window.group_controls.mark2_enabled.setChecked(True)
        self.window.run_analysis()
        self.assertEqual(self.window.result.card("CD").valid_pairs, 0)

    def close(self):
        for child in tuple(self.window._stage_windows):
            child.document.force_close = True
            child.close()
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def test_import_refreshes_match_metrics_mark2_child_and_reset(self):
        ids = row_ids(self.raw)
        self.window.set_wafer_id_mapping(self.mapping)
        self.assertEqual(self.window.result.card("CD").valid_pairs, 5)
        self.assertAlmostEqual(self.window.result.card("CD").slope, 2)
        plan = self.window.result.group_plan
        self.assertEqual(row_ids(plan.raw), ids)
        self.assertEqual(plan.mark2_labels, labels_for_raw(self.raw, self.labels))
        self.assertEqual(plan.raw["Wafer ID"].tolist(), ["W1"] * 3 + ["W2"] * 3)
        pd.testing.assert_frame_equal(self.window.raw_model.document_frame(), self.raw)
        summary = self.window.result.wafer_summary("CD")
        self.assertTrue(all("OLD-" not in str(v) for v in summary["Wafer"]))
        self.window.metrics_group_combo.setCurrentIndex(self.window.metrics_group_combo.findData("Product"))
        self.window._wafer_checked("CD", 0, True)
        detail = self.window.plot_groups["CD"]["wafer_details"]["A"]
        self.assertEqual(detail["result"].card("CD").valid_pairs, 3)
        self.assertEqual(detail["result"].group_plan.mark2_labels,
                         tuple(plan.mark2_labels[i] for i in [0, 2, 3, 5]))
        child = self.window.open_correlation_workspace()
        self.assertEqual(child.raw_model.frame()["Wafer ID"].tolist(), plan.raw["Wafer ID"].tolist())
        self.assertIsNotNone(child._group_plan)
        self.assertEqual(child._group_plan.mark2_labels, plan.mark2_labels)
        self.window.set_wafer_id_mapping(None)
        self.assertEqual(self.window.result.card("CD").valid_pairs, 0)
        self.assertEqual(self.window._effective_raw_frame()["Wafer ID"].tolist(), self.raw["Wafer ID"].tolist())

    def test_wkb_recovery_final_stage_excel_and_selection_script(self):
        self.window.result_mode.setCurrentText("Final")
        self.window.set_raw_frame(self.raw.copy())
        self.window.result_mode.setCurrentText("Preview")
        self.window.set_wafer_id_mapping(self.mapping)
        script = json.loads(self.window.selection_script())
        self.assertEqual({r["wafer_id"] for r in script["records"]}, {"W1", "W2"})
        for mode in ("Final", "Preview"):
            self.window.result_mode.setCurrentText(mode)
            self.window.run_analysis()
            self.assertEqual(self.window.result.card("CD").valid_pairs, 5)
        frame = self.window.current_workbook().stage_frame("preview", apply_card=False)
        self.assertEqual(frame["Wafer ID"].tolist(), ["W1"] * 3 + ["W2"] * 3)
        self.window.preview_map_frame = frame
        with TemporaryDirectory() as directory:
            path = self.window.save_workbook(Path(directory) / "mapped.mwkb")
            stored = load_workspace(path)
            self.assertEqual(stored.states["match"]["wafer_id_mapping"], self.mapping)
            pd.testing.assert_frame_equal(stored.frames["raw"], self.raw)
            reopened = MatchingWindow()
            reopened.document.force_close = True
            try:
                reopened.restore_workspace(stored)
                self.assertEqual(reopened.result.card("CD").valid_pairs, 5)
                report = load_workbook(reopened.export_excel(Path(directory) / "mapped.xlsx"))
                try:
                    strings = [c.value for sheet in report for row in sheet for c in row if isinstance(c.value, str)]
                    self.assertIn("W1", strings)
                    self.assertIn("OLD-W1", strings)  # Literal Raw source is retained in the report.
                finally:
                    report.close()
                reopened.set_wafer_id_mapping(None)
                self.assertEqual(reopened.current_workbook().stage_frame("preview")["Wafer ID"].tolist(),
                                 self.raw["Wafer ID"].tolist())
            finally:
                reopened.close()
                reopened.deleteLater()
        recovery = self.window.workspace_snapshot(include_drafts=True)
        self.window.restore_workspace(recovery)
        self.assertEqual(self.window.result.card("CD").valid_pairs, 5)
        self.assertEqual(self.window.wafer_id_mapping, self.mapping)

    def test_invalid_import_keeps_previous_mapping_and_literal_sources(self):
        self.window.set_wafer_id_mapping(self.mapping)
        bad = deepcopy(self.mapping)
        bad["records"].pop()
        with self.assertRaises(ValueError):
            self.window.set_wafer_id_mapping(bad)
        self.assertEqual(self.window.wafer_id_mapping, self.mapping)
        self.assertEqual(self.window.result.card("CD").valid_pairs, 5)
        pd.testing.assert_frame_equal(self.window.raw_frame, self.raw)
        pd.testing.assert_frame_equal(self.window.reference_frame, self.ref)

    def test_mapping_menu_and_processing_are_type2_only(self):
        self.window.set_wafer_id_mapping(self.mapping)
        self.assertTrue(self.window.wafer_id_mapping_menu.menuAction().isVisible())
        self.window.apply_analysis_settings({"workbook_type": "type1"}, refresh=False)
        self.assertFalse(self.window.wafer_id_mapping_menu.menuAction().isVisible())
        pd.testing.assert_frame_equal(self.window._effective_raw_frame(), self.raw)
        with self.assertRaisesRegex(ValueError, "only for Type2"):
            self.window.set_wafer_id_mapping(self.mapping)

    def test_selection_exclusions_and_spectra_use_new_ids(self):
        selection = {"records": [{"id": str(i), "key": key} for i, key in enumerate(row_ids(self.raw))],
                     "excluded": ["1"], "hide_excluded": True}
        for state in (self.window.group_controls.state, self.window.group_controls.state["applied"]):
            state["data_selection"] = deepcopy(selection)
        self.window.set_wafer_id_mapping(self.mapping)
        self.assertEqual(self.window.result.source_rows, (0, 2, 3, 4, 5))
        child = self.window.open_stage_workspace("preview")
        self.assertEqual(child.participating_positions(child.model.frame()), {0, 2, 3, 4, 5})
        viewer = self.window.open_spectra_workspace()
        viewer.apply_load_result(LoadResult(self.spectra, ()), replace=True)
        self.assertTrue(viewer.copy_wkb_selection())
        self.assertEqual({s.key for s in viewer.checked_spectra()},
                         {self.spectra[i].key for i in (0, 2, 3, 4, 5)})
        info = viewer.spectra_info().with_flags
        self.assertEqual(info["REF CD"].tolist(), ["3.0000", "7.0000", "9.0000", "11.0000", ""])


if __name__ == "__main__":
    unittest.main()
