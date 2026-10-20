"""Partial Reference measurements use source row positions without dropping Raw."""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QApplication

from metrology_app.matching import MatchWorkbook, ParameterMapping
from metrology_app.matching_window import MatchingWindow
from metrology_app.match_groups import row_ids

APP = QApplication.instance() or QApplication([])


def sources():
    reference = pd.DataFrame({"CD Reference": ["3.000", "", "7.000", "9.000", "11.000"]})
    raw = pd.DataFrame({"Wafer ID": ["W1"] * 6, "Die Seq": ["001", "003", "005", "007", "009", "011"],
                        "CD": ["1.000", "2.000", "3.000", "4.000", "5.000", "6.000"]})
    return reference, raw


class PartialReferenceMatchingTests(unittest.TestCase):
    def test_partial_reference_matches_only_finite_original_row_pairs_in_every_mode(self):
        reference, raw = sources()
        for match_type in ("TEM", "NOVA", "KLA"):
            for stage in ("preview", "final"):
                with self.subTest(match_type=match_type, stage=stage):
                    book = MatchWorkbook(reference, raw, [ParameterMapping("CD", "CD Reference", "CD")],
                                         match_type=match_type, result_mode=stage)
                    result = book.analyze()
                    self.assertEqual(result.card("CD").valid_pairs, 4)
                    self.assertAlmostEqual(result.card("CD").slope, 2.)
                    self.assertAlmostEqual(result.card("CD").intercept, 1.)
                    series = result.series("CD")
                    self.assertEqual(len(series), len(raw))
                    self.assertTrue(np.isnan(series["Bias"].iloc[1]))
                    self.assertTrue(np.isnan(series["Bias"].iloc[5]))
                    pd.testing.assert_frame_equal(book.reference, reference)
                    pd.testing.assert_frame_equal(book.raw, raw)

    def test_partial_reference_does_not_block_run_or_compact_empty_rows_in_workbook_ui(self):
        reference, raw = sources()
        for match_type, stage in ((mode, stage) for mode in ("TEM", "NOVA", "KLA")
                                  for stage in ("Preview", "Final")):
            with self.subTest(match_type=match_type, stage=stage):
                window = MatchingWindow()
                try:
                    window.match_type.setCurrentText(match_type)
                    window.result_mode.setCurrentText(stage)
                    window.set_reference_frame(reference)
                    window.set_raw_frame(raw)
                    self.assertTrue(window.run_action.isEnabled(), window.status.text())
                    result = window.run_analysis()
                    self.assertEqual(result.card("CD").valid_pairs, 4)
                    self.assertAlmostEqual(result.card("CD").slope, 2.)
                    self.assertEqual(len(result.series("CD")), len(raw))
                    self.assertNotIn("Row count differs", window.status.text())
                    pd.testing.assert_frame_equal(window.reference_model.document_frame(), reference)
                    raw_model = window.raw_model if stage == "Preview" else window.final_raw_model
                    pd.testing.assert_frame_equal(raw_model.document_frame(), raw)
                finally:
                    window.document.force_close = True
                    window.close()
                    window.deleteLater()
                    APP.processEvents()

    def test_editing_blank_reference_cells_and_undo_preserve_original_pair_positions(self):
        reference, raw = sources()
        reference.iloc[1, 0] = "5.000"
        window = MatchingWindow()
        try:
            window.match_type.setCurrentText("NOVA")
            window.set_reference_frame(reference)
            window.set_raw_frame(raw)
            window.group_controls.restore({"enabled": False, "mark_enabled": False})
            window.run_analysis()
            window.reference_model.edit({(2, 0): ""})
            result = window.run_analysis()
            self.assertEqual(len(window.reference_frame), 5)
            self.assertEqual(result.card("CD").valid_pairs, 4)
            self.assertAlmostEqual(result.card("CD").slope, 2.)
            self.assertEqual(result.series("CD")["Reference"].iloc[2], 7.)
            self.assertTrue(np.isnan(result.series("CD")["Reference"].iloc[1]))
            window.reference_model.undo.undo()
            result = window.run_analysis()
            self.assertEqual(result.card("CD").valid_pairs, 5)
            self.assertAlmostEqual(result.card("CD").slope, 2.)
            pd.testing.assert_frame_equal(window.reference_model.document_frame(), reference)
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_partial_reference_survives_wkb_reopen_and_existing_analysis_windows(self):
        reference, raw = sources()
        window, restored = MatchingWindow(), None
        try:
            window.match_type.setCurrentText("NOVA")
            window.set_reference_frame(reference)
            window.set_raw_frame(raw)
            window.run_analysis()
            window.open_correlation_workspace()
            window.open_stage_workspace("preview")
            with TemporaryDirectory() as folder:
                path = Path(folder) / "partial-reference.mwkb"
                window.save_workbook(path)
                restored = MatchingWindow()
                restored.load_workbook(path)
                result = restored.run_analysis()
                self.assertEqual(result.card("CD").valid_pairs, 4)
                pd.testing.assert_frame_equal(restored.reference_model.document_frame(), reference)
                pd.testing.assert_frame_equal(restored.raw_model.document_frame(), raw)
                child = restored.open_correlation_workspace()
                self.assertTrue(child.reference_model.document_frame().empty)
                pd.testing.assert_frame_equal(child.raw_model.document_frame(), raw)
                self.assertEqual(len(restored.open_stage_workspace("preview").model.document_frame()), 6)
        finally:
            for owner in (window, restored):
                if owner is not None:
                    owner.document.force_close = True
                    owner.close()
                    owner.deleteLater()
            APP.processEvents()

    def test_reference_filters_and_head_groups_keep_the_complete_raw_row_space(self):
        reference, raw = sources()
        mapping = [ParameterMapping("CD", "CD Reference", "CD")]
        grouped = MatchWorkbook(reference, raw, mapping, match_type="NOVA",
                                test_flags=pd.DataFrame({"TestFlag": [0, 0, 0, 1, 1, 1]}),
                                grouping_state={"enabled": True})
        result = grouped.analyze()
        self.assertEqual(result.source_rows, tuple(range(6)))
        self.assertEqual(result.group_summary("CD")["Valid pairs"].tolist(), [2, 2])
        filtered = MatchWorkbook(reference, raw, mapping, match_type="KLA", grouping_state={
            "filters": [{"table": "reference", "column": "CD Reference", "minimum": 6.}]})
        result = filtered.analyze()
        self.assertEqual(result.source_rows, (2, 3, 4))
        self.assertEqual(result.card("CD").valid_pairs, 3)
        self.assertAlmostEqual(result.card("CD").slope, 2.)

    def test_partial_reference_keeps_selected_raw_row_scope_in_copied_child(self):
        reference, raw = sources()
        window = MatchingWindow()
        try:
            window.match_type.setCurrentText("NOVA")
            window.set_reference_frame(reference)
            window.set_raw_frame(raw)
            window.group_controls.restore({"enabled": False, "mark_enabled": False, "data_selection": {
                "records": [{"key": key, "id": f"row{i}"} for i, key in enumerate(row_ids(raw))],
                "excluded": ["row2"],
            }})
            result = window.run_analysis()
            self.assertEqual(result.source_rows, (0, 1, 3, 4, 5))
            self.assertEqual(result.card("CD").valid_pairs, 3)
            child = window.open_correlation_workspace()
            pd.testing.assert_frame_equal(child.raw_model.document_frame(), raw)
            self.assertEqual(child.participating_positions(raw), {0, 1, 3, 4, 5})
            self.assertTrue(child.reference_model.document_frame().empty)
            pd.testing.assert_frame_equal(window.reference_model.document_frame(), reference)
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            APP.processEvents()
