"""Public editor workflows when one Workbook is reused for multiple OCD cases."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from metrology_app.matching import MatchWorkbook, ParameterMapping
from metrology_app.matching_window import MatchingWindow
from metrology_app.correlation_window import CorrelationWindow
from metrology_app.sheet import SheetModel, SheetView, clipboard_rows
from metrology_app.settings import get_settings, save_settings
from metrology_app.workspace_document import analysis_state, restore_analysis_state

APP = QApplication.instance() or QApplication([])


def case_frames(name, rows, extra=0):
    values = np.arange(rows, dtype=float) + 10
    raw = pd.DataFrame({"Wafer ID": [f"{name}-W1"] * rows,
                        "Die Seq": np.arange(1, rows + 1),
                        "X(mm)": np.arange(rows) % 3, "Y(mm)": np.arange(rows) // 3,
                        f"OCD_{name}": [f"{value:.8f}" for value in values]})
    for column in range(extra):
        raw[f"{name}_extra_{column}"] = values + column + 100
    reference = pd.DataFrame({f"{name} Reference": values * 1.02 + 0.3})
    return reference, raw


def paste_case(window, name, rows, extra=0):
    reference, raw = case_frames(name, rows, extra)
    with patch.object(SheetView, "mismatched_paste_choice", return_value="keep"):
        for view, frame in ((window.reference_view, reference), (window.raw_view, raw)):
            APP.clipboard().setText(frame.to_csv(sep="\t", index=False, lineterminator="\n"))
            view.setCurrentIndex(view.model().index(0, 0))
            view.paste()
    window._populate_mappings([ParameterMapping(name, f"{name} Reference", f"OCD_{name}")])
    window.run_analysis()
    APP.processEvents()
    return reference, raw


class CaseSwitchingTests(unittest.TestCase):
    def setUp(self):
        saved = get_settings()
        self.addCleanup(save_settings, saved)
        self.window = MatchingWindow()
        self.window.match_type.setCurrentText("NOVA")
        self.addCleanup(self.close)

    def close(self):
        self.window.document.force_close = True
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def test_match_fit_equation_and_r_squared_support_selection_and_copy(self):
        paste_case(self.window, "CD", 6)
        plot = self.window.plot_groups["CD"]["plots"]["match"]
        self.assertFalse(plot.heading.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        label = plot.formula_label
        self.assertTrue(label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse)
        self.assertTrue(label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.assertIn("R²", label.text())
        self.window.show()
        APP.processEvents()
        label.setFocus()
        label.setSelection(0, len(label.text()))
        APP.clipboard().clear()
        QTest.keyClick(label, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(APP.clipboard().text(), label.text())

    def test_floating_raw_has_no_native_transient_owner_and_closes_with_workbook(self):
        self.window.show()
        controller = self.window.raw_floating_editor
        controller.detach()
        APP.processEvents()
        dialog = controller.dialog
        self.assertIsNone(dialog.parentWidget(), "An owned Tool window can raise the entire Workbook above sibling analyses")
        self.assertIsNone(dialog.windowHandle().transientParent())
        self.assertFalse(dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint,
                         'Raw must not be topmost over unrelated applications')
        self.assertIs(self.window.raw_view, controller.panel.findChild(SheetView))
        self.window.document.force_close = True
        self.window.close()
        APP.processEvents()
        self.assertFalse(dialog.isVisible())

    def test_linked_map_retains_mapped_raw_column_and_literal_values(self):
        paste_case(self.window, "CD", 6, 2)
        child = self.window.open_stage_workspace("preview")
        child.set_copy_from_wkb(True)
        expected = self.window.raw_model.document_frame()
        actual = child.model.document_frame()
        self.assertTrue(set(expected.columns) <= set(actual.columns),
                        f"Copied Map dropped original Raw columns: {set(expected.columns) - set(actual.columns)}")
        pd.testing.assert_frame_equal(actual.loc[:, expected.columns], expected)

    def test_original_raw_column_uses_its_mapping_card_and_restores_without_changing_literals(self):
        paste_case(self.window, "CD", 6)
        child = self.window.open_stage_workspace("preview")
        original = child.model.document_frame()
        child.card_check.setChecked(True)
        expected = pd.to_numeric(original["OCD_CD"]) * 1.02 + .3
        np.testing.assert_allclose(child.plot_page.frame["OCD_CD"], expected)
        np.testing.assert_allclose(child.parameter_cards["OCD_CD"], [1.02, .3])
        state = analysis_state(child)
        child.card_check.setChecked(False)
        child.set_parameter_cards({})
        restore_analysis_state(child, state)
        child.recognize()
        np.testing.assert_allclose(child.plot_page.frame["OCD_CD"], expected)
        pd.testing.assert_frame_equal(child.model.document_frame(), original)

    def test_calibrated_stage_reads_original_columns_for_swapped_aliases_and_shared_inputs(self):
        raw = pd.DataFrame({"Wafer ID": ["W1"] * 4, "Die Seq": [1, 2, 3, 4],
                            "A": ["1.000", "2.000", "3.000", "4.000"],
                            "B": ["10.000", "20.000", "30.000", "40.000"]})
        reference = pd.DataFrame({"Ref A": [21., 41., 61., 81.],
                                  "Ref B": [5., 8., 11., 14.],
                                  "Ref C": [9., 13., 17., 21.]})
        book = MatchWorkbook(reference, raw,
                             [ParameterMapping("A", "Ref A", "B"),
                              ParameterMapping("B", "Ref B", "A"),
                              ParameterMapping("C", "Ref C", "A")], match_type="NOVA")
        stage = book.stage_frame("preview", apply_card=True)
        for column in ("A", "B", "C"):
            np.testing.assert_allclose(stage[column], reference[f"Ref {column}"])
        literal = book.stage_frame("preview", apply_card=False)
        pd.testing.assert_frame_equal(literal.loc[:, raw.columns], raw)
        pd.testing.assert_frame_equal(book.raw, raw)

    def test_ordinary_paste_of_different_cases_keeps_open_linked_sources_complete(self):
        paste_case(self.window, "CD", 6, 2)
        map_window = self.window.open_stage_workspace("preview")
        correlation = self.window.open_correlation_workspace()
        map_window.set_copy_from_wkb(True)
        correlation.set_copy_from_wkb(True)
        correlation.set_reference_table(pd.DataFrame({"Manual Ref": ["1.000", "2.000"]}))
        manual_ref = correlation.reference_model.document_frame()
        for name, rows, extra in (("Depth", 9, 4), ("Thickness", 5, 1), ("CD", 8, 3)):
            with self.subTest(case=name):
                _reference, incoming = paste_case(self.window, name, rows, extra)
                expected = self.window.raw_model.document_frame()
                pd.testing.assert_frame_equal(expected.iloc[:rows, :len(incoming.columns)], incoming.astype(str))
                pd.testing.assert_frame_equal(correlation.raw_model.document_frame(), expected)
                pd.testing.assert_frame_equal(correlation.reference_model.document_frame(), manual_ref)
                actual = map_window.model.document_frame()
                self.assertTrue(set(expected.columns) <= set(actual.columns),
                                f"Case {name} dropped Raw columns: {set(expected.columns) - set(actual.columns)}")
                pd.testing.assert_frame_equal(actual.loc[:, expected.columns], expected)

    def test_same_named_ref_raw_can_analyze_after_an_intermediate_incompatible_case(self):
        reference = pd.DataFrame({"CD": ["11.000", "12.000", "13.000", "14.000"]})
        initial = pd.DataFrame({"Wafer ID": ["W1"] * 4, "Die Seq": [1, 2, 3, 4],
                                "Other CD": ["1.000", "2.000", "3.000", "4.000"]})
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(initial)
        self.window._populate_mappings([ParameterMapping("CD", "CD", "Other CD")])
        self.window.run_analysis()
        replacement = initial.rename(columns={"Other CD": "CD"}).assign(CD=["2.000", "3.000", "7.000", "9.000"])
        with patch.object(SheetView, "mismatched_paste_choice", return_value="keep"):
            for frame, view in ((reference, self.window.reference_view),
                                (replacement, self.window.raw_view)):
                APP.clipboard().setText(frame.to_csv(sep="\t", index=False, lineterminator="\n"))
                view.setCurrentIndex(view.model().index(0, 0))
                view.paste()
        APP.processEvents()
        self.assertTrue(self.window.analyze_button.isEnabled(), self.window.status.text())
        result = self.window.run_analysis()
        self.assertEqual(result.summary["Valid pairs"].tolist(), [4])

    def test_pasting_raw_identity_into_incomplete_ref_enables_ref_plots(self):
        child = CorrelationWindow()
        self.addCleanup(lambda: self.close_child(child))
        child.set_reference_table(pd.DataFrame({"Wafer ID": [""] * 6, "Die Seq": [""] * 6,
                                                "CD": ["10.000", "bad", "", "13.000", "14.000", "15.000"]}))
        raw = pd.DataFrame({"Wafer ID": ["W1"] * 6, "Die Seq": [1, 2, 3, 4, 5, 6],
                            "CD": ["1.000", "2.000", "3.000", "4.000", "5.000", "6.000"]})
        child.set_table(raw, "Synthetic Raw")
        identity = raw[["Wafer ID", "Die Seq"]]
        APP.clipboard().setText(identity.to_csv(sep="\t", index=False, lineterminator="\n"))
        child.reference_sheet.setCurrentIndex(child.reference_model.index(0, 0))
        with patch.object(SheetView, "mismatched_paste_choice", return_value="keep"):
            child.reference_sheet.paste()
        child.recognize()
        self.assertTrue(child.reference_measurements)
        self.assertTrue(child.selected(child.reference_wafer_list), "Newly recognized Ref identities must not stay unchecked")
        self.assertIn("CD", child.selected(child.reference_parameter_list))
        child.correlation_page.selector.selectAll()
        child.correlation_page.draw_plot()
        self.assertTrue(child.correlation_page.ready, child.correlation_page.status.text())
        child.sequence_page.selector.selectAll()
        child.sequence_page.draw_plot()
        self.assertTrue(child.sequence_page.ready, child.sequence_page.status.text())
        self.assertTrue(any(group.get("source", {}).get("name") == "Reference" for group in child.sequence_page.groups))

    def test_single_column_numeric_clipboard_does_not_run_delimiter_inference(self):
        text = "CD\n1.00000000001\n2.00000000002\n3.00000000003\n"
        with patch("csv.Sniffer.sniff", side_effect=AssertionError("No delimiter exists to infer")):
            self.assertEqual(clipboard_rows(text), [["CD"], ["1.00000000001"], ["2.00000000002"], ["3.00000000003"]])

    def test_wrong_offset_paste_cut_and_correct_paste_does_not_leave_phantom_rows(self):
        for source in ("reference", "raw"):
            with self.subTest(source=source):
                reference = pd.DataFrame({"CD": ["11.000", "12.000", "13.000", "14.000"]})
                raw = pd.DataFrame({"Wafer ID": ["W1"] * 4, "Die Seq": [1, 2, 3, 4], "CD": ["1", "2", "3", "4"]})
                self.window.set_reference_frame(reference)
                self.window.set_raw_frame(raw)
                self.window._populate_mappings([ParameterMapping("CD", "CD", "CD")])
                self.window.run_analysis()
                view = self.window.reference_view if source == "reference" else self.window.raw_view
                model = self.window.reference_model if source == "reference" else self.window.raw_model
                frame = reference if source == "reference" else raw
                text = frame.to_csv(sep="\t", index=False, lineterminator="\n")
                APP.clipboard().setText(text)
                view.setCurrentIndex(model.index(1, 1))
                view.paste()
                self.assertTrue(view.cut())
                APP.clipboard().setText(text)
                view.setCurrentIndex(model.index(0, 0))
                with patch.object(SheetView, "mismatched_paste_choice", return_value="keep"):
                    view.paste()
                self.assertEqual(model.document_frame().shape, frame.shape)
                self.assertTrue(self.window.analyze_button.isEnabled(), self.window.status.text())
                self.assertEqual(self.window.run_analysis().summary["Valid pairs"].tolist(), [4])

    def test_cut_after_offset_paste_restores_extent_on_undo_and_keeps_original_blank_rows(self):
        model = SheetModel()
        view = SheetView(model)
        self.addCleanup(view.deleteLater)
        self.addCleanup(model.deleteLater)
        model.load(pd.DataFrame({"CD": ["1.000", "2.000", "", ""]}))
        before = model.document_frame()
        APP.clipboard().setText("CD\n11.000\n12.000\n13.000\n14.000\n")
        view.setCurrentIndex(model.index(1, 1))
        view.paste()
        pasted = model.document_frame()
        self.assertEqual(len(pasted), 5)
        self.assertTrue(view.cut())
        cut = model.document_frame()
        self.assertEqual(len(cut), 4)
        pd.testing.assert_frame_equal(cut, before)
        model.undo.undo()
        pd.testing.assert_frame_equal(model.document_frame(), pasted)
        model.undo.redo()
        pd.testing.assert_frame_equal(model.document_frame(), before)

    def test_shorter_ref_with_explicit_identity_can_draw_without_a_row_count_gate(self):
        child = CorrelationWindow()
        self.addCleanup(lambda: self.close_child(child))
        raw = pd.DataFrame({"Wafer ID": ["W1"] * 4, "Die Seq": [1, 2, 3, 4],
                            "CD": [1, 2, 3, 4], "Depth": [2, 4, 6, 8]})
        reference = raw.iloc[:3].assign(CD=[11, 12, 13], Depth=[4, 6, 8])
        child.set_table(raw, "Synthetic Raw")
        child.set_reference_table(reference)
        child.recognize()
        child.check_all(child.reference_wafer_list, True)
        child.check_all(child.reference_parameter_list, True)
        self.assertIn("Reference", {source["name"] for source in child.selection.get("sources", ())})
        # Independent Ref plots do not require cross-source row pairing. Keep
        # the existing protection against correlating unequal source extents.
        child.check_all(child.wafer_list, False)
        child.correlation_page.selector.selectAll()
        child.correlation_page.draw_plot()
        self.assertTrue(child.correlation_page.ready, child.correlation_page.status.text())
        child.sequence_page.selector.selectAll()
        child.sequence_page.draw_plot()
        self.assertTrue(child.sequence_page.ready, child.sequence_page.status.text())
        self.assertTrue(any(group.get("source", {}).get("name") == "Reference" for group in child.sequence_page.groups))
        pd.testing.assert_frame_equal(child.reference_model.document_frame(), reference.astype(str))

    def test_manual_ref_wafer_selection_draws_mixed_numeric_values_after_identity_paste(self):
        child = CorrelationWindow()
        self.addCleanup(lambda: self.close_child(child))
        child.set_reference_table(pd.DataFrame({"Wafer ID": [""] * 6, "Die Seq": [""] * 6,
                                                "CD": ["10.000", "bad", "", "13.000", "14.000", "15.000"]}))
        raw = pd.DataFrame({"Wafer ID": ["W1"] * 6, "Die Seq": [1, 2, 3, 4, 5, 6],
                            "CD": ["1.000", "2.000", "3.000", "4.000", "5.000", "6.000"]})
        child.set_table(raw, "Synthetic Raw")
        APP.clipboard().setText(raw[["Wafer ID", "Die Seq"]].to_csv(sep="\t", index=False, lineterminator="\n"))
        child.reference_sheet.setCurrentIndex(child.reference_model.index(0, 0))
        with patch.object(SheetView, "mismatched_paste_choice", return_value="keep"):
            child.reference_sheet.paste()
        child.recognize()
        child.check_all(child.reference_wafer_list, True)
        child.check_all(child.reference_parameter_list, True)
        self.assertIn("CD", child.selected(child.reference_parameter_list))
        child.correlation_page.selector.selectAll()
        child.correlation_page.draw_plot()
        self.assertTrue(child.correlation_page.ready, child.correlation_page.status.text())
        child.sequence_page.selector.selectAll()
        child.sequence_page.draw_plot()
        self.assertTrue(child.sequence_page.ready, child.sequence_page.status.text())

    def test_user_source_column_does_not_block_reference_and_raw_plots(self):
        child = CorrelationWindow()
        self.addCleanup(lambda: self.close_child(child))
        raw = pd.DataFrame({"Wafer ID": ["W1"] * 4, "Die Seq": [1, 2, 3, 4],
                            "Source": ["Raw file"] * 4, "CD": [1, 2, 3, 4], "Thickness": [2, 4, 6, 8]})
        reference = raw.assign(Source="Ref file", CD=[11, 12, 13, 14], Thickness=[4, 6, 8, 10])
        child.set_table(raw, "Synthetic Raw")
        child.set_reference_table(reference)
        child.correlation_page.selector.selectAll()
        child.correlation_page.draw_plot()
        self.assertTrue(child.correlation_page.ready, child.correlation_page.status.text())
        self.assertEqual(child.reference_model.document_frame()["Source"].tolist(), ["Ref file"] * 4)
        self.assertEqual(child.raw_model.document_frame()["Source"].tolist(), ["Raw file"] * 4)

    def test_reference_identity_auto_detection_does_not_reset_an_explicit_empty_group_choice(self):
        child = CorrelationWindow()
        self.addCleanup(lambda: self.close_child(child))
        frame = pd.DataFrame({"Wafer ID": ["W1"] * 4, "Die Seq": [1, 2, 3, 4],
                              "CD": [1, 2, 3, 4], "Depth": [2, 4, 6, 8]})
        child.set_reference_table(frame)
        child.reference_group_checks["Wafer ID"].setChecked(False)
        self.assertFalse(child.reference_measurements)
        child.reference_model.edit({(1, 2): "1.00001"})
        child.recognize()
        self.assertFalse(child.reference_group_checks["Wafer ID"].isChecked())
        self.assertFalse(child.reference_measurements)

    def test_duplicate_ref_headers_do_not_prevent_valid_raw_only_plots(self):
        child = CorrelationWindow()
        self.addCleanup(lambda: self.close_child(child))
        raw = pd.DataFrame({"Wafer ID": ["W1"] * 4, "Die Seq": [1, 2, 3, 4],
                            "CD": [1, 2, 3, 4], "Thickness": [2, 4, 6, 8]})
        child.set_table(raw, "Synthetic Raw")
        child.set_reference_table(raw.assign(CD=[11, 12, 13, 14]))
        child.reference_model.load(pd.DataFrame([[1, 2]] * 4, columns=["Bad", "Bad"]))
        child.recognize()
        child.correlation_page.selector.selectAll()
        child.correlation_page.draw_plot()
        self.assertTrue(child.correlation_page.ready, child.correlation_page.status.text())
        child.sequence_page.selector.selectAll()
        child.sequence_page.draw_plot()
        self.assertTrue(child.sequence_page.ready, child.sequence_page.status.text())
        self.assertTrue(all(source["name"] == "Raw Data" for source in child.selection["sources"]))
        self.assertIn("Fix duplicate", child.reference_footer.text())

    def test_failed_child_refresh_is_not_remembered_as_success(self):
        paste_case(self.window, "CD", 6)
        child = self.window.open_stage_workspace("preview")
        child.set_copy_from_wkb(True)
        self.window._stage_sync_inputs = None
        with patch.object(self.window, "_refresh_stage_workspace", side_effect=[ValueError("Synthetic transient failure"), None]) as probe:
            self.window.sync_stage_windows()
            self.window.sync_stage_windows()
            self.assertEqual(probe.call_count, 2, "An unsuccessful source update must remain eligible for retry")

    @staticmethod
    def close_child(child):
        child.document.force_close = True
        child.close()
        child.deleteLater()
        APP.processEvents()
