"""Locked metadata protects row-aligned source strings during clipboard updates."""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel
from PyQt6.QtTest import QTest
from metrology_app.sheet import SheetModel, SheetView
from metrology_app.window import MainWindow
from metrology_app.correlation_window import CorrelationWindow
from metrology_app.matching import ParameterMapping

APP = QApplication.instance() or QApplication([])


class MetadataLockTests(unittest.TestCase):
    def test_wafer_map_table_paste_preserves_locked_positions_in_source_and_analysis(self):
        window = MainWindow()
        self.addCleanup(APP.processEvents)
        self.addCleanup(window.deleteLater)
        self.addCleanup(self.close_window, window)
        window.set_table(pd.DataFrame({"Wafer ID": ["001"] * 2, "Die Seq": ["002", "036"],
                                       "Value": ["5.000", "6.000"], "X": ["-6.000", "-5.000"],
                                       "Y": ["1.000", "2.000"]}), "test")
        window.model.set_clipboard_locks(["X", "Y"])
        window.document.mark_clean()
        APP.clipboard().setText("Wafer ID\tDie Seq\tValue\tFIELD X\tFIELD Y\n"
                                "001\t002\t8.000\t99.000\t88.000\n001\t036\t9.000\t77.000\t66.000")
        window.paste_table()
        expected = pd.DataFrame({"Wafer ID": ["001"] * 2, "Die Seq": ["002", "036"],
                                 "Value": ["8.000", "9.000"], "X": ["-6.000", "-5.000"],
                                 "Y": ["1.000", "2.000"]})
        pd.testing.assert_frame_equal(window.model.document_frame(), expected)
        pd.testing.assert_frame_equal(window._frame, expected)
        self.assertTrue(window.document.is_dirty())

    @staticmethod
    def close_window(window):
        window.document.force_close = True
        window.close()

    @staticmethod
    def click_lock(view, column):
        view.resize(660, 220)
        view.show()
        APP.processEvents()
        cell = view.model().index(0, column)
        view.scrollTo(cell)
        rect = view.visualRect(cell)
        point = rect.center()
        point.setX(rect.right() - 13)
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)

    def test_header_lock_icon_and_keyboard_toggle_preserve_names_and_use_red_green_states(self):
        model = SheetModel()
        model.load_matrix([["X", "Y", "Value"], ["-6.000", "1.000", "5.000"]])
        view = SheetView(model, metadata_locks=True)
        self.addCleanup(view.deleteLater)
        self.click_lock(view, 0)
        self.assertEqual(model.clipboard_locks, {"X"})
        self.assertFalse(model.flags(model.index(0, 0)) & Qt.ItemFlag.ItemIsEditable)
        image = view.viewport().grab().toImage()
        colors = {}
        for column in (0, 1, 2):
            rect = view.visualRect(model.index(0, column))
            pixels = [(x, y, image.pixelColor(x, y))
                      for x in range(rect.right() - 24, rect.right())
                      for y in range(rect.top(), rect.bottom())]
            colors[column] = {color.name() for _, _, color in pixels}
            if column == 2:
                continue
            colored = [(x, y) for x, y, color in pixels
                       if (color.red() - color.green() > 20 and color.red() - color.blue() > 10)
                       or (color.green() - color.red() > 20 and color.green() - color.blue() > 10)]
            self.assertTrue(colored, "Lock state must remain visible")
            self.assertLessEqual(max(x for x, _ in colored) - min(x for x, _ in colored) + 1, 9)
            self.assertLessEqual(max(y for _, y in colored) - min(y for _, y in colored) + 1, 10)
            background = image.pixelColor(rect.right() - 24, rect.center().y())
            foreground = (209, 73, 91) if column == 0 else (0, 138, 72)
            blended = tuple(round((front + back) / 2) for front, back in
                            zip(foreground, (background.red(), background.green(), background.blue())))
            self.assertTrue(any(all(abs(actual - expected) <= 2 for actual, expected in
                                    zip((color.red(), color.green(), color.blue()), blended))
                                for _, _, color in pixels), "Icon should blend at half opacity")
        for state_colors in colors.values():
            self.assertNotIn("#d1495b", state_colors)
            self.assertNotIn("#008a48", state_colors)
        self.click_lock(view, 2)
        view.setCurrentIndex(model.index(0, 2))
        QTest.keyClick(view, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(model.clipboard_locks, {"X"})
        view.setCurrentIndex(model.index(1, 0))
        QTest.keyClick(view, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
        self.assertFalse(model.clipboard_locks)
        self.assertEqual(model.source_headers(), ["X", "Y", "Value"])
        self.assertTrue(model.flags(model.index(0, 0)) & Qt.ItemFlag.ItemIsEditable)

    def test_renamed_xy_columns_keep_their_positions_names_and_values_in_replacement_paste(self):
        model = SheetModel()
        model.load_matrix([["Wafer ID", "Die Seq", "Value", "FIELD X", "FIELD Y"],
                           ["001", "002", "5.000", "-6.000", "1.000"],
                           ["001", "036", "6.000", "-5.000", "2.000"]])
        model.edit({(0, 3): "X", (0, 4): "Y"})
        model.set_clipboard_locks(["X", "Y"])
        before = model.document_frame()
        incoming = [["Wafer ID", "Die Seq", "Value", "FIELD X", "FIELD Y"],
                    ["002", "050", "7.100", "99.000", "88.000"],
                    ["002", "085", "8.200", "77.000", "66.000"]]
        model.replace_matrix(incoming, report_paste=True)
        self.assertEqual(model.document_frame().columns.tolist(), ["Wafer ID", "Die Seq", "Value", "X", "Y"])
        self.assertEqual(model.document_frame().values.tolist(),
                         [["002", "050", "7.100", "-6.000", "1.000"],
                          ["002", "085", "8.200", "-5.000", "2.000"]])
        self.assertEqual(model.clipboard_locks, {"X", "Y"})
        model.undo.undo()
        pd.testing.assert_frame_equal(model.document_frame(), before)
        model.undo.redo()
        self.assertEqual(model.document_frame().iloc[:, 3:].values.tolist(),
                         [["-6.000", "1.000"], ["-5.000", "2.000"]])

    def test_undoing_a_metadata_rename_keeps_the_same_column_protected(self):
        model = SheetModel()
        model.load_matrix([["Value", "FIELD X"], ["5.000", "-6.000"]])
        model.edit({(0, 1): "X"})
        model.set_clipboard_locks(["X"])
        model.undo.undo()
        self.assertEqual(model.clipboard_locks, {"FIELD X"})
        self.assertFalse(model.flags(model.index(1, 1)) & Qt.ItemFlag.ItemIsEditable)
        model.undo.redo()
        self.assertEqual(model.clipboard_locks, {"X"})
        model.replace_matrix([["Value", "FIELD X"], ["7.100", "99.000"]], report_paste=True)
        self.assertEqual(model.document_frame().columns.tolist(), ["Value", "X"])
        self.assertEqual(model.document_frame().values.tolist(), [["7.100", "-6.000"]])

    def test_undoing_a_header_to_blank_or_nonmetadata_does_not_leave_an_invisible_lock(self):
        for old_name in ("", "Other"):
            with self.subTest(header=old_name):
                model = SheetModel()
                model.load_matrix([["Value", old_name], ["5.000", "-6.000"]])
                model.edit({(0, 1): "X"})
                model.set_clipboard_locks(["X"])
                model.undo.undo()
                self.assertFalse(model.clipboard_locks)
                self.assertTrue(model.flags(model.index(1, 1)) & Qt.ItemFlag.ItemIsEditable)

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

    def test_header_locks_and_exact_strings_survive_workspace_roundtrip_without_sidebar(self):
        window, restored = MainWindow(), MainWindow()
        self.addCleanup(APP.processEvents)
        for target in (window, restored):
            self.addCleanup(target.deleteLater)
            self.addCleanup(self.close_window, target)
        window.set_table(pd.DataFrame({"Wafer ID": ["001", "001"], "Die Seq": ["002", "036"],
                                       "X(mm)": ["1.000", "2.000"], "CD": ["5.000", "6.000"]}), "test")
        window.resize(1180, 740)
        window.show()
        window.document.mark_clean()
        self.click_lock(window.sheet, 1)
        self.click_lock(window.sheet, 2)
        self.assertTrue(window.document.is_dirty())
        self.assertNotIn("Metadata locks", [label.text() for label in window.findChildren(QLabel)])
        with TemporaryDirectory() as scratch:
            path = Path(scratch) / "locked-metadata.wmap"
            window.document.save(path)
            restored.load_workspace(path)
        self.assertEqual(restored.model.clipboard_locks, {"Die Seq", "X(mm)"})
        pd.testing.assert_frame_equal(restored.model.document_frame(), window.model.document_frame())
        self.assertFalse(restored.document.is_dirty())

    def test_only_wafer_map_metadata_has_lock_controls_and_legacy_locks_remain_visible(self):
        from metrology_app.dynamic_window import DynamicWindow
        from metrology_app.matching_window import MatchingWindow
        from metrology_app.metadata_locks import ColumnLockDelegate
        windows = (MainWindow(), CorrelationWindow(), DynamicWindow(), MatchingWindow())
        self.addCleanup(APP.processEvents)
        for window in windows:
            self.addCleanup(window.deleteLater)
            self.addCleanup(self.close_window, window)
            if isinstance(window, MatchingWindow):
                for view in (window.reference_view, window.raw_view):
                    self.assertFalse(view.metadata_locks_enabled)
                    self.assertNotIsInstance(view.itemDelegate(), ColumnLockDelegate)
                continue
            frame = pd.DataFrame({"Wafer ID": ["001"], "Die Seq": ["002"], "CD": ["5.000"]})
            window.set_table(frame, "test")
            if isinstance(window, CorrelationWindow):
                window.set_reference_table(frame, "test")
                self.assertFalse(window.reference_sheet.metadata_locks_enabled)
            enabled = window.workspace_type == "wafer_map"
            self.assertEqual(window.sheet.metadata_locks_enabled, enabled)
            self.assertEqual(isinstance(window.sheet.itemDelegate(), ColumnLockDelegate), enabled)
            snapshot = window.workspace_snapshot()
            snapshot.states["ui"]["metadata_locks"] = {"model": ["Die Seq", "CD"],
                                                       "reference_model": ["Die Seq"]}
            window.restore_workspace(snapshot)
            self.assertEqual(window.model.clipboard_locks, {"Die Seq"} if enabled else set())
            self.assertTrue(window.model.flags(window.model.index(1, 2)) & Qt.ItemFlag.ItemIsEditable)
            if not enabled:
                self.assertFalse(window.sheet.toggle_column_lock(window.model.index(0, 1)))
                self.assertTrue(window.model.flags(window.model.index(1, 1)) & Qt.ItemFlag.ItemIsEditable)
                if isinstance(window, CorrelationWindow):
                    self.assertFalse(window.reference_model.clipboard_locks)

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
        self.assertTrue(view.cut())
        self.assertEqual(APP.clipboard().text(), "Die Seq\tX(mm)\tCD\n002\t1.000\t5.000\n036\t2.000\t6.000\n")
        self.assertEqual(model.document_frame().values.tolist(), [["002", "1.000"], ["036", "2.000"]])
        self.assertEqual(model.document_frame().columns.tolist(), ["Die Seq", "X(mm)"])
        model.undo.undo()
        self.assertEqual(model.snapshot(), before)

    def test_locked_columns_survive_whole_table_paste_by_position_and_shape_change_is_rejected(self):
        model = SheetModel()
        model.load_matrix([["Die Seq", "X(mm)", "CD"], ["002", "1.000", "5.000"], ["036", "2.000", "6.000"]])
        model.set_clipboard_locks(["Die Seq", "X(mm)"])
        model.replace_matrix([["Sequence", "FIELD X", "CD"], ["999", "99.00", "7.100"],
                              ["888", "88.00", "8.200"]], report_paste=True)
        self.assertEqual(model.document_frame().columns.tolist(), ["Die Seq", "X(mm)", "CD"])
        self.assertEqual(model.document_frame().values.tolist(), [["002", "1.000", "7.100"], ["036", "2.000", "8.200"]])
        before = model.snapshot()
        with self.assertRaisesRegex(ValueError, "Unlock metadata"):
            model.replace_matrix([["CD"], ["9.000"]], report_paste=True)
        self.assertEqual(model.snapshot(), before)
        with self.assertRaisesRegex(ValueError, "locked column position"):
            model.replace_matrix([["CD"], ["9.000"], ["10.000"]], report_paste=True)
        self.assertEqual(model.snapshot(), before)
        model.set_clipboard_locks([])
        model.replace_matrix([["CD"], ["9.000"], ["10.000"]], report_paste=True)
        self.assertEqual(model.document_frame().columns.tolist(), ["CD"])


if __name__ == "__main__":
    unittest.main()
