"""Observable clipboard-update feedback, through the editable sheet seam."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
import pandas as pd

from metrology_app.sheet import SheetModel, SheetView


APP = QApplication.instance() or QApplication([])


class PasteFeedbackTests(unittest.TestCase):
    def test_keyboard_paste_and_undo_keep_dirty_and_formal_source_roundtrip_correct(self):
        from PyQt6.QtTest import QTest
        from metrology_app.matching_window import MatchingWindow
        from metrology_app.workspace_store import load_workspace
        window = MatchingWindow()
        with tempfile.TemporaryDirectory() as scratch:
            try:
                window.set_reference_frame(pd.DataFrame({"CD Reference": [3., 5., 7.]}))
                window.set_raw_frame(pd.DataFrame({"CD": ["1.000", "2.000", "3.000"]}))
                window.run_analysis()
                path = Path(scratch) / "source.wkb"
                window.save_workbook(path)
                self.assertFalse(window.document.is_dirty())
                window.raw_view.setCurrentIndex(window.raw_view.model().index(1, 0))
                APP.clipboard().setText("4.000")
                QTest.keyClick(window.raw_view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
                self.assertTrue(window.document.is_dirty())
                QTest.keyClick(window.raw_view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
                window.run_analysis()
                self.assertFalse(window.document.is_dirty())
                self.assertEqual(load_workspace(path).frames["raw"].CD.tolist(), ["1.000", "2.000", "3.000"])
                # Formal Save still validates and retains an invalid-header draft.
                window.raw_model.setData(window.raw_model.index(0, 1), "CD")
                self.assertTrue(window.document.is_dirty())
                window.save_workbook(path)
                reopened = load_workspace(path)
                self.assertEqual(reopened.frames["raw"].columns.tolist(), ["CD", "CD"])
                self.assertTrue(reopened.states["match"]["draft"])
            finally:
                window.document.force_close = True
                window.close()
                window.deleteLater()
                APP.processEvents()

    def test_explicit_run_after_keyboard_paste_or_undo_uses_latest_values_without_late_overwrite(self):
        from PyQt6.QtTest import QTest
        from metrology_app.matching_window import MatchingWindow
        window = MatchingWindow()
        try:
            window.set_reference_frame(pd.DataFrame({"CD Reference": [3., 5., 7.]}))
            window.set_raw_frame(pd.DataFrame({"CD": ["1.000", "2.000", "3.000"]}))
            window.run_analysis()
            window.raw_view.setCurrentIndex(window.raw_view.model().index(1, 0))
            APP.clipboard().setText("4.000")
            QTest.keyClick(window.raw_view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(window.raw_model.document_frame().CD.tolist(), ["4.000", "2.000", "3.000"])
            result = window.run_analysis()
            self.assertAlmostEqual(result.card("CD").slope, -1)
            self.assertAlmostEqual(result.card("CD").intercept, 8)
            QTest.keyClick(window.raw_view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(window.raw_model.document_frame().CD.tolist(), ["1.000", "2.000", "3.000"])
            result = window.run_analysis()
            self.assertAlmostEqual(result.card("CD").slope, 2)
            self.assertAlmostEqual(result.card("CD").intercept, 1)
            QTest.qWait(120)
            self.assertEqual(window.result.series("CD")["Raw"].tolist(), [1., 2., 3.])
            self.assertAlmostEqual(window.result.card("CD").slope, 2)
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_cached_sources_keep_whitespace_blank_rows_and_copy_on_write_semantics(self):
        for copy_on_write in (False, True):
            with self.subTest(copy_on_write=copy_on_write), pd.option_context("mode.copy_on_write", copy_on_write):
                model = SheetModel()
                model.load_matrix([["CD"], ["1.000"]])
                accepted = model.document_frame()
                model.frame()
                model.setData(model.index(1, 0), "2.1000")
                self.assertEqual(model.frame().CD.tolist(), ["2.1000"])
                self.assertEqual(accepted.CD.tolist(), ["1.000"])
                model.setData(model.index(1, 0), "   ")
                self.assertTrue(model.frame().empty)
                self.assertEqual(model.document_frame().CD.tolist(), ["   "])
                model.undo.undo()
                self.assertEqual(model.frame().CD.tolist(), ["2.1000"])
                model.undo.undo()
                pd.testing.assert_frame_equal(model.document_frame(), accepted)

    def test_identical_paste_confirms_no_changes_without_an_edit_or_highlights(self):
        from metrology_app.sheet import PasteFeedbackBar

        model = SheetModel()
        matrix = [["Wafer ID", "CD"], ["001", "1.00"]]
        model.load_matrix(matrix)
        view = SheetView(model)
        bar = PasteFeedbackBar(view)
        self.addCleanup(view.deleteLater)
        self.addCleanup(bar.deleteLater)
        before, revision = model.snapshot(), model.revision
        view.setCurrentIndex(model.index(0, 0))
        APP.clipboard().setText("Wafer ID\tCD\n001\t1.00")
        view.paste()
        self.assertIn("No changes", bar.message.text())
        self.assertFalse(bar.isHidden())
        self.assertFalse(hasattr(bar, "show_changes_button"))
        self.assertEqual(model.paste_report.changes, {})
        self.assertEqual(model.snapshot(), before)
        self.assertEqual(model.revision, revision)
        self.assertFalse(model.undo.canUndo())
        self.assertIsNone(model.data(model.index(1, 1), Qt.ItemDataRole.BackgroundRole))

    def test_changed_paste_uses_native_selection_without_extra_colours_in_both_themes(self):
        from PyQt6.QtGui import QColor

        for theme, colour in (("light", "#d97706"), ("dark", "#fbbf24")):
            with self.subTest(theme=theme), patch("metrology_app.sheet.get_settings", return_value={"theme": theme}):
                model = SheetModel()
                model.load_matrix([["CD"], ["1.00"]])
                view = SheetView(model)
                view.resize(320, 180)
                view.show()
                APP.processEvents()
                view.setCurrentIndex(model.index(1, 0))
                APP.clipboard().setText("1.25")
                view.paste()
                self.assertTrue(view.selectionModel().isSelected(model.index(1, 0)))
                self.assertIsNone(model.data(model.index(1, 0), Qt.ItemDataRole.BackgroundRole))
                self.assertIsNone(view.clipboard_outline.bounds)
                self.assertEqual(model.cells[(1, 0)], "1.25")
                view.close()
                view.deleteLater()
                APP.processEvents()

    def test_replacement_receipt_counts_cleared_values_and_preserves_undo(self):
        model = SheetModel()
        model.load_matrix([["ID", "CD", "Old"], ["001", "1.00", "9"], ["002", "2.00", "8"]])
        before = model.snapshot()
        view = SheetView(model)
        self.addCleanup(view.deleteLater)
        APP.clipboard().setText("ID\tCD\n001\t1.00")
        view.paste(replace=True)
        report = model.paste_report
        self.assertEqual(report.changes, {(0, 2): ("Old", ""), (1, 2): ("9", ""),
                                          (2, 0): ("002", ""), (2, 1): ("2.00", ""),
                                          (2, 2): ("8", "")})
        self.assertEqual(report.rows_removed, 1)
        self.assertIn("Old (3)", report.summary)
        model.undo.undo()
        self.assertEqual(model.snapshot(), before)
        self.assertIsNone(model.paste_report)
        model.undo.redo()
        self.assertEqual(model.document_frame().values.tolist(), [["001", "1.00"]])
        self.assertIsNone(model.paste_report)

    def test_replacement_of_blank_trailing_rows_reports_structure_not_false_value_edits(self):
        model = SheetModel()
        model.load_matrix([["ID"], ["001"], [""]])
        view = SheetView(model)
        self.addCleanup(view.deleteLater)
        before = model.snapshot()
        APP.clipboard().setText("ID\n001")
        view.paste(replace=True)
        self.assertEqual(model.paste_report.changes, {})
        self.assertEqual(model.paste_report.rows_removed, 1)
        self.assertIn("1 row removed", model.paste_report.summary)
        self.assertNotIn("No changes", model.paste_report.summary)
        self.assertEqual(model.document_frame().ID.tolist(), ["001"])
        model.undo.undo()
        self.assertEqual(model.snapshot(), before)

    def test_tooltip_escapes_markup_but_clipboard_and_document_keep_literal_strings(self):
        model = SheetModel()
        model.load_matrix([["ID", "Note"], ["001", "<old> & 1"]])
        view = SheetView(model)
        self.addCleanup(view.deleteLater)
        view.setCurrentIndex(model.index(1, 1))
        APP.clipboard().setText('"<b>literal & text</b>\nsecond line"')
        view.paste()
        literal = "<b>literal & text</b>\nsecond line"
        self.assertEqual(model.cells[(1, 1)], literal)
        self.assertEqual(model.document_frame().iloc[0].tolist(), ["001", literal])
        tooltip = model.data(model.index(1, 1), Qt.ItemDataRole.ToolTipRole)
        self.assertIn("&lt;old&gt; &amp; 1", tooltip)
        self.assertIn("&lt;b&gt;literal &amp; text&lt;/b&gt;", tooltip)
        self.assertNotIn("<b>literal", tooltip)

    def test_filtered_paste_highlights_source_rows_after_sort_and_reports_hidden_changes(self):
        from metrology_app.match_group_ui import ProjectedSheetModel
        from metrology_app.sheet import PasteFeedbackBar

        model = SheetModel()
        model.load_matrix([["ID", "CD"], ["001", "1.00"], ["002", "2.00"], ["003", "3.00"]])
        proxy = ProjectedSheetModel(model)
        proxy.set_rows([2, 0])
        view = SheetView(proxy)
        bar = PasteFeedbackBar(view)
        self.addCleanup(view.deleteLater)
        self.addCleanup(bar.deleteLater)
        view.setCurrentIndex(proxy.index(2, 1))
        APP.clipboard().setText("1.20")
        view.paste()
        self.assertEqual(model.paste_report.changes, {(1, 1): ("1.00", "1.20")})
        proxy.set_rows([0, 2])
        self.assertFalse(hasattr(bar, "show_changes_button"))
        self.assertIn("Before: 1.00", proxy.data(proxy.index(1, 1), Qt.ItemDataRole.ToolTipRole))
        self.assertEqual(model.cells[(2, 1)], "2.00")
        proxy.set_rows([2])
        self.assertIn("1 cell changed", bar.message.text())
        self.assertEqual(proxy.rows, (3,))
        model.undo.undo()
        self.assertEqual(model.cells[(1, 1)], "1.00")
        self.assertTrue(bar.isHidden())

    def test_dismissal_clears_only_the_receipt_and_next_edit_invalidates_old_differences(self):
        from metrology_app.sheet import PasteFeedbackBar

        model = SheetModel()
        model.load_matrix([["CD"], ["1.00"]])
        view = SheetView(model)
        bar = PasteFeedbackBar(view)
        self.addCleanup(view.deleteLater)
        self.addCleanup(bar.deleteLater)
        view.setCurrentIndex(model.index(1, 0))
        APP.clipboard().setText("2.00")
        view.paste()
        revision, snapshot, undo_index = model.revision, model.snapshot(), model.undo.index()
        bar.clear_button.click()
        self.assertFalse(hasattr(bar, "show_changes_button"))
        self.assertTrue(bar.isHidden())
        self.assertEqual((model.revision, model.snapshot(), model.undo.index()),
                         (revision, snapshot, undo_index))
        APP.clipboard().setText("3.00")
        view.paste()
        model.setData(model.index(1, 0), "4.00")
        self.assertTrue(bar.isHidden())
        self.assertIsNone(model.paste_report)

    def test_cancelled_or_out_of_bounds_paste_keeps_the_previous_receipt_and_values(self):
        from metrology_app.match_group_ui import ProjectedSheetModel

        model = SheetModel()
        model.load_matrix([["ID", "CD"], ["001", "1.00"], ["002", "2.00"]])
        view = SheetView(model)
        self.addCleanup(view.deleteLater)
        view.setCurrentIndex(model.index(1, 1))
        APP.clipboard().setText("1.25")
        view.paste()
        before, report = model.snapshot(), model.paste_report
        view.setCurrentIndex(model.index(0, 0))
        APP.clipboard().setText("ID\n001")
        with patch.object(view, "mismatched_paste_choice", return_value="cancel"):
            view.paste()
        self.assertEqual(model.snapshot(), before)
        self.assertIs(model.paste_report, report)
        proxy = ProjectedSheetModel(model)
        proxy.set_rows([0])
        view.setModel(proxy)
        view.setCurrentIndex(proxy.index(1, 1))
        APP.clipboard().setText("4.00\n5.00")
        with self.assertRaisesRegex(ValueError, "within displayed rows"):
            view.paste()
        self.assertEqual(model.snapshot(), before)
        self.assertIs(model.paste_report, report)

    def test_matching_raw_toolbar_and_grid_show_stage_specific_feedback(self):
        from metrology_app.matching_window import MatchingWindow

        window = MatchingWindow()
        try:
            window.set_reference_frame(pd.DataFrame({"CD Reference": ["1", "2"]}))
            window.set_raw_frame(pd.DataFrame({"CD": ["1.00", "2.00"]}))
            APP.clipboard().setText("CD\n1.00\n2.50")
            window.paste_raw()
            self.assertIn("1 cell changed", window.raw_paste_feedback.message.text())
            self.assertEqual(window.raw_model.paste_report.changes, {(2, 0): ("2.00", "2.50")})
            self.assertEqual(window.raw_frame.CD.tolist(), ["1.00", "2.50"])

            window.result_mode.setCurrentText("Final")
            self.assertTrue(window.raw_paste_feedback.isHidden())
            window.set_raw_frame(pd.DataFrame({"CD": ["1.00", "2.00"]}))
            window.raw_view.setCurrentIndex(window.raw_view.model().index(1, 0))
            APP.clipboard().setText("1.10")
            window.raw_view.paste()
            self.assertEqual(window.final_raw_model.paste_report.changes, {(1, 0): ("1.00", "1.10")})
            self.assertEqual(window.final_match_frame.CD.tolist(), ["1.10", "2.00"])
            window.result_mode.setCurrentText("Preview")
            self.assertIn("1 cell changed", window.raw_paste_feedback.message.text())
            self.assertIs(window.raw_view.paste_report, window.raw_model.paste_report)
            window.raw_model.undo.undo()  # Toolbar replacement retains its existing load/Undo semantics.
            self.assertEqual(window.raw_frame.CD.tolist(), ["1.00", "2.50"])
        finally:
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_workspace_toolbar_receipt_does_not_leak_into_later_file_load(self):
        from metrology_app.window import MainWindow

        window = MainWindow()
        try:
            window.set_table(pd.DataFrame({"Wafer ID": ["001"], "CD": ["1.00"]}), "Fixture")
            APP.clipboard().setText("Wafer ID\tCD\n001\t1.25")
            window.paste_table()
            self.assertIn("CD (1)", window.paste_feedback.message.text())
            self.assertEqual(window.model.cells[(1, 1)], "1.25")
            window.set_table(pd.DataFrame({"Wafer ID": ["002"], "CD": ["2.00"]}), "New file")
            self.assertTrue(window.paste_feedback.isHidden())
            self.assertIsNone(window.model.paste_report)
        finally:
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_receipt_retains_changed_column_summary_without_navigation_control(self):
        from metrology_app.sheet import PasteFeedbackBar

        model = SheetModel()
        model.load_matrix([["Wafer ID", "Keep", "Value"], ["001", "same", "2.10"]])
        view = SheetView(model)
        bar = PasteFeedbackBar(view)
        self.addCleanup(view.deleteLater)
        self.addCleanup(bar.deleteLater)
        self.assertTrue(bar.isHidden())
        view.setCurrentIndex(model.index(1, 2))
        APP.clipboard().setText("3.40")
        view.paste()

        self.assertFalse(bar.isHidden())
        self.assertIn("1 cell changed", bar.message.text())
        self.assertIn("Value (1)", bar.message.text())
        view.setCurrentIndex(model.index(1, 0))
        self.assertFalse(hasattr(bar, "show_changes_button"))
        self.assertEqual(view.currentIndex(), model.index(1, 0))
        model.undo.undo()
        self.assertTrue(bar.isHidden())

    def test_nearly_identical_paste_reports_only_exact_string_changes(self):
        model = SheetModel()
        model.load_matrix([["Wafer ID", "Keep", "Value"],
                           ["001", "same", "2.10"], ["002", "same", "3.20"]])
        view = SheetView(model)
        self.addCleanup(view.deleteLater)
        view.setCurrentIndex(model.index(0, 0))
        APP.clipboard().setText("Wafer ID\tKeep\tValue\n001\tsame\t2.100\n002\tsame\t4.20")

        view.paste()

        report = model.paste_report
        self.assertEqual(report.changes, {(1, 2): ("2.10", "2.100"),
                                          (2, 2): ("3.20", "4.20")})
        self.assertIn("2 cells changed", report.summary)
        self.assertIn("Value (2)", report.summary)
        self.assertEqual(model.document_frame().iloc[0].tolist(), ["001", "same", "2.100"])
        self.assertEqual(view.currentIndex(), model.index(0, 0))
        self.assertIn("2.10", model.data(model.index(1, 2), Qt.ItemDataRole.ToolTipRole))
        model.undo.undo()
        self.assertEqual(model.cells[(1, 2)], "2.10")
        self.assertIsNone(model.paste_report)


if __name__ == "__main__":
    unittest.main()
