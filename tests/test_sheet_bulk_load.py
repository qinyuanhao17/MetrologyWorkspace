"""Bulk loading preserves the public literal and analysis sheet behavior."""
import unittest
import pandas as pd
from PyQt6.QtWidgets import QApplication
from metrology_app.sheet import SheetModel

APP = QApplication.instance() or QApplication([])


class SheetBulkLoadTests(unittest.TestCase):
    def test_reset_notification_reads_never_leave_previous_source_cached(self):
        model = SheetModel()
        self.addCleanup(model.deleteLater)
        original = pd.DataFrame({'ID': ['001', '002'], 'Value': ['1.00', '2.00']})
        incoming = pd.DataFrame({'New ID': ['new'], 'New Value': ['0001.230000']})
        model.load(original)
        seen_before, seen_after = [], []
        model.modelAboutToBeReset.connect(lambda: seen_before.append(model.document_frame()))
        model.modelReset.connect(lambda: seen_after.append(model.document_frame()))
        model.load(incoming)
        pd.testing.assert_frame_equal(seen_before[0], original)
        pd.testing.assert_frame_equal(seen_after[0], incoming)
        pd.testing.assert_frame_equal(model.document_frame(), incoming)

    def test_dense_and_sparse_loads_match_clipboard_matrix_semantics(self):
        fixtures = [pd.DataFrame({" ID ": ["001", "002"], "CD": ["1.000", "2.000"]}),
                    pd.DataFrame({"A": [" ", "3"], "B": ["\t", "4"]}),
                    pd.DataFrame({"A": ["", ""], "B": ["1.00", ""]}),
                    pd.DataFrame([["1", "2"]], columns=["Same", " Same "]),
                    pd.DataFrame([["1", ""]], columns=["A", ""])]
        for frame in fixtures:
            loaded, matrix = SheetModel(), SheetModel()
            self.addCleanup(loaded.deleteLater)
            self.addCleanup(matrix.deleteLater)
            text = frame.fillna("").astype(str)
            matrix.load_matrix([list(text.columns), *text.values.tolist()])
            loaded.load(frame)
            self.assertEqual(loaded.snapshot(), matrix.snapshot())
            pd.testing.assert_frame_equal(loaded.document_frame(), matrix.document_frame())
            if len(set(matrix.headers())) != len(matrix.headers()):
                with self.assertRaises(ValueError):
                    loaded.frame()
            else:
                pd.testing.assert_frame_equal(loaded.frame(), matrix.frame())

    def test_reentrant_literal_edit_during_load_is_not_replaced_by_prepared_frames(self):
        model = SheetModel()
        self.addCleanup(model.deleteLater)
        observations = []
        def observer():
            if not observations:
                observations.append(model.frame())
                model.edit({(1, 1): "9.999000"})
        model.changed.connect(observer)
        model.load(pd.DataFrame({"ID": ["001"], "CD": ["1.000"]}))
        self.assertEqual(observations[0].iloc[0, 1], "1.000")
        self.assertEqual(model.document_frame().iloc[0, 1], "9.999000")
        self.assertEqual(model.frame().iloc[0, 1], "9.999000")
