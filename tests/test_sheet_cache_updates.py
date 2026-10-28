"""Literal value edits update cached frames once, without weakening notifications."""
import unittest
from unittest.mock import patch
import pandas as pd
from PyQt6.QtWidgets import QApplication
from metrology_app.sheet import SheetModel

APP = QApplication.instance() or QApplication([])


class SheetCacheUpdateTests(unittest.TestCase):
    def model(self, frame=None):
        model = SheetModel()
        self.addCleanup(model.deleteLater)
        model.load(frame if frame is not None else pd.DataFrame({"ID": ["001", "002"], "CD": ["1.000", "2.000"]}))
        model.document_frame()
        model.frame()
        return model

    def test_one_cache_write_per_frame_for_edit_undo_redo(self):
        model = self.model()
        original = pd.DataFrame._set_value
        writes = []
        def record(frame, *args, **kwargs):
            writes.append((id(frame), args))
            return original(frame, *args, **kwargs)
        with patch.object(pd.DataFrame, "_set_value", record):
            for operation in (lambda: model.edit({(1, 1): "9.99000"}), model.undo.undo, model.undo.redo):
                writes.clear()
                operation()
                self.assertEqual(len(writes), 2, "one update for each owned frame, not two per notification")
        self.assertEqual(model.document_frame().iloc[0, 1], "9.99000")
        self.assertEqual(model.undo.count(), 1)

    def test_callbacks_see_new_values_and_old_snapshots_stay_detached(self):
        model = self.model()
        old_document, old_analysis = model.document_frame(), model.frame()
        seen = []
        def observe(*_):
            seen.append((model.document_frame().iloc[0, 1], model.frame().iloc[0, 1]))
        model.dataChanged.connect(observe)
        model.changed.connect(observe)
        model.edit({(1, 1): "9.99000"})
        model.undo.undo()
        model.undo.redo()
        self.assertEqual(seen, [(value, value) for value in ("9.99000", "9.99000", "1.000", "1.000", "9.99000", "9.99000")])
        self.assertEqual(old_document.iloc[0, 1], "1.000")
        self.assertEqual(old_analysis.iloc[0, 1], "1.000")

    def test_nested_edit_and_unknown_notification_still_invalidate(self):
        model = self.model()
        nested = []
        def observe(*_):
            if not nested:
                nested.append(True)
                model.apply({(2, 1): "8.000000"})
        model.dataChanged.connect(observe)
        model.apply({(1, 1): "9.99000"})
        self.assertEqual(model.frame()["CD"].tolist(), ["9.99000", "8.000000"])
        # Untracked changes have no prepared transaction to consume.
        model.cells[(1, 1)] = "7.0000000"
        model.changed.emit()
        self.assertEqual(model.document_frame()["CD"].tolist(), ["7.0000000", "8.000000"])
        self.assertEqual(model.frame()["CD"].tolist(), ["7.0000000", "8.000000"])

    def test_blank_rows_headers_growth_and_duplicate_names_keep_full_fallback(self):
        model = self.model(pd.DataFrame({"ID": ["001", "", "003"], "CD": ["1.000", "", "3.000"]}))
        old = model.frame()
        model.edit({(1, 1): "9.0000", (2, 1): "2.0000"})
        self.assertEqual(model.frame()["CD"].tolist(), ["9.0000", "2.0000", "3.000"])
        model.undo.undo()
        pd.testing.assert_frame_equal(model.frame(), old)
        model.edit({(0, 1): "ID", (105, 1): "5.0000"})
        with self.assertRaises(ValueError):
            model.frame()
        self.assertEqual(model.document_frame().iloc[104, 1], "5.0000")
        model.undo.undo()
        pd.testing.assert_frame_equal(model.frame(), old)

    def test_dense_multi_column_updates_preserve_precision_and_fragmented_frames(self):
        frame = pd.DataFrame({f"P{column}": [f"{row}.{column:06}" for row in range(180)] for column in range(9)})
        model = self.model(frame)
        changes = {(row + 1, column): f"000{row}.{column:09}" for row in range(180) for column in (1, 3, 7)}
        model.edit(changes)
        expected = frame.copy()
        for (row, column), value in changes.items():
            expected.iat[row - 1, column] = value
        pd.testing.assert_frame_equal(model.document_frame(), expected)
        pd.testing.assert_frame_equal(model.frame(), expected)
        model.undo.undo()
        pd.testing.assert_frame_equal(model.document_frame(), frame)
        model.undo.redo()
        pd.testing.assert_frame_equal(model.frame(), expected)

    def test_structural_signal_reads_cannot_leave_old_frames_cached(self):
        model = self.model()
        reads = []
        model.rowsAboutToBeInserted.connect(lambda *_: reads.append(model.document_frame()))
        observed = []
        model.dataChanged.connect(lambda *_: observed.append(model.document_frame()))
        model.edit({(1, 1): "8.00000", (105, 1): "9.00000"})
        self.assertEqual(len(reads), 1)
        self.assertEqual(observed[0].iloc[0, 1], "8.00000")
        self.assertEqual(observed[0].iloc[104, 1], "9.00000")
