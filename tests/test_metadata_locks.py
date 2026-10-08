"""Locked metadata protects row-aligned source strings during clipboard updates."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from metrology_app.sheet import SheetModel, SheetView
from metrology_app.window import MainWindow
from metrology_app.correlation_window import CorrelationWindow
from metrology_app.matching import ParameterMapping

APP = QApplication.instance() or QApplication([])


class MetadataLockTests(unittest.TestCase):
    def test_new_empty_table_clears_missing_locks_so_first_paste_is_possible(self):
        model = SheetModel()
        model.load_matrix([["Die Seq", "CD"], ["002", "5.000"]])
        model.set_clipboard_locks(["Die Seq"])
        model.load_matrix([])
        self.assertFalse(model.clipboard_locks)
        model.replace_matrix([["CD"], ["7.100"]], report_paste=True)
        self.assertEqual(model.document_frame().values.tolist(), [["7.100"]])

    def test_metadata_lock_names_preserve_literal_header_whitespace(self):
        model = SheetModel()
        model.load_matrix([[" X(mm) ", "CD"], ["1.000", "5.000"]])
        model.set_clipboard_locks([" X(mm) "])
        model.paste_cells({(1, 0): "9.000", (1, 1): "6.000"})
        self.assertEqual(model.document_frame().columns.tolist(), [" X(mm) ", "CD"])
        self.assertEqual(model.document_frame().values.tolist(), [["1.000", "6.000"]])
        self.assertFalse(model.flags(model.index(1, 0)) & Qt.ItemFlag.ItemIsEditable)

    def test_rejected_raw_replacement_keeps_correlation_source_context(self):
        window = CorrelationWindow()
        self.addCleanup(window.deleteLater)
        raw = pd.DataFrame({"Wafer ID": ["001"] * 3, "Die Seq": ["002", "036", "085"],
                            "CD": ["5.000", "6.000", "7.000"]})
        window.set_sources(raw, raw, (ParameterMapping("CD", "CD", "CD"),))
        window.model.set_clipboard_locks(["Die Seq"])
        sources, mappings = window._workbook_sources, window._source_mappings
        before = window.workspace_snapshot()
        with self.assertRaisesRegex(ValueError, "Unlock metadata"):
            window.set_table(raw.iloc[:1], "Clipboard", report_paste=True)
        self.assertEqual(window._workbook_sources, sources)
        self.assertEqual(window._source_mappings, mappings)
        after = window.workspace_snapshot()
        self.assertEqual(before.states, after.states)
        for name, frame in before.frames.items():
            pd.testing.assert_frame_equal(frame, after.frames[name])
        window.document.timer.stop()
        window.document.identity_timer.stop()
        window.refresh_timer.stop()

    def test_right_side_locks_and_exact_strings_survive_workspace_roundtrip(self):
        for window_type in (MainWindow, CorrelationWindow):
            with self.subTest(window=window_type.__name__):
                window, restored = window_type(), window_type()
                self.addCleanup(window.deleteLater)
                self.addCleanup(restored.deleteLater)
                window.set_table(pd.DataFrame({"Wafer ID": ["001", "001"], "Die Seq": ["002", "036"],
                                               "X(mm)": ["1.000", "2.000"], "CD": ["5.000", "6.000"]}), "test")
                window.metadata_locks_panel.checks["Die Seq"].click()
                window.metadata_locks_panel.checks["X(mm)"].click()
                if isinstance(window, CorrelationWindow):
                    window.set_reference_table(window.model.document_frame(), "test")
                    window.reference_metadata_locks_panel.checks["Die Seq"].click()
                snapshot = window.workspace_snapshot()
                restored.restore_workspace(snapshot)
                self.assertEqual(restored.model.clipboard_locks, {"Die Seq", "X(mm)"})
                pd.testing.assert_frame_equal(restored.model.document_frame(), window.model.document_frame())
                if isinstance(window, CorrelationWindow):
                    self.assertEqual(restored.reference_model.clipboard_locks, {"Die Seq"})
                for target in (window, restored):
                    target.document.timer.stop()
                    target.document.identity_timer.stop()
                    target.refresh_timer.stop()

    def test_locked_metadata_survives_range_paste_and_measurement_undo(self):
        model = SheetModel()
        model.load_matrix([["Die Seq", "X(mm)", "CD"], ["002", "1.000", "5.000"], ["036", "2.000", "6.000"]])
        before = model.snapshot()
        model.set_clipboard_locks(["Die Seq", "X(mm)"])
        view = SheetView(model)
        self.addCleanup(view.deleteLater)
        view.setCurrentIndex(model.index(1, 0))
        APP.clipboard().setText("999\t99.00\t7.100\n888\t88.00\t8.200")
        view.paste()
        self.assertEqual(model.document_frame().values.tolist(), [["002", "1.000", "7.100"], ["036", "2.000", "8.200"]])
        self.assertFalse(model.flags(model.index(1, 1)) & Qt.ItemFlag.ItemIsEditable)
        self.assertEqual(model.paste_report.changes, {(1, 2): ("5.000", "7.100"), (2, 2): ("6.000", "8.200")})
        model.undo.undo()
        self.assertEqual(model.snapshot(), before)
        view.selectAll()
        self.assertFalse(view.cut())
        self.assertEqual(model.snapshot(), before)

    def test_locked_columns_survive_whole_table_paste_by_name_and_row_change_is_rejected(self):
        model = SheetModel()
        model.load_matrix([["Die Seq", "X(mm)", "CD"], ["002", "1.000", "5.000"], ["036", "2.000", "6.000"]])
        model.set_clipboard_locks(["Die Seq", "X(mm)"])
        model.replace_matrix([["CD"], ["7.100"], ["8.200"]], report_paste=True)
        self.assertEqual(model.document_frame().columns.tolist(), ["CD", "Die Seq", "X(mm)"])
        self.assertEqual(model.document_frame().values.tolist(), [["7.100", "002", "1.000"], ["8.200", "036", "2.000"]])
        before = model.snapshot()
        with self.assertRaisesRegex(ValueError, "Unlock metadata"):
            model.replace_matrix([["CD"], ["9.000"]], report_paste=True)
        self.assertEqual(model.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
