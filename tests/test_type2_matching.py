"""Type2 ID matching through domain calculations and Workbook operations."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt, QModelIndex
from PyQt6.QtWidgets import QApplication

from metrology_app.matching import MatchWorkbook, ParameterMapping
from metrology_app.matching_window import MatchingWindow
from metrology_app.workbook_startup import WorkbookStartupDialog
from metrology_app.workspace_store import load_workspace

APP = QApplication.instance() or QApplication([])
KEYS = {"reference": ["WaferID", "Col/X", "Row/Y"], "raw": ["Wafer ID", "FIELD X", "FIELD Y"]}


def sources():
    ref = pd.DataFrame({"WaferID": ["001"]*5, "Col/X": ["3","1","2","8","9"], "Row/Y": ["0"]*5,
                        "CD": ["7.0000","3.0000","5.0000","17.0000","19.0000"]})
    raw = pd.DataFrame({"Wafer ID": ["001"]*4, "Die Seq": ["10","20","30","40"],
                        "FIELD X": ["1","4","2","3"], "FIELD Y": ["0"]*4,
                        "CD": ["1.0000","4.0000","2.0000","3.0000"]})
    return ref, raw


class Type2MatchingTests(unittest.TestCase):
    def test_matching_settings_collapse_frees_space_without_changing_analysis(self):
        from PyQt6.QtTest import QTest
        ref, raw = sources()
        window = MatchingWindow()
        try:
            window.apply_analysis_settings({"workbook_type": "type2"}, refresh=False)
            window.set_reference_frame(ref)
            window.set_raw_frame(raw)
            window.set_matching_keys(KEYS)
            result = window.run_analysis()
            window.resize(1400, 950)
            window.show()
            QTest.qWait(30)
            expanded_height = window.mapping_card.height()
            window.matching_settings_toggle.setChecked(False)
            APP.processEvents()
            self.assertFalse(window.matching_settings_body.isVisible())
            self.assertTrue(window.analyze_button.isVisible())
            self.assertTrue(window.matching_settings_toggle.isVisible())
            self.assertLess(window.mapping_card.height(), expanded_height)
            self.assertIs(window.result, result)
            self.assertEqual(window.matching_keys, KEYS)
            window.run_action.trigger()
            self.assertEqual(window.result.card("CD").valid_pairs, 3)
            self.assertFalse(window.matching_settings_toggle.isChecked())
            window.matching_settings_toggle.setChecked(True)
            APP.processEvents()
            self.assertTrue(window.matching_settings_body.isVisible())
            self.assertTrue(window.matching_conditions.isVisible())
            self.assertGreaterEqual(window.mapping_card.height(), 450)
        finally:
            window.document.force_close = True
            window.close(); window.deleteLater(); APP.processEvents()

    def test_collapsed_settings_survive_save_recovery_and_old_files_default_expanded(self):
        ref, raw = sources()
        window, reopened, recovered = MatchingWindow(), MatchingWindow(), MatchingWindow()
        try:
            window.apply_analysis_settings({"workbook_type": "type2"}, refresh=False)
            window.set_reference_frame(ref); window.set_raw_frame(raw); window.set_matching_keys(KEYS)
            window.run_analysis()
            window.matching_settings_toggle.setChecked(False)
            with TemporaryDirectory() as folder:
                path = window.save_workbook(Path(folder) / "collapsed.mwkb")
                reopened.load_workbook(path)
                self.assertFalse(reopened.matching_settings_toggle.isChecked())
                self.assertTrue(reopened.matching_settings_body.isHidden())
                self.assertFalse(reopened.document.is_dirty())
                self.assertEqual(reopened.matching_keys, KEYS)
                self.assertEqual(reopened.result.card("CD").valid_pairs, 3)
                reopened.reference_model.edit({(1, 3): "9.0000"})
                reopened.document.recovery_path = Path(folder) / "draft.mwkb"
                reopened.document.write_recovery()
                recovered.document.recover(reopened.document.recovery_path)
                self.assertFalse(recovered.matching_settings_toggle.isChecked())
                self.assertTrue(recovered.matching_settings_body.isHidden())
                old = recovered.workspace_snapshot()
                old.states["match_ui"].pop("matching_settings_expanded")
                old.states["match_ui"].pop("matching_settings_expanded_size")
                recovered.restore_workspace(old)
                self.assertTrue(recovered.matching_settings_toggle.isChecked())
                self.assertFalse(recovered.matching_settings_body.isHidden())
        finally:
            for target in (window, reopened, recovered):
                target.document.force_close = True
                target.close(); target.deleteLater()
            APP.processEvents()

    def test_row_count_and_order_do_not_control_pairing_in_either_stage(self):
        ref, raw = sources()
        for stage in ("preview", "final"):
            book = MatchWorkbook(ref, raw, [ParameterMapping("CD", "CD", "CD")], workbook_type="type2",
                                 matching_keys=KEYS, result_mode=stage, final_match_raw=raw)
            result = book.analyze()
            self.assertEqual(book.match_type, "Reference")
            self.assertEqual(result.card("CD").valid_pairs, 3)
            self.assertAlmostEqual(result.card("CD").slope, 2.)
            self.assertAlmostEqual(result.card("CD").intercept, 1.)
            np.testing.assert_allclose(result.series("CD")["Reference"], [3,np.nan,5,7], equal_nan=True)
            self.assertEqual(result.source_rows, (0,1,2,3))
            self.assertEqual(result.group_plan.reference["Col/X"].tolist(), ["1","","2","3"])
        with self.assertRaisesRegex(ValueError, "more rows"):
            MatchWorkbook(ref, raw, [ParameterMapping("CD","CD","CD")])

    def test_ambiguous_and_zero_pair_workbooks_report_missing_results(self):
        ref, raw = sources()
        ref = pd.concat([ref, ref], ignore_index=True)
        result = MatchWorkbook(ref, raw, [ParameterMapping("CD","CD","CD")], workbook_type="type2",
                               matching_keys=KEYS).analyze()
        self.assertEqual(result.card("CD").valid_pairs, 0)
        self.assertTrue(result.series("CD")["Reference"].isna().all())
        self.assertIn("duplicate Reference", result.id_alignment.message)

    def test_ui_creation_save_restore_and_linked_reference_follow_raw_ids(self):
        ref, raw = sources()
        window, reopened = MatchingWindow(), MatchingWindow()
        try:
            window.apply_analysis_settings({"workbook_type":"type2"}, refresh=False)
            window.set_reference_frame(ref)
            window.set_raw_frame(raw)
            self.assertFalse(window.run_action.isEnabled())
            window.set_matching_keys(KEYS)
            self.assertFalse(window.match_type_menu.menuAction().isVisible())
            self.assertTrue(window.mapping_table.isColumnHidden(8))
            self.assertEqual(window.match_type.currentText(), "Reference")
            self.assertTrue(window.run_action.isEnabled(), window.status.text())
            result = window.run_analysis()
            self.assertEqual(result.card("CD").valid_pairs, 3)
            child = window.open_correlation_workspace()
            self.assertEqual(child.reference_model.document_frame()["CD"].tolist(), ["3.0000","","5.0000","7.0000"])
            with TemporaryDirectory() as folder:
                path = window.save_workbook(Path(folder)/"id.mwkb")
                saved = load_workspace(path)
                self.assertEqual(saved.states["match"]["matching_keys"], KEYS)
                pd.testing.assert_frame_equal(saved.frames["reference"], ref)
                reopened.load_workbook(path)
                self.assertEqual(reopened.matching_conditions.selection(), KEYS)
                self.assertFalse(reopened.document.is_dirty())
                self.assertEqual(reopened.result.card("CD").valid_pairs, 3)
                window.reference_model.edit({(1,3):"9.0000"})
                window.run_analysis()
                self.assertEqual(child.reference_model.document_frame()["CD"].iloc[3], "9.0000")
        finally:
            for target in (window, reopened):
                target.document.force_close = True
                target.close()
                target.deleteLater()
            APP.processEvents()

    def test_ordered_lists_pair_checked_fields_and_report_missing_columns(self):
        window = MatchingWindow()
        try:
            window.apply_analysis_settings({"workbook_type":"type2"}, refresh=False)
            ref, raw = sources()
            window.set_reference_frame(ref)
            window.set_raw_frame(raw)
            window.set_matching_keys(KEYS)
            fields = window.matching_conditions.lists["reference"]
            self.assertEqual(fields.dragDropMode(), fields.DragDropMode.InternalMove)
            self.assertTrue(fields.model().moveRows(QModelIndex(),0,1,QModelIndex(),3))
            self.assertEqual(window.matching_keys["reference"], ["Col/X","Row/Y","WaferID"])
            window.set_matching_keys(KEYS)
            window.set_raw_frame(raw.drop(columns="FIELD Y"))
            self.assertFalse(window.run_action.isEnabled())
            self.assertIn("FIELD Y", window.matching_conditions.status.text())
            self.assertIn("FIELD Y", window.matching_keys["raw"])
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_type2_new_dialog_has_no_instrument_selection(self):
        dialog = WorkbookStartupDialog(new=True)
        try:
            dialog.workbook_type.setCurrentIndex(dialog.workbook_type.findData("type2"))
            self.assertTrue(dialog.match_type.isHidden())
            self.assertEqual(dialog.settings()["match_type"],"Reference")
            dialog.workbook_type.setCurrentIndex(dialog.workbook_type.findData("type1"))
            self.assertFalse(dialog.match_type.isHidden())
        finally:
            dialog.deleteLater()
            APP.processEvents()

    def test_no_matches_keep_raw_trend_visible_and_explain_unavailable_card(self):
        ref, raw = sources()
        ref["WaferID"] = "other wafer"
        window = MatchingWindow()
        try:
            window.apply_analysis_settings({"workbook_type":"type2"}, refresh=False)
            window.set_reference_frame(ref)
            window.set_raw_frame(raw)
            window.set_matching_keys(KEYS)
            result = window.run_analysis()
            self.assertEqual(result.card("CD").valid_pairs,0)
            trend = window.plot_groups["CD"]["plots"]["trend"]
            self.assertFalse(trend.card_checkbox.isEnabled())
            self.assertFalse(trend.card_checkbox.isChecked())
            pmish = next(curve for curve in trend.listDataItems() if curve.name()=="PMISH")
            np.testing.assert_allclose(pmish.yData,[1,4,2,3])
        finally:
            window.document.force_close=True
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_reference_filters_evaluate_the_id_aligned_row(self):
        ref,raw=sources()
        book=MatchWorkbook(ref,raw,[ParameterMapping("CD","CD","CD")],workbook_type="type2",matching_keys=KEYS,
                           grouping_state={"filters":[{"table":"reference","column":"CD","minimum":4.}]})
        result=book.analyze()
        self.assertEqual(result.source_rows,(2,3))
        self.assertAlmostEqual(result.card("CD").slope,2.)

    def test_key_choices_and_literal_tables_survive_recovery(self):
        ref,raw=sources()
        window,recovered=MatchingWindow(),MatchingWindow()
        try:
            window.apply_analysis_settings({"workbook_type":"type2"},refresh=False)
            window.set_reference_frame(ref)
            window.set_raw_frame(raw)
            window.set_matching_keys(KEYS)
            window.run_analysis()
            with TemporaryDirectory() as folder:
                window.document.recovery_path=Path(folder)/"draft.mwkb"
                window.document.write_recovery()
                recovered.document.recover(window.document.recovery_path)
                self.assertEqual(recovered.matching_keys,KEYS)
                self.assertEqual(recovered.result.card("CD").valid_pairs,3)
                pd.testing.assert_frame_equal(recovered.reference_model.document_frame(),ref)
                pd.testing.assert_frame_equal(recovered.raw_model.document_frame(),raw)
        finally:
            for target in (window,recovered):
                target.document.force_close=True
                target.close()
                target.deleteLater()
            APP.processEvents()

    def test_correlation_uses_matched_rows_but_trend_keeps_unmatched_raw(self):
        ref,raw=sources()
        window=MatchingWindow()
        try:
            window.apply_analysis_settings({"workbook_type":"type2"},refresh=False)
            window.set_reference_frame(ref)
            window.set_raw_frame(raw)
            window.set_matching_keys(KEYS)
            window.run_analysis()
            child=window.open_correlation_workspace()
            child.update_plan()
            correlation_rows={row for key,rows in child.correlation_page.selection["groups"].items()
                              if key[0]=="Raw Data" for row in rows}
            trend_rows={row for key,rows in child.sequence_page.selection["groups"].items()
                        if key[0]=="Raw Data" for row in rows}
            self.assertEqual(correlation_rows,{4,6,7})
            self.assertEqual(trend_rows,{4,5,6,7})
            child.reference_model.edit({(1,child.reference_model.document_frame().columns.get_loc("CD")):"101.000"})
            window.reference_model.edit({(2,3):"13.0000"})
            window.run_analysis()
            self.assertEqual(child.reference_model.document_frame()["CD"].iloc[0],"101.000")
        finally:
            window.document.force_close=True
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_large_linked_updates_realign_reference_after_raw_key_edits(self):
        from time import monotonic
        from PyQt6.QtTest import QTest
        ref = pd.DataFrame({"WaferID": ["001"]*1200, "Col/X":list(map(str,range(1200))),
                            "Row/Y":["0"]*1200,"CD":list(map(str,range(1200)))})
        raw = pd.DataFrame({"Wafer ID":["001"]*1000,"FIELD X":list(map(str,range(1000))),
                            "FIELD Y":["0"]*1000,"CD":list(map(str,range(1000))),
                            **{f"metadata{i}":["text"]*1000 for i in range(6)}})
        window=MatchingWindow()
        try:
            window.apply_analysis_settings({"workbook_type":"type2"},refresh=False)
            window.set_reference_frame(ref);window.set_raw_frame(raw);window.set_matching_keys(KEYS)
            window.run_analysis()
            child=window.open_correlation_workspace()
            window._background_stage_refresh=True
            window.raw_model.edit({(1,1):"1100"})
            window.run_analysis()
            deadline=monotonic()+8
            while monotonic()<deadline:
                QTest.qWait(20)
                if child.reference_model.document_frame()["CD"].iloc[0]=="1100":
                    break
            self.assertEqual(child.raw_model.document_frame()["FIELD X"].iloc[0],"1100")
            self.assertEqual(child.reference_model.document_frame()["CD"].iloc[0],"1100")
        finally:
            window.document.force_close=True
            window.close();window.deleteLater();APP.processEvents()
