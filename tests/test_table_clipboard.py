"""Clipboard workflow examples: feedback is presentation, cuts are undoable edits."""
import os
import unittest
from time import perf_counter
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PyQt6.QtCore import QItemSelection, QItemSelectionModel, Qt
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication, QToolButton

from metrology_app.sheet import PasteFeedbackBar, SheetModel, SheetView

APP = QApplication.instance() or QApplication([])


class TableClipboardTests(unittest.TestCase):
    def make_view(self, model=None):
        model = model or SheetModel()
        if not model.cells:
            model.load_matrix([["ID", "Value"], ["001", "1.000"], ["002", "2.100"]])
        view = SheetView(model)
        view.resize(420, 220)
        view.show()
        APP.processEvents()
        self.addCleanup(view.deleteLater)
        self.addCleanup(view.close)
        return model, view

    def select(self, view, top, left, bottom, right):
        model = view.model()
        view.selectionModel().select(
            QItemSelection(model.index(top, left), model.index(bottom, right)),
            QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def test_copy_animates_the_range_without_editing_and_escape_cancels_only_feedback(self):
        model, view = self.make_view()
        self.select(view, 1, 0, 2, 1)
        before, revision = model.snapshot(), model.revision
        QTest.keyClick(view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(APP.clipboard().text(), "001\t1.000\n002\t2.100\n")
        self.assertEqual(view.clipboard_outline.bounds, (1, 0, 2, 1))
        self.assertEqual(view.clipboard_outline.mode, "copy")
        initial_phase = view.clipboard_outline.phase
        start = perf_counter()
        image = view.viewport().grab().toImage()
        # Wait for the actual timer event, not wall time alone. Prior storage
        # teardown can occupy qWait's last event turn: an overdue timeout then
        # has not been dispatched even though the overlay/timer remain alive.
        ticks = QSignalSpy(view.clipboard_outline.timer.timeout)
        self.assertTrue(ticks.wait(160), "copy animation timer did not fire")
        self.assertNotEqual(view.viewport().grab().toImage(), image, {
            "elapsed_ms": (perf_counter() - start) * 1000,
            "phase": (initial_phase, view.clipboard_outline.phase),
            "bounds": view.clipboard_outline.bounds, "mode": view.clipboard_outline.mode,
            "timer": view.clipboard_outline.timer.isActive(),
            "visible": view.clipboard_outline.isVisible(), "updates": view.updatesEnabled(),
            "viewport": view.viewport().size(), "outline": view.clipboard_outline.geometry(),
            "revision": (revision, model.revision), "clipboard": APP.clipboard().text(),
        })
        self.assertEqual((model.snapshot(), model.revision), (before, revision))
        self.assertFalse(model.undo.canUndo())
        QTest.keyClick(view, Qt.Key.Key_Escape)
        self.assertIsNone(view.clipboard_outline.bounds)
        self.assertFalse(view.clipboard_outline.timer.isActive())
        self.assertEqual(model.snapshot(), before)
        self.assertEqual(APP.clipboard().text(), "001\t1.000\n002\t2.100\n")

    def test_cut_copies_before_clearing_as_one_undoable_operation(self):
        model, view = self.make_view()
        self.select(view, 1, 1, 2, 1)
        before = model.snapshot()
        QTest.keyClick(view, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(APP.clipboard().text(), "1.000\n2.100\n")
        self.assertEqual(model.cells.get((1, 1), ""), "")
        self.assertEqual(model.cells.get((2, 1), ""), "")
        self.assertEqual(model.cells[(1, 0)], "001")
        self.assertEqual(model.undo.count(), 1)
        self.assertEqual(view.clipboard_outline.mode, "copy")
        self.assertEqual(view.clipboard_outline.bounds, (1, 1, 2, 1))
        QTest.keyClick(view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(model.snapshot(), before)
        self.assertIsNone(view.clipboard_outline.bounds)
        QTest.keyClick(view, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(model.cells.get((1, 1), ""), "")

    def test_failed_copy_does_not_clear_cut_source(self):
        model, view = self.make_view()
        self.select(view, 1, 0, 2, 1)
        before = model.snapshot()
        with patch.object(view, "copy", return_value=False):
            view.cut()
        self.assertEqual(model.snapshot(), before)
        self.assertFalse(model.undo.canUndo())

    def test_cut_of_filtered_sorted_rows_preserves_hidden_rows_and_undo_identity(self):
        from metrology_app.match_group_ui import ProjectedSheetModel
        model = SheetModel()
        model.load_matrix([["ID", "CD"], ["001", "1.000"], ["002", "2.000"], ["003", "3.000"]])
        proxy = ProjectedSheetModel(model)
        proxy.set_rows([2, 0])
        _, view = self.make_view(proxy)
        self.select(view, 1, 1, 2, 1)
        before = model.snapshot()
        view.cut()
        self.assertEqual(APP.clipboard().text(), "3.000\n1.000\n")
        self.assertEqual(model.cells[(2, 1)], "2.000")
        self.assertNotIn((1, 1), model.cells)
        self.assertNotIn((3, 1), model.cells)
        model.undo.undo()
        self.assertEqual(model.snapshot(), before)
        self.assertEqual(proxy.rows, (3, 1))

    def test_derived_order_cells_are_copyable_but_a_mixed_cut_is_rejected(self):
        from metrology_app.match_group_ui import OrderModel
        model = OrderModel()
        model.load_matrix([["TestFlag"], ["1"], ["2"]])
        _, view = self.make_view(model)
        self.select(view, 1, 0, 2, 1)
        before = model.snapshot()
        APP.clipboard().setText("keep")
        view.cut()
        self.assertEqual(model.snapshot(), before)
        self.assertFalse(model.undo.canUndo())
        self.assertEqual(APP.clipboard().text(), "keep")
        self.select(view, 1, 0, 2, 0)
        view.cut()
        self.assertEqual(APP.clipboard().text(), "1\n2\n")
        model.undo.undo()
        self.assertEqual(model.snapshot(), before)

    def test_paste_selects_full_rectangle_without_extra_colour_or_border_even_when_values_match(self):
        model, view = self.make_view()
        bar = PasteFeedbackBar(view)
        self.addCleanup(bar.deleteLater)
        before, revision = model.snapshot(), model.revision
        view.setCurrentIndex(model.index(1, 0))
        APP.clipboard().setText("001\t1.000\n002\t2.100")
        QTest.keyClick(view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        self.assertIsNone(view.clipboard_outline.bounds)
        self.assertFalse(view.clipboard_outline.timer.isActive())
        self.assertTrue(view.selectionModel().isSelected(model.index(2, 1)))
        self.assertEqual((model.snapshot(), model.revision), (before, revision))
        self.assertIn("No changes", bar.message.text())
        self.assertNotIn("Show changes", [button.text() for button in bar.findChildren(QToolButton)])
        self.assertIsNone(model.data(model.index(1, 1), Qt.ItemDataRole.BackgroundRole))

    def test_reload_model_switch_hidden_view_and_clipboard_replacement_stop_animation(self):
        model, view = self.make_view()
        self.select(view, 1, 0, 2, 1)
        view.copy()
        view.hide()
        APP.processEvents()
        self.assertFalse(view.clipboard_outline.timer.isActive())
        view.show()
        APP.processEvents()
        self.assertTrue(view.clipboard_outline.timer.isActive())
        APP.clipboard().setText("different clipboard")
        self.assertIsNone(view.clipboard_outline.bounds)
        view.copy()
        model.load_matrix([["Other"], ["keep"]])
        self.assertIsNone(view.clipboard_outline.bounds)
        view.selectAll()
        view.copy()
        other = SheetModel()
        view.setModel(other)
        self.assertIsNone(view.clipboard_outline.bounds)

    def test_large_copy_and_animation_do_not_enumerate_selected_indexes_or_emit_edits(self):
        model = SheetModel()
        model.load(pd.DataFrame({f"C{i}": ["1.000"] * 8000 for i in range(33)}))
        _, view = self.make_view(model)
        self.select(view, 0, 0, 8000, 32)
        revision = model.revision
        with patch.object(view, "selectedIndexes", side_effect=AssertionError("per-cell selection scan")):
            view.copy()
            QTest.qWait(160)
            view.viewport().grab()
        self.assertEqual(model.revision, revision)
        self.assertFalse(model.undo.canUndo())

    def test_dynamic_cut_uses_shared_data_history_and_keeps_derived_row_read_only(self):
        from metrology_app.dynamic_page import DynamicPivotModel, DynamicPivotView
        source = SheetModel()
        source.load_matrix([["CD"], ["1.000"], ["2.000"]])
        model = DynamicPivotModel()
        model.set_frame(pd.DataFrame({1: [1., 2., 2.1213203436]}, index=["1", "2", "3 Sigma"]),
                        {(0, 0): (1, 0), (1, 0): (2, 0)}, source.edit)
        view = DynamicPivotView(model, source)
        self.addCleanup(view.deleteLater)
        self.select(view, 0, 0, 1, 0)
        before = source.snapshot()
        QTest.keyClick(view, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(APP.clipboard().text(), "1.000\n2.000\n")
        self.assertNotIn((1, 0), source.cells)
        self.assertEqual(source.undo.count(), 1)
        self.assertEqual(view.clipboard_outline.mode, "copy")
        QTest.keyClick(view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(source.snapshot(), before)
        self.select(view, 2, 0, 2, 0)
        view.cut()
        self.assertEqual(source.snapshot(), before)

    def test_select_all_excludes_reserved_and_blank_trailing_cells_not_internal_blanks(self):
        model = SheetModel()
        model.load_matrix([["ID", "Keep", "Value", ""],
                           ["001", "", "1.000", ""], ["002", "", "2.000", ""],
                           ["", "", "", ""]])
        _, view = self.make_view(model)
        revision, before = model.revision, model.snapshot()
        QTest.keyClick(view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        ranges = view.selectionModel().selection()
        self.assertEqual([(r.top(), r.left(), r.bottom(), r.right()) for r in ranges], [(0, 0, 2, 2)])
        self.assertTrue(view.selectionModel().isSelected(model.index(1, 1)))
        self.assertFalse(view.selectionModel().isSelected(model.index(3, 0)))
        self.assertEqual((model.revision, model.snapshot()), (revision, before))
        view.copy()
        self.assertEqual(APP.clipboard().text(), "ID\tKeep\tValue\n001\t\t1.000\n002\t\t2.000\n")

    def test_select_all_in_projection_selects_visible_data_and_empty_sheet_selects_nothing(self):
        from metrology_app.match_group_ui import ProjectedSheetModel
        model = SheetModel()
        model.load_matrix([["ID", "CD"], ["001", "1.000"], ["002", "2.000"]])
        proxy = ProjectedSheetModel(model)
        proxy.set_rows([1])
        _, view = self.make_view(proxy)
        view.selectAll()
        self.assertEqual([(r.top(), r.left(), r.bottom(), r.right())
                          for r in view.selectionModel().selection()], [(0, 0, 1, 1)])
        empty = SheetModel()
        view.setModel(empty)
        view.setCurrentIndex(empty.index(0, 0))
        view.selectAll()
        self.assertFalse(view.selectionModel().hasSelection())

    def test_known_paste_rectangle_is_reported_without_reconstructing_it_from_differences(self):
        model = SheetModel()
        model.load_matrix([["ID", "Keep", "Value"], ["001", "same", "1.000"], ["002", "same", "2.000"]])
        model.paste_cells({(1, 2): "1.100"}, bounds=(0, 0, 2, 2))
        self.assertEqual(model.paste_report.bounds, (0, 0, 2, 2))
        self.assertEqual(model.paste_report.changes, {(1, 2): ("1.000", "1.100")})

    def test_dynamic_cut_preserves_source_precision_and_trailing_zeroes_in_clipboard(self):
        from metrology_app.dynamic_page import DynamicPivotModel, DynamicPivotView
        source = SheetModel()
        literal = "1.2345678901234500"
        source.load_matrix([["CD"], [literal], ["2.00000"]])
        model = DynamicPivotModel()
        model.set_frame(pd.DataFrame({1: [float(literal), 2., 1.6]}, index=["1", "2", "3 Sigma"]),
                        {(0, 0): (1, 0), (1, 0): (2, 0)}, source.edit)
        view = DynamicPivotView(model, source)
        self.addCleanup(view.deleteLater)
        self.select(view, 0, 0, 1, 0)
        view.cut()
        self.assertEqual(APP.clipboard().text(), literal + "\n2.00000\n")
        source.undo.undo()
        self.assertEqual(source.cells[(1, 0)], literal)

    def test_read_only_result_tables_copy_with_feedback_without_cutting_calculated_values(self):
        from PyQt6.QtGui import QStandardItem, QStandardItemModel
        from PyQt6.QtWidgets import QTableView
        from metrology_app.table_clipboard import attach_copy_feedback
        model = QStandardItemModel(2, 1)
        model.setItem(0, 0, QStandardItem("1.000"))
        model.setItem(1, 0, QStandardItem("2.000"))
        view = QTableView()
        view.setModel(model)
        attach_copy_feedback(view)
        self.addCleanup(view.deleteLater)
        view.selectAll()
        QTest.keyClick(view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(APP.clipboard().text(), "1.000\n2.000\n")
        self.assertEqual(view.clipboard_outline.mode, "copy")
        QTest.keyClick(view, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(model.data(model.index(0, 0)), "1.000")
        model.setData(model.index(0, 0), "3.000")
        self.assertIsNone(view.clipboard_outline.bounds)


if __name__ == "__main__":
    unittest.main()
