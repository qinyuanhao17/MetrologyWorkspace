"""Participation table operations retain source identities and responsive Qt seams."""
from time import perf_counter
import unittest

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication

from metrology_app.data_selection import ParticipationModel, SelectionDialog


APP = QApplication.instance() or QApplication([])


class ParticipationBulkTests(unittest.TestCase):
    def make_dialog(self, frame, ids):
        dialog = SelectionDialog(frame, ids, ids, [])
        dialog.resize(650, 300)
        dialog.show()
        APP.processEvents()
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        return dialog

    @staticmethod
    def click(dialog, row, modifiers=Qt.KeyboardModifier.NoModifier):
        index = dialog.model.index(row, 1)
        dialog.table.scrollTo(index)
        APP.processEvents()
        QTest.mouseClick(dialog.table.viewport(), Qt.MouseButton.LeftButton, modifiers,
                         dialog.table.visualRect(index).center())

    def test_shift_range_notifies_once_and_keeps_filtered_sorted_source_ids(self):
        frame = pd.DataFrame({"ID": ["Keep-000", "Hidden-001", "Keep-002", "Hidden-003", "Keep-004", "Keep-005"],
                              "CD": ["1.000", "2.100", "3.000", "4.000", "5.000", "6.000"]})
        original = frame.copy(deep=True)
        ids = [f"source-{i:03d}" for i in range(6)]
        dialog = self.make_dialog(frame, ids)
        dialog.search.setText("Keep")
        dialog.table.sortByColumn(3, Qt.SortOrder.DescendingOrder)
        self.assertEqual(dialog.model.rows, [5, 4, 2, 0])
        self.click(dialog, 0)
        changes, cells = QSignalSpy(dialog.model.changed), QSignalSpy(dialog.model.dataChanged)
        self.click(dialog, 2, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(dialog.model.checked, {"source-000", "source-001", "source-003"})
        self.assertIn("3 participating", dialog.status.text())
        self.assertEqual((len(changes), len(cells)), (1, 1))
        top, bottom, roles = cells[0]
        self.assertEqual((top.row(), top.column(), bottom.row(), bottom.column()), (0, 0, 2, 0))
        self.assertEqual(roles, [Qt.ItemDataRole.CheckStateRole.value])
        dialog.reject()
        pd.testing.assert_frame_equal(frame, original)
        self.assertEqual(ids, [f"source-{i:03d}" for i in range(6)])

    def test_large_shift_range_finishes_as_one_responsive_edit(self):
        count = 20000
        frame = pd.DataFrame({"ID": [f"{row:06d}" for row in range(count)], "CD": ["1.1234567890000"] * count})
        ids = list(frame.ID)
        dialog = self.make_dialog(frame, ids)
        self.click(dialog, 0)
        index = dialog.model.index(count - 1, 1)
        dialog.table.scrollTo(index)
        APP.processEvents()
        start = perf_counter()
        QTest.mouseClick(dialog.table.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ShiftModifier, dialog.table.visualRect(index).center())
        elapsed = perf_counter() - start
        self.assertFalse(dialog.model.checked)
        self.assertLess(elapsed, .10, f"Shift range blocked the GUI: {elapsed:.3f}s")

    def test_repeated_flags_queries_keep_readonly_data_and_checkable_use_promptly(self):
        model = ParticipationModel(pd.DataFrame({"CD": ["1.000"]}), ["record-001"], ["record-001"])
        use, data = model.index(0, 0), model.index(0, 2)
        self.assertTrue(model.flags(use) & Qt.ItemFlag.ItemIsUserCheckable)
        self.assertFalse(model.flags(data) & Qt.ItemFlag.ItemIsUserCheckable)
        self.assertFalse(model.flags(data) & Qt.ItemFlag.ItemIsEditable)
        self.assertTrue(model.flags(data) & Qt.ItemFlag.ItemIsSelectable)
        times = []
        for _ in range(3):
            start = perf_counter()
            for _ in range(200000):
                model.flags(data)
            times.append(perf_counter() - start)
        self.assertLess(min(times), .15, f"Native selection repeatedly queried slow flags: {times}")
