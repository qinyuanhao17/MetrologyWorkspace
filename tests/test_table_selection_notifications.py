"""Selection signals stay complete; native accessibility needs only first cells."""
import unittest
from time import perf_counter
from unittest.mock import patch

import pandas as pd
from PyQt6.QtCore import QItemSelection, QItemSelectionModel, Qt
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication, QHeaderView, QStyleOptionHeader, QTableView

from metrology_app.match_group_ui import OrderModel, ProjectedSheetModel
from metrology_app.sheet import SheetModel, SheetView

APP = QApplication.instance() or QApplication([])


def rectangles(selection):
    return [(r.top(), r.left(), r.bottom(), r.right()) for r in selection]


class TableSelectionNotificationTests(unittest.TestCase):
    def view(self, model):
        view = SheetView(model)
        self.addCleanup(APP.processEvents)
        self.addCleanup(view.deleteLater)
        self.addCleanup(view.close)
        return view

    def test_native_first_cell_events_keep_delta_order_without_expanding_ranges(self):
        model = SheetModel()
        model.load(pd.DataFrame({f'C{i}': ['1.0000']*1000 for i in range(33)}))
        view = self.view(model)
        selected = QItemSelection(model.index(17, 4), model.index(900, 20))
        selected.select(model.index(1, 1), model.index(8, 3))
        deselected = QItemSelection(model.index(5, 0), model.index(12, 3))
        delivered = []
        original = QTableView.selectionChanged

        def native(receiver, new, old):
            delivered.append((rectangles(new), rectangles(old)))
            original(receiver, new, old)

        # This is the Qt accessibility boundary, not a model-change mock. Qt
        # itself only emits first-cell Add/Remove events for these deltas.
        with patch.object(QTableView, 'selectionChanged', new=native):
            view.selectionChanged(selected, deselected)
        self.assertEqual(delivered, [([(17, 4, 17, 4)], [(5, 0, 5, 0)])])
        self.assertEqual(rectangles(selected), [(17, 4, 900, 20), (1, 1, 8, 3)])

    def test_full_selection_model_signal_and_projection_mapping_are_retained(self):
        source = SheetModel()
        source.load(pd.DataFrame({'CD': ['1.000', '2.000', '3.000', '4.000'],
                                  'Depth': ['5.00', '', '7.00', '8.00']}))
        model = ProjectedSheetModel(source)
        model.set_rows([3, 1])
        view = self.view(model)
        signals = QSignalSpy(view.selectionModel().selectionChanged)
        view.selectAll()
        self.assertEqual(len(signals), 1)
        self.assertEqual(rectangles(signals[0][0]), [(0, 0, 2, 1)])
        self.assertEqual(rectangles(view.selectionModel().selection()), [(0, 0, 2, 1)])
        self.assertEqual(model.mapToSource(model.index(1, 0)).row(), 4)
        self.assertEqual(model.mapToSource(model.index(2, 0)).row(), 2)
        view.clearSelection()
        self.assertEqual(rectangles(signals[-1][1]), [(0, 0, 2, 1)])
        self.assertEqual(source.document_frame().CD.tolist(), ['1.000', '2.000', '3.000', '4.000'])
        self.assertTrue(source.undo.isClean())

    def test_custom_disabled_flags_keep_original_native_notification(self):
        class DisabledModel(SheetModel):
            def flags(self, index):
                return Qt.ItemFlag.NoItemFlags if index.row() == 0 else super().flags(index)
        model = DisabledModel()
        model.load(pd.DataFrame({'CD': ['1', '2']}))
        view = self.view(model)
        delta = QItemSelection(model.index(0, 0), model.index(2, 0))
        delivered = []
        with patch.object(QTableView, 'selectionChanged',
                          new=lambda receiver, new, old: delivered.append(rectangles(new))):
            view.selectionChanged(delta, QItemSelection())
        self.assertEqual(delivered, [[(0, 0, 2, 0)]])

    def test_custom_header_styling_keeps_the_native_header_path(self):
        class CustomHeader(SheetModel):
            def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
                return super().headerData(section, orientation, role)
        self.assertFalse(CustomHeader().uniform_selection_flags)

    def test_numeric_zero_participation_header_is_not_blank(self):
        from metrology_app.data_selection import ParticipationModel, ParticipationView
        model = ParticipationModel(pd.DataFrame({0: ['v']}), ['id'], ['id'])
        view = ParticipationView()
        view.setModel(model)
        self.addCleanup(view.deleteLater)
        header = view.horizontalHeader()
        option = QStyleOptionHeader()
        header.initStyleOptionForIndex(option, 2)
        self.assertEqual(option.text, '0')

    def test_hidden_header_edges_and_sort_arrow_match_native_options(self):
        model = SheetModel()
        model.load(pd.DataFrame({f'C{i}': ['1', '2'] for i in range(4)}))
        view = self.view(model)
        header = view.horizontalHeader()
        header.hideSection(0)
        for section in range(3, header.count()):
            header.hideSection(section)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(2, Qt.SortOrder.AscendingOrder)
        for direction in (Qt.LayoutDirection.LeftToRight, Qt.LayoutDirection.RightToLeft):
            header.setLayoutDirection(direction)
            for section in (1, 2):
                expected, actual = QStyleOptionHeader(), QStyleOptionHeader()
                header.initStyleOption(expected)
                QHeaderView.initStyleOptionForIndex(header, expected, section)
                header.initStyleOptionForIndex(actual, section)
                self.assertEqual(actual.position, expected.position)
                self.assertEqual(actual.sortIndicator, expected.sortIndicator)
                self.assertEqual(actual.text, expected.text)

    def test_duplicate_locked_header_renames_keep_change_order(self):
        model = SheetModel()
        model.load(pd.DataFrame([['W1', 'W2']], columns=['Wafer ID', 'Wafer ID']))
        model.set_clipboard_locks({'Wafer ID'})
        model.apply({(0, 1): 'Lot ID', (0, 0): 'PAD Name'})
        self.assertEqual(model.clipboard_locks, frozenset({'PAD Name'}))
        self.assertFalse(model.flags(model.index(1, 0)) & Qt.ItemFlag.ItemIsEditable)
        self.assertTrue(model.flags(model.index(1, 1)) & Qt.ItemFlag.ItemIsEditable)

    def test_nested_change_context_restores_outer_cells_and_clears_after_notification(self):
        model = SheetModel()
        seen = []
        def nested_edit():
            seen.append(dict(model.changed_cells))
            if model.changed_cells == {(1, 0): '1.2300'}:
                model.apply({(9, 1): '2.340000'})
                self.assertEqual(dict(model.changed_cells), {(1, 0): '1.2300'})
        model.changed.connect(nested_edit)
        model.edit({(1, 0): '1.2300'})
        self.assertEqual(seen, [{(1, 0): '1.2300'}, {(9, 1): '2.340000'}])
        self.assertIsNone(model.changed_cells)
        self.assertEqual(model.cells[(9, 1)], '2.340000')
        self.assertEqual(model.document_frame().shape, (9, 2))

    def test_delete_undo_retains_internal_and_trailing_blanks_across_replays(self):
        model = SheetModel()
        frame = pd.DataFrame({'A': ['1.230000', '', ' ', ''], 'B': ['', '', '\t', '']})
        model.load(frame)
        model.edit({key: '' for key in model.cells})
        for _ in range(3):
            model.undo.undo()
            pd.testing.assert_frame_equal(model.document_frame(), frame)
            model.undo.redo()
            self.assertTrue((model.document_frame().to_numpy() == '').all())

    def test_order_selection_does_not_expand_clipboard_or_cut_permissions(self):
        model = OrderModel()
        self.assertTrue(model.uniform_selection_flags)
        self.assertFalse(model.uniform_selectable)
        self.assertFalse(model.flags(model.index(1, 1)) & Qt.ItemFlag.ItemIsEditable)

    def test_first_dense_delete_undo_restores_exact_cells_and_notification_promptly(self):
        model = SheetModel()
        frame = pd.DataFrame({f'C{i}': ['1.123456789000000']*100000 for i in range(33)})
        model.load(frame)
        model.edit({cell: '' for cell in model.cells})
        changes = QSignalSpy(model.dataChanged)
        start = perf_counter()
        model.undo.undo()
        elapsed = perf_counter() - start
        self.assertLess(elapsed, .6, f'First full Delete Undo blocked for {elapsed:.3f}s')
        self.assertEqual(len(changes), 1)
        self.assertEqual((changes[0][0].row(), changes[0][0].column(),
                          changes[0][1].row(), changes[0][1].column()), (0, 0, 100000, 32))
        pd.testing.assert_frame_equal(model.document_frame(), frame)
