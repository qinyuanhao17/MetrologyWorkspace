"""Mapping rows can be removed and restored without deleting source measurements."""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pandas as pd
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox, QDoubleSpinBox
from metrology_app.matching_window import MatchingWindow
from metrology_app.workspace_store import save_workspace

APP = QApplication.instance() or QApplication([])


class MappingRowControlTests(unittest.TestCase):
    def setUp(self):
        self.window = MatchingWindow()
        self.reference = pd.DataFrame({"CD Reference": ["2.000", "4.000", "6.000"],
                                       "Depth Reference": ["7.000", "11.000", "15.000"]})
        self.raw = pd.DataFrame({"Wafer ID": ["001"] * 3, "Die Seq": ["002", "036", "085"],
                                 "CD": ["1.000", "2.000", "3.000"], "Depth": ["3.000", "5.000", "7.000"]})
        self.window.set_reference_frame(self.reference)
        self.window.set_raw_frame(self.raw)

    def tearDown(self):
        self.window.document.force_close = True
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def add_mapping(self, reference):
        failures = []

        def choose_reference():
            dialog = APP.activeModalWidget()
            try:
                dialog.findChild(QComboBox).setCurrentText(reference)
                dialog.accept()
            except Exception as error:
                failures.append(error)
                if dialog is not None:
                    dialog.reject()

        QTimer.singleShot(0, choose_reference)
        self.window.mapping_add_button.click()
        self.assertEqual(failures, [])


    def test_minus_removes_checked_mapping_and_matching_plots_but_not_source_data(self):
        window = self.window
        window.run_analysis()
        window.mapping_table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
        window.mapping_remove_button.click()
        self.assertEqual(window.mapping_table.rowCount(), 1)
        self.assertEqual(window.mapping_table.item(0, 2).text(), "Depth Reference")
        self.assertNotIn("CD", window.plot_groups)
        self.assertIsNone(window.group_plot_page.result)
        pd.testing.assert_frame_equal(window.reference_model.document_frame(), self.reference)
        pd.testing.assert_frame_equal(window.raw_model.document_frame(), self.raw)
        window.set_raw_frame(self.raw.assign(CD=["9.100", "9.200", "9.300"]))
        self.assertEqual(window.mapping_table.rowCount(), 1, "An input refresh must not recreate removed mappings")
        self.assertTrue(window.mapping_add_button.isEnabled())
        self.assertFalse(window.mapping_remove_button.isEnabled())

    def test_plus_readds_a_reference_parameter_using_the_real_dialog_without_adding_ref_raw_choices(self):
        window = self.window
        self.assertTrue(window.mapping_add_button.isEnabled())
        window.mapping_remove_button.click()
        self.assertEqual(window.mapping_table.rowCount(), 0)
        self.assertTrue(window.mapping_add_button.isEnabled())
        failures = []

        def choose_cd():
            dialog = APP.activeModalWidget()
            try:
                combo = dialog.findChild(QComboBox)
                combo.setCurrentText("CD Reference")
                dialog.accept()
            except Exception as error:
                failures.append(error)
                dialog.reject()

        QTimer.singleShot(0, choose_cd)
        window.mapping_add_button.click()
        self.assertEqual(failures, [])
        self.assertEqual(window.mapping_table.rowCount(), 1)
        self.assertEqual(window.mapping_table.item(0, 2).text(), "CD Reference")
        self.assertEqual(window.selected_mappings()[0].raw_column, "CD")
        self.assertEqual(window.mapping_table.horizontalHeaderItem(3).text(), "Raw Data column")
        picker = window.mapping_table.cellWidget(0, 3)
        self.assertEqual([picker.itemText(i) for i in range(picker.count())], ["", "Wafer ID", "Die Seq", "CD", "Depth"])
        pd.testing.assert_frame_equal(window.reference_model.document_frame(), self.reference)
        pd.testing.assert_frame_equal(window.raw_model.document_frame(), self.raw)

    def test_plus_can_reuse_the_only_reference_and_preserve_both_rows_in_a_draft(self):
        window = self.window
        reference = self.reference[["CD Reference"]]
        window.set_reference_frame(reference)
        original = window.selected_mappings()
        self.assertTrue(window.mapping_add_button.isEnabled())
        failures = []

        def choose_reference():
            dialog = APP.activeModalWidget()
            try:
                combo = dialog.findChild(QComboBox)
                self.assertEqual([combo.itemText(i) for i in range(combo.count())], ["CD Reference"])
                dialog.accept()
            except Exception as error:
                failures.append(error)
                if dialog is not None:
                    dialog.reject()

        QTimer.singleShot(0, choose_reference)
        window.mapping_add_button.click()
        self.assertEqual(failures, [])
        self.assertEqual(window.mapping_table.rowCount(), 2)
        self.assertEqual(window.mapping_table.item(1, 2).text(), "CD Reference")
        self.assertEqual(window.mapping_table.item(1, 1).text(), "CD 2")
        self.assertEqual(window.mapping_table.item(1, 0).checkState(), Qt.CheckState.Unchecked)
        self.assertEqual(window.mapping_table.cellWidget(1, 3).currentText(), "")
        self.assertEqual(window.selected_mappings(), original)
        window.mapping_table.cellWidget(1, 3).setCurrentText("Depth")
        with TemporaryDirectory() as folder:
            path = Path(folder) / "shared-reference-draft.wkb"
            window.save_workbook(path)
            restored = MatchingWindow()
            try:
                restored.load_workbook(path)
                self.assertEqual(restored.mapping_table.rowCount(), 2)
                self.assertEqual(restored.mapping_table.item(1, 1).text(), "CD 2")
                self.assertEqual(restored.mapping_table.item(1, 2).text(), "CD Reference")
                self.assertEqual(restored.mapping_table.cellWidget(1, 3).currentText(), "Depth")
                self.assertEqual(restored.mapping_table.item(1, 0).checkState(), Qt.CheckState.Unchecked)
                self.assertEqual(restored.selected_mappings(), original)
                self.assertFalse(restored.document.is_dirty())
                pd.testing.assert_frame_equal(restored.reference_model.document_frame(), reference)
                pd.testing.assert_frame_equal(restored.raw_model.document_frame(), self.raw)
            finally:
                restored.document.force_close = True
                restored.close()
                restored.deleteLater()
                APP.processEvents()

    def test_shared_reference_comparisons_show_their_own_cards_and_reopen_independently(self):
        window = self.window
        reference = self.reference[["CD Reference"]]
        window.set_reference_frame(reference)
        window.mapping_table.item(0, 1).setText("CD comparison")
        self.add_mapping("CD Reference")
        window.mapping_table.item(1, 1).setText("Depth comparison")
        window.mapping_table.cellWidget(1, 3).setCurrentText("Depth")
        window.mapping_table.item(1, 0).setCheckState(Qt.CheckState.Checked)
        for row, limit in enumerate((.125, .75)):
            window.mapping_table.cellWidget(row, 10).findChild(QDoubleSpinBox).setValue(limit)
            window.mapping_table.cellWidget(row, 10).findChild(QCheckBox).setChecked(True)
        window.run_analysis()
        self.assertEqual(window.result.parameter_names, ("CD comparison", "Depth comparison"))
        self.assertEqual([window.mapping_table.item(row, 4).text() for row in range(2)], ["2", "1"])
        self.assertEqual([window.mapping_table.item(row, 5).text() for row in range(2)], ["0", "-1"])
        self.assertEqual(set(window.plot_groups), {"CD comparison", "Depth comparison"})
        self.add_mapping("CD Reference")
        window.mapping_table.cellWidget(2, 3).setCurrentText("Depth")
        window.run_analysis()
        self.assertEqual(window.mapping_table.item(2, 4).text(), "", "Unused mapping has no Card")
        expected = window.selected_mappings()
        with TemporaryDirectory() as folder:
            path = Path(folder) / "shared-reference-analyzed.wkb"
            window.save_workbook(path)
            restored = MatchingWindow()
            try:
                restored.load_workbook(path)
                self.assertEqual(restored.mapping_table.rowCount(), 3)
                self.assertEqual(restored.selected_mappings(), expected)
                self.assertEqual(restored.result.parameter_names, ("CD comparison", "Depth comparison"))
                self.assertEqual([restored.mapping_table.item(row, 4).text() for row in range(3)], ["2", "1", ""])
                self.assertEqual(restored.mapping_table.item(2, 0).checkState(), Qt.CheckState.Unchecked)
                self.assertEqual(restored.mapping_table.cellWidget(2, 3).currentText(), "Depth")
                pd.testing.assert_frame_equal(restored.result.summary, window.result.summary)
                self.assertFalse(restored.document.is_dirty())
                pd.testing.assert_frame_equal(restored.reference_model.document_frame(), reference)
                pd.testing.assert_frame_equal(restored.raw_model.document_frame(), self.raw)
            finally:
                restored.document.force_close = True
                restored.close()
                restored.deleteLater()
                APP.processEvents()

    def test_minus_only_removes_checked_rows_when_the_reference_is_shared(self):
        window = self.window
        reference = self.reference[["CD Reference"]]
        window.set_reference_frame(reference)
        self.add_mapping("CD Reference")
        window.mapping_table.cellWidget(1, 3).setCurrentText("Depth")
        window.run_analysis()
        window.mapping_remove_button.click()
        self.assertEqual(window.mapping_table.rowCount(), 1)
        self.assertEqual(window.mapping_table.item(0, 1).text(), "CD 2")
        self.assertEqual(window.mapping_table.item(0, 2).text(), "CD Reference")
        self.assertEqual(window.mapping_table.cellWidget(0, 3).currentText(), "Depth")
        self.assertEqual(window.mapping_table.item(0, 0).checkState(), Qt.CheckState.Unchecked)
        window.mapping_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        window.run_analysis()
        self.assertEqual(window.result.parameter_names, ("CD 2",))
        self.assertEqual(set(window.plot_groups), {"CD 2"})
        window.mapping_remove_button.click()
        self.assertEqual(window.mapping_table.rowCount(), 0)
        self.assertTrue(window.mapping_add_button.isEnabled())
        self.add_mapping("CD Reference")
        self.assertEqual(window.mapping_table.rowCount(), 1)
        self.assertEqual(window.selected_mappings()[0].raw_column, "CD")
        pd.testing.assert_frame_equal(window.reference_model.document_frame(), reference)
        pd.testing.assert_frame_equal(window.raw_model.document_frame(), self.raw)

    def test_shared_reference_rows_survive_source_refresh_and_stage_changes(self):
        window = self.window
        reference = self.reference[["CD Reference"]]
        window.set_reference_frame(reference)
        self.add_mapping("CD Reference")
        window.mapping_table.cellWidget(1, 3).setCurrentText("Depth")
        window.mapping_table.item(1, 0).setCheckState(Qt.CheckState.Checked)
        expected = window.selected_mappings()
        window.set_raw_frame(self.raw.drop(columns="Depth"))
        self.assertEqual(window.mapping_table.rowCount(), 2)
        self.assertFalse(window.analyze_button.isEnabled())
        window.set_raw_frame(self.raw.assign(Note=["A", "B", "C"]))
        self.assertEqual(window.selected_mappings(), expected)
        window.set_reference_frame(reference)
        self.assertEqual(window.selected_mappings(), expected)
        window.result_mode.setCurrentText("Final")
        window.set_raw_frame(self.raw.assign(Note=["Final"] * 3))
        self.assertEqual(window.mapping_table.rowCount(), 2)
        self.assertEqual(window.selected_mappings(), expected)
        window.result_mode.setCurrentText("Preview")
        self.assertEqual(window.mapping_table.rowCount(), 2)
        self.assertEqual(window.selected_mappings(), expected)
        pd.testing.assert_frame_equal(window.reference_model.document_frame(), reference)
        pd.testing.assert_frame_equal(window.raw_model.document_frame(), self.raw.assign(Note=["A", "B", "C"]))

    def test_new_unused_mapping_is_not_auto_selected_after_renaming_and_refresh(self):
        window = self.window
        window.set_reference_frame(self.reference[["CD Reference"]])
        window.mapping_table.item(0, 1).setText("Original calibration")
        self.add_mapping("CD Reference")
        window.mapping_table.item(1, 1).setText("CD")
        window.set_raw_frame(self.raw)
        self.assertEqual(window.mapping_table.item(1, 1).text(), "CD")
        self.assertEqual(window.mapping_table.item(1, 0).checkState(), Qt.CheckState.Unchecked)
        self.assertEqual(window.mapping_table.cellWidget(1, 3).currentText(), "")
        self.assertEqual([mapping.name for mapping in window.selected_mappings()], ["Original calibration"])
        with TemporaryDirectory() as folder:
            path = Path(folder) / "unused-renamed.wkb"
            window.save_workbook(path)
            restored = MatchingWindow()
            try:
                restored.load_workbook(path)
                self.assertEqual(restored.mapping_table.item(1, 1).text(), "CD")
                self.assertEqual(restored.mapping_table.item(1, 0).checkState(), Qt.CheckState.Unchecked)
                self.assertEqual(restored.mapping_table.cellWidget(1, 3).currentText(), "")
                self.assertEqual([mapping.name for mapping in restored.selected_mappings()], ["Original calibration"])
            finally:
                restored.document.force_close = True
                restored.close()
                restored.deleteLater()
                APP.processEvents()

    def test_older_reference_keyed_drafts_and_analyzed_workbooks_still_open(self):
        window = self.window
        with TemporaryDirectory() as folder:
            for analyzed in (False, True):
                with self.subTest(analyzed=analyzed):
                    if analyzed:
                        window.run_analysis()
                    snapshot = window.workspace_snapshot()
                    snapshot.states["match_ui"]["mapping_choices"] = {
                        row["reference_column"]: {key: value for key, value in row.items() if key != "reference_column"}
                        for row in snapshot.states["match_ui"]["mapping_choices"]
                    }
                    path = Path(folder) / f"legacy-{analyzed}.wkb"
                    save_workspace(path, snapshot)
                    restored = MatchingWindow()
                    try:
                        restored.load_workbook(path)
                        self.assertEqual(restored.mapping_table.rowCount(), 2)
                        self.assertEqual(restored.selected_mappings(), window.selected_mappings())
                        self.assertFalse(restored.document.is_dirty())
                        pd.testing.assert_frame_equal(restored.reference_model.document_frame(), self.reference)
                        pd.testing.assert_frame_equal(restored.raw_model.document_frame(), self.raw)
                    finally:
                        restored.document.force_close = True
                        restored.close()
                        restored.deleteLater()
                        APP.processEvents()

    def test_canceling_an_added_mapping_does_not_change_the_saved_workbook(self):
        window = self.window
        with TemporaryDirectory() as folder:
            window.save_workbook(Path(folder) / "before-cancel.wkb")
            before = window.selected_mappings()
            QTimer.singleShot(0, lambda: APP.activeModalWidget().reject())
            window.mapping_add_button.click()
            self.assertEqual(window.mapping_table.rowCount(), 2)
            self.assertEqual(window.selected_mappings(), before)
            self.assertFalse(window.document.is_dirty())

    def test_invalid_mapping_choices_are_rejected_before_replacing_the_document(self):
        window = self.window
        window.run_analysis()
        before = window.selected_mappings()
        result = window.result
        for invalid in ([{"reference_column": "CD Reference", "checked": "yes"}],
                        [{"reference_column": "CD Reference", "bias_limit": -1}], "CD Reference"):
            with self.subTest(invalid=invalid):
                snapshot = window.workspace_snapshot()
                snapshot.states["match_ui"]["mapping_choices"] = invalid
                with self.assertRaisesRegex(ValueError, "Invalid parameter mapping"):
                    window.restore_workspace(snapshot)
                self.assertEqual(window.selected_mappings(), before)
                self.assertIs(window.result, result)
                pd.testing.assert_frame_equal(window.reference_model.document_frame(), self.reference)
                pd.testing.assert_frame_equal(window.raw_model.document_frame(), self.raw)

    def test_removed_mappings_stay_removed_after_draft_and_analyzed_workbook_reopen(self):
        window = self.window
        window.mapping_table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
        window.mapping_remove_button.click()
        with TemporaryDirectory() as folder:
            path = Path(folder) / "mapping-rows.wkb"
            for analyzed in (False, True):
                with self.subTest(analyzed=analyzed):
                    if analyzed:
                        window.mapping_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
                        window.run_analysis()
                    window.save_workbook(path)
                    restored = MatchingWindow()
                    try:
                        restored.load_workbook(path)
                        self.assertEqual(restored.mapping_table.rowCount(), 1)
                        self.assertEqual(restored.mapping_table.item(0, 2).text(), "Depth Reference")
                        self.assertTrue(restored.mapping_add_button.isEnabled())
                        self.assertFalse(restored.document.is_dirty())
                        pd.testing.assert_frame_equal(restored.reference_model.document_frame(), self.reference)
                        pd.testing.assert_frame_equal(restored.raw_model.document_frame(), self.raw)
                        if analyzed:
                            self.assertEqual(restored.result.parameter_names, ("Depth",))
                    finally:
                        restored.document.force_close = True
                        restored.close()
                        restored.deleteLater()
                        APP.processEvents()


if __name__ == "__main__":
    unittest.main()
