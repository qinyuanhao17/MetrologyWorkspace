"""Data-tab regression checks; run Qt offscreen without opening desktop windows."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog, QLabel, QMessageBox

from metrology_app.appearance import configure_fonts
from metrology_app.data import read_table
from metrology_app.sheet import SheetModel, column_letter
from metrology_app.window import MainWindow, parameter_checked_by_default

ROOT = Path(__file__).resolve().parents[1]
APP = QApplication.instance() or QApplication([])
APP.setStyle("Fusion")
configure_fonts(APP)


class SheetTests(unittest.TestCase):
    def test_auto_rename_starts_at_one_and_skips_reserved_suffixes(self):
        for headers, expected in (
            (["Value", "Value", "Value", "Value"],
             ["Value", "Value_1", "Value_2", "Value_3"]),
            (["Value", "Value", "Value_1", "Value", "Value_3"],
             ["Value", "Value_2", "Value_1", "Value_4", "Value_3"]),
        ):
            with self.subTest(headers=headers):
                model = SheetModel()
                model.load(pd.DataFrame([["1.00"] * len(headers)], columns=headers))
                model.rename_duplicate_headers()
                self.assertEqual(model.headers(), expected)
                self.assertEqual(model.frame().iloc[0].tolist(), ["1.00"] * len(headers))

    def test_default_parameter_exclusions_ignore_formatting(self):
        for name in ("MSE", "gof", "N_GOF", "LBH", "regIter", "reglter", "C Index", "CINDEX"):
            self.assertFalse(parameter_checked_by_default(name))
        for name in ("OCD_H1", "ASi_BCD", "Thickness"):
            self.assertTrue(parameter_checked_by_default(name))

    def test_header_letters_and_undo(self):
        self.assertEqual([column_letter(c) for c in [0, 25, 26, 51, 52]], ["A", "Z", "AA", "AZ", "BA"])
        model = SheetModel()
        model.load(pd.DataFrame({"Wafer ID": ["001"], "Value": ["2.10"]}))
        model.edit({(1, 1): "7.25", (2, 0): "002", (2, 1): "8"})
        self.assertEqual(model.frame().Value.tolist(), ["7.25", "8"])
        model.undo.undo()
        self.assertEqual(model.frame().Value.tolist(), ["2.10"])
        model.undo.redo()
        self.assertEqual(len(model.frame()), 2)

    def test_text_import_preserves_ids(self):
        frame = read_table(text="Wafer ID\tValue\tNote\n001\t2.10\tNA\n002\t3.20\ttext", dtype=str)
        self.assertEqual(frame.iloc[0].tolist(), ["001", "2.10", "NA"])


class WorkspaceTests(unittest.TestCase):
    def test_quality_columns_are_numeric_in_correlation_and_dynamic_parameter_lists(self):
        from metrology_app.correlation_window import CorrelationWindow
        from metrology_app.dynamic_window import DynamicWindow

        quality = ["MSE", "GOF", "LBH", "NGOF", "CINDEX"]
        frame = pd.DataFrame({
            "Wafer ID": ["W1"] * 3, "Die Seq": [1, 2, 3],
            "DP": [65., 66., 67.], "fitTime": [10, 11, 12],
            **{name: [.1, .2, .3] for name in quality},
        })
        for cls in (CorrelationWindow, DynamicWindow):
            with self.subTest(window=cls.__name__):
                window = cls()
                try:
                    window.set_table(frame, "Quality parameters")
                    trees = [window.parameter_list]
                    if isinstance(window, CorrelationWindow):
                        window.set_reference_table(frame, "Reference quality parameters")
                        trees.append(window.reference_parameter_list)
                    for tree in trees:
                        items = {tree.topLevelItem(i).text(0): tree.topLevelItem(i)
                                 for i in range(tree.topLevelItemCount())}
                        for name in quality:
                            self.assertEqual(items[name].text(1), "NUMERIC")
                            self.assertTrue(items[name].flags() & Qt.ItemFlag.ItemIsUserCheckable)
                        self.assertEqual(items["fitTime"].text(1), "METADATA")
                finally:
                    window.model.undo.setClean()
                    if isinstance(window, CorrelationWindow):
                        window.reference_model.undo.setClean()
                    window.close()
                    window.deleteLater()
                    APP.processEvents()

    def test_wafer_map_quality_columns_are_selectable_numeric_not_metadata(self):
        w = self.window
        frame = pd.DataFrame({
            "Wafer ID": ["W1", "W1"], "FIELD X": [0, 1], "FIELD Y": [0, 1],
            "MSE": ["0.1", "0.2"], "gof": ["0.9", "0.8"],
            "N_GOF": ["0.9", "0.8"], "LBH": ["1", "2"],
            "C Index": ["3", "4"], "fitTime": ["10", "11"],
            "regIter": ["1", "2"], "DP": ["65", "66"],
        })
        w.set_table(frame, "Quality metrics")
        items = {w.parameter_list.topLevelItem(i).text(0):
                 w.parameter_list.topLevelItem(i)
                 for i in range(w.parameter_list.topLevelItemCount())}
        quality = ["MSE", "gof", "N_GOF", "LBH", "C Index"]
        for column in quality:
            with self.subTest(column=column):
                item = items[column]
                self.assertEqual(item.text(1), "NUMERIC")
                self.assertTrue(item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
                self.assertEqual(item.checkState(0), Qt.CheckState.Unchecked)
                item.setCheckState(0, Qt.CheckState.Checked)
        self.assertEqual(w.selection["metrics"], quality)
        self.assertEqual(w.plot_page.selection["metrics"], quality)
        for column in ("fitTime", "regIter", "Wafer ID", "FIELD X", "FIELD Y"):
            self.assertEqual(items[column].text(1), "METADATA")
            self.assertFalse(items[column].flags() & Qt.ItemFlag.ItemIsUserCheckable)

        frame["MSE"] = ["invalid", ""]
        w.set_table(frame, "Non-numeric MSE")
        mse = next(w.parameter_list.topLevelItem(i)
                   for i in range(w.parameter_list.topLevelItemCount())
                   if w.parameter_list.topLevelItem(i).text(0) == "MSE")
        self.assertEqual(mse.text(1), "METADATA")
        self.assertNotIn("MSE", w.selection["metrics"])

    def test_first_cell_paste_auto_identifies_wafers(self):
        w = MainWindow()
        try:
            self.assertEqual(w.group_columns(), [])
            w.sheet.setCurrentIndex(w.model.index(0, 0))
            APP.clipboard().setText("Wafer ID\tPAD Name\tValue\nW1\tCELL\t1\nW2\tCELL\t2")
            w.sheet.paste()
            w.recognize()
            self.assertEqual(w.group_columns(), ["Wafer ID"])
            self.assertEqual([m.label for m in w.measurements], ["W1", "W2"])
        finally:
            w.model.undo.setClean()
            w.close()
            w.deleteLater()
            APP.processEvents()

    def test_replace_paste_shortcut_clears_the_table_and_reidentifies(self):
        w = MainWindow()
        try:
            w.sheet.setCurrentIndex(w.model.index(0, 0))
            APP.clipboard().setText("Wafer ID\tPAD Name\tStale\tValue\nW1\tCELL\t9\t1\nW2\tCELL\t9\t2")
            w.sheet.paste()
            w.recognize()
            self.assertEqual(w.group_columns(), ["Wafer ID"])
            self.assertEqual(len(w.measurements), 2)
            self.assertEqual(w._frame.shape, (2, 4))
            value_item = next(
                w.parameter_list.topLevelItem(index)
                for index in range(w.parameter_list.topLevelItemCount())
                if w.parameter_list.topLevelItem(index).text(0) == "Value"
            )
            value_item.setCheckState(0, Qt.CheckState.Checked)

            w.sheet.setCurrentIndex(w.model.index(0, 0))
            APP.clipboard().setText(
                "Wafer ID\tPAD Name\tValue\n"
                "W1\tA\t1\nW1\tB\t2\nW2\tA\t3\nW2\tB\t4"
            )
            QTest.keyClick(w.sheet, Qt.Key.Key_V,
                           Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
            w.recognize()
            self.assertEqual(w.group_columns(), ["Wafer ID", "PAD Name"])
            self.assertEqual(len(w.measurements), 4)
            self.assertEqual(w._frame.shape, (4, 3))
            self.assertNotIn("Stale", w._frame.columns)
            self.assertEqual(w.selection["metrics"], ["Value"])
            self.assertEqual(w.plot_page.selection["metrics"], ["Value"])
        finally:
            w.model.undo.setClean()
            w.close()
            w.deleteLater()
            APP.processEvents()

    def test_default_paste_at_a1_keeps_cells_outside_the_pasted_range(self):
        """Ctrl+V only overwrites the pasted rectangle; it never clears the table."""
        w = MainWindow()
        try:
            w.sheet.setCurrentIndex(w.model.index(0, 0))
            APP.clipboard().setText(
                "Wafer ID\tPAD Name\tKeep\tExtra\nW1\tCELL\t21\t11\nW2\tCELL\t22\t12"
            )
            w.sheet.paste()
            w.sheet.setCurrentIndex(w.model.index(0, 0))
            APP.clipboard().setText(
                "Wafer ID\tPAD Name\tValue\n"
                "W1\tA\t1\nW1\tB\t2\nW2\tA\t3\nW2\tB\t4"
            )
            with patch.object(w.sheet, "mismatched_paste_choice", return_value="keep") as reminder:
                w.sheet.paste()
            reminder.assert_called_once_with((3, 4), (4, 2))
            w.recognize()
            self.assertEqual(w.group_columns(), ["Wafer ID", "PAD Name"])
            self.assertEqual(len(w.measurements), 4)
            self.assertEqual(w._frame.shape, (4, 4))
            self.assertEqual(w._frame["Extra"].tolist(), ["11", "12", "", ""])
            w.model.undo.undo()
            self.assertEqual(w.model.cells[(0, 2)], "Keep")
        finally:
            w.model.undo.setClean()
            w.close()
            w.deleteLater()
            APP.processEvents()

    def test_replace_paste_ignores_an_empty_clipboard(self):
        w = MainWindow()
        try:
            w.sheet.setCurrentIndex(w.model.index(0, 0))
            APP.clipboard().setText("Wafer ID\tValue\nW1\t1")
            w.sheet.paste()
            before = dict(w.model.cells)
            APP.clipboard().setText("")
            w.sheet.paste(replace=True)
            self.assertEqual(w.model.cells, before)
        finally:
            w.model.undo.setClean()
            w.close()
            w.deleteLater()
            APP.processEvents()

    def test_paste_size_reminder_lists_both_sizes_and_can_replace(self):
        w = MainWindow()
        try:
            w.sheet.setCurrentIndex(w.model.index(0, 0))
            APP.clipboard().setText(
                "Wafer ID\tPAD Name\tKeep\tExtra\nW1\tCELL\t21\t11\nW2\tCELL\t22\t12"
            )
            w.sheet.paste()
            w.sheet.setCurrentIndex(w.model.index(0, 0))
            APP.clipboard().setText(
                "Wafer ID\tPAD Name\tValue\n"
                "W1\tA\t1\nW1\tB\t2\nW2\tA\t3\nW2\tB\t4"
            )
            seen = {}

            def choose_replace(box):
                seen["text"] = box.text()
                next(button for button in box.buttons()
                     if button.text() == "Clear table and paste").click()

            with patch.object(QMessageBox, "exec", choose_replace):
                w.sheet.paste()
            self.assertIn("3 columns × 4 rows", seen["text"])
            self.assertIn("4 columns × 2 rows", seen["text"])
            w.recognize()
            self.assertEqual(w._frame.shape, (4, 3))
            self.assertNotIn("Extra", w._frame.columns)
        finally:
            w.model.undo.setClean()
            w.close()
            w.deleteLater()
            APP.processEvents()

    def test_paste_size_reminder_cancel_leaves_the_table_untouched(self):
        w = MainWindow()
        try:
            w.sheet.setCurrentIndex(w.model.index(0, 0))
            APP.clipboard().setText(
                "Wafer ID\tPAD Name\tKeep\tExtra\nW1\tCELL\t21\t11\nW2\tCELL\t22\t12"
            )
            w.sheet.paste()
            before = dict(w.model.cells)
            w.sheet.setCurrentIndex(w.model.index(0, 0))
            APP.clipboard().setText("Wafer ID\tPAD Name\tValue\nW1\tA\t1")
            with patch.object(QMessageBox, "exec", lambda box: None):
                w.sheet.paste()
            self.assertEqual(w.model.cells, before)
        finally:
            w.model.undo.setClean()
            w.close()
            w.deleteLater()
            APP.processEvents()

    def test_workspace_data_selection_limits_plots_and_restores_with_the_document(self):
        from PyQt6.QtCore import Qt
        from metrology_app.data_selection import FrameSelectionDialog
        from metrology_app.match_groups import participation_source_keys
        w = MainWindow()
        try:
            w.set_table(pd.DataFrame({"Wafer ID": ["W1", "W2", "W3"], "Value": [1., 2., 3.]}),
                        "Clipboard")
            frame = w.model.frame()
            keys = participation_source_keys(frame)
            dialog = FrameSelectionDialog(frame)
            dialog.model.setData(dialog.model.index(1, 0), Qt.CheckState.Unchecked,
                                 Qt.ItemDataRole.CheckStateRole)
            dialog.accept()
            self.assertEqual(dialog.excluded, [keys[1]])
            w._local_selection_excluded = set(dialog.excluded)
            w._local_view = {"filters": [[{"column": "CD", "minimum": 2}]],
                             "row_bools": [[]], "group_bools": [], "show": "filtered"}
            w.update_plan()
            self.assertEqual(w.participating_positions(frame), {0, 2})
            self.assertEqual(w.data_badge.text(), "3 rows × 2 columns")
            self.assertEqual(w.selection_count.text(), "2 of 3 rows used")
            refreshed = pd.DataFrame({"Wafer ID": ["Z1", "Z2", "Z3"], "Value": [7., 8., 9.]})
            w.set_table(refreshed, "Workbook refresh", keep_local_selection=True)
            self.assertEqual(w._local_selection_excluded,
                             {participation_source_keys(refreshed)[1]})
            self.assertEqual(w.participating_positions(refreshed), {0, 2})
            snapshot = w.workspace_snapshot()
            self.assertEqual(snapshot.states["data_selection"]["excluded"],
                             [participation_source_keys(refreshed)[1]])
            self.assertTrue(snapshot.states["data_selection"]["follow_workbook"])
            self.assertEqual(snapshot.states["data_selection"]["view"]["show"], "filtered")
            restored = MainWindow()
            try:
                restored.restore_workspace(snapshot)
                self.assertEqual(restored._local_selection_excluded,
                                 {participation_source_keys(refreshed)[1]})
                self.assertEqual(restored.participating_positions(restored.model.frame()), {0, 2})
                self.assertEqual(restored._local_view["show"], "filtered")
            finally:
                restored.close()
                restored.deleteLater()
        finally:
            w.model.undo.setClean()
            w.close()
            w.deleteLater()
            APP.processEvents()

    def test_wafer_record_filter_hides_and_unchecks_small_measurement_sets(self):
        from PyQt6.QtCore import Qt
        w = MainWindow()
        try:
            w.set_table(pd.DataFrame({
                "Wafer ID": ["W1"] * 2 + ["W2"] * 4,
                "Die Seq": [1, 2, 1, 2, 3, 4],
                "Value": [1., 2., 3., 4., 5., 6.]}), "Clipboard")
            self.assertEqual(
                [w.wafer_list.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole + 1)
                 for i in range(2)], [2, 4])
            w.min_records.setValue(3)
            self.assertTrue(w.wafer_list.topLevelItem(0).isHidden())
            self.assertFalse(w.wafer_list.topLevelItem(1).isHidden())
            self.assertEqual(w.wafer_list.topLevelItem(0).checkState(0), Qt.CheckState.Unchecked)
            participating = sorted((tuple(rows) for rows in w.selection["groups"].values()),
                                   key=len)[-1]
            self.assertEqual(participating, (2, 3, 4, 5))
            # Pressing All must not bring the records-filtered wafers back.
            hidden_key = w.wafer_list.topLevelItem(0).data(0, Qt.ItemDataRole.UserRole)
            w.check_all(w.wafer_list, True)
            self.assertEqual(w.wafer_list.topLevelItem(0).checkState(0), Qt.CheckState.Unchecked)
            self.assertNotIn(hidden_key, w.radius_page.selection["wafers"])
            w.restore_selection({"wafers": (hidden_key,), "metrics": ()})
            self.assertEqual(w.wafer_list.topLevelItem(0).checkState(0), Qt.CheckState.Unchecked)
            self.assertEqual(w.selection_state()["min_records"], 3)
            w.min_records.setValue(0)
            self.assertFalse(w.wafer_list.topLevelItem(0).isHidden())
            w.restore_selection({"wafers": (), "metrics": (), "min_records": 3})
            self.assertEqual(w.min_records.value(), 3)
            self.assertTrue(w.wafer_list.topLevelItem(0).isHidden())
        finally:
            w.model.undo.setClean()
            w.close()
            w.deleteLater()
            APP.processEvents()

    def test_sequence_axis_keeps_labels_until_the_plot_is_laid_out(self):
        from PyQt6.QtCore import QRectF
        from PyQt6.QtWidgets import QApplication
        from metrology_app.plotting.sequence_axis import SpanLabelAxis
        app = QApplication.instance() or QApplication([])
        axis = SpanLabelAxis([(0, 10, "W1"), (10, 20, "W2")], optional_fields=False)

        class _View:
            def __init__(self, width):
                self.width = width

            def viewRange(self):
                return [[0, 20], [0, 1]]

            def sceneBoundingRect(self):
                return QRectF(0, 0, self.width, 10)

        try:
            axis._linkedView = lambda: _View(0)
            axis.refresh()
            self.assertFalse(axis._tickLevels)
            axis._linkedView = lambda: _View(600)
            axis.refresh()
            self.assertTrue(axis._tickLevels[0])
        finally:
            axis.deleteLater()
            app.processEvents()

    def test_page_size_reads_two_digit_values(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.plot_page import PlotPage
        from metrology_app.radius_page import RadiusPage
        app = QApplication.instance() or QApplication([])
        pages = [PlotPage(), RadiusPage()]
        try:
            wafers = [f"W{i}" for i in range(31)]
            for page in pages:
                self.assertFalse(page.page_size.keyboardTracking())
                page.page_size.setValue(12)
                page.page_index = 0
                self.assertEqual(page.paginate_wafers(wafers), (wafers[:12], 0, 3))
        finally:
            for page in pages:
                page.deleteLater()
            app.processEvents()

    def test_radius_pages_keep_all_metrics_of_a_wafer_together(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.radius_page import RadiusPage
        app = QApplication.instance() or QApplication([])
        page = RadiusPage()
        try:
            page.page_size.setValue(2)
            for index, expected in ((0, (["A", "B"], 0, 3)),
                                    (1, (["C", "D"], 1, 3)),
                                    (9, (["E"], 2, 3))):
                page.page_index = index
                self.assertEqual(page.paginate_wafers(["A", "B", "C", "D", "E"]), expected)
        finally:
            page.deleteLater()
            app.processEvents()

    def test_selection_show_modes_keep_all_rows_and_can_filter_rows(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication
        from metrology_app.data_selection import FrameSelectionDialog
        app = QApplication.instance() or QApplication([])
        frame = pd.DataFrame({"Wafer ID": ["W1", "W2", "W3", "W4"], "CD": [1., 2., 3., 4.]})
        dialog = FrameSelectionDialog(frame)
        try:
            dialog.filter_groups = [[{"column": "CD", "minimum": 3}]]
            dialog._rebuild_filter_rows()
            dialog.refresh_rows()
            self.assertEqual(dialog.model.rows, [0, 1, 2, 3])
            dialog.show_rows.setCurrentIndex(dialog.show_rows.findData("filtered"))
            self.assertEqual(dialog.model.rows, [2, 3])
            dialog.show_rows.setCurrentIndex(dialog.show_rows.findData("checked"))
            self.assertEqual(dialog.model.rows, [2, 3])
            dialog.model.setData(dialog.model.index(0, 0), Qt.CheckState.Unchecked,
                                 Qt.ItemDataRole.CheckStateRole)
            dialog.show_rows.setCurrentIndex(dialog.show_rows.findData("unchecked"))
            self.assertEqual(dialog.model.rows, [2])
        finally:
            dialog.deleteLater()
            app.processEvents()

    def test_frame_selection_keeps_its_filter_rows_when_reopened(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.data_selection import FrameSelectionDialog
        app = QApplication.instance() or QApplication([])
        frame = pd.DataFrame({"Wafer ID": ["W1", "W2", "W3"], "CD": [1., 2., 3.]})
        dialog = FrameSelectionDialog(
            frame,
            filters=[[{"column": "CD", "minimum": 2}]], row_bools=[[]],
            group_bools=[], show="filtered")
        try:
            self.assertEqual(dialog.model.rows, [1, 2])
            self.assertEqual(dialog.show_rows.currentData(), "filtered")
            dialog.accept()
            self.assertEqual(dialog.saved_filters, [[{"column": "CD", "minimum": 2}]])
            self.assertEqual(dialog.saved_show, "filtered")
        finally:
            dialog.deleteLater()
            app.processEvents()

    def test_frame_selection_dialog_shows_order_and_reference_columns(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.data_selection import FrameSelectionDialog
        app = QApplication.instance() or QApplication([])
        frame = pd.DataFrame({"Wafer ID": ["W1", "W2"], "CD": [1., 2.]})
        dialog = FrameSelectionDialog(
            frame,
            extra_frames=[("Order", pd.DataFrame({"TestFlag": [0, 1]})),
                          ("Reference", pd.DataFrame({"CD Reference": [3., 5.]}))])
        try:
            for name in ("Order / TestFlag", "Reference / CD Reference", "Raw Data / Wafer ID"):
                self.assertIn(name, dialog.model.headers)
            self.assertEqual(dialog.model.rowCount(), 2)
        finally:
            dialog.deleteLater()
            app.processEvents()

    def test_wafer_map_pages_keep_all_metrics_of_a_wafer_together(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.plot_page import PlotPage
        app = QApplication.instance() or QApplication([])
        page = PlotPage()
        try:
            page.page_size.setValue(2)
            for index, expected in ((0, (["A", "B"], 0, 3)),
                                    (1, (["C", "D"], 1, 3)),
                                    (9, (["E"], 2, 3))):
                page.page_index = index
                self.assertEqual(page.paginate_wafers(["A", "B", "C", "D", "E"]), expected)
        finally:
            page.deleteLater()
            app.processEvents()

    def test_child_window_radio_switches_between_workbook_and_full_data_selection(self):
        from types import SimpleNamespace
        from PyQt6.QtWidgets import QComboBox
        from metrology_app.match_groups import participation_source_keys
        w = MainWindow()
        try:
            w.set_table(pd.DataFrame({"Wafer ID": ["W1", "W2"], "Value": [1., 2.]}), "Clipboard")
            frame = w.model.frame()
            keys = participation_source_keys(frame)
            self.assertFalse(w.workbook_selection_action.isVisible())
            self.assertFalse(w.full_data_action.isVisible())
            owner = SimpleNamespace(match_type=QComboBox(),
                                    document=SimpleNamespace(
                                        path=None,
                                        identity_timer=SimpleNamespace(start=lambda: None)),
                                    _workspace_data_follows_workbook=lambda: True)
            w.configure_workbook_owner(owner, "map.preview")
            self.assertTrue(w.workbook_selection_action.isVisible())
            self.assertTrue(w.full_data_action.isVisible())
            w._participation_excluded = {keys[1]}
            w.update_plan()
            self.assertEqual(w.participating_positions(frame), {0})
            used = {row for rows in w.selection["groups"].values() for row in rows}
            self.assertNotIn(1, used)
            w.full_data_action.trigger()
            self.assertEqual(w.participating_positions(frame), {0, 1})
            self.assertFalse(w._workbook_selection_applies)
            w.workbook_selection_action.trigger()
            self.assertEqual(w.participating_positions(frame), {0})
            self.assertTrue(w._workbook_selection_applies)
        finally:
            w._managed_owner = None
            w.model.undo.setClean()
            w.close()
            w.deleteLater()
            APP.processEvents()

    def setUp(self):
        self.window = MainWindow()
        self.window.load_path(ROOT / "sample_data" / "OCD_measurement_data.csv")
        self.source_shape = read_table(ROOT / "sample_data" / "OCD_measurement_data.csv").shape

    def tearDown(self):
        self.window.model.undo.setClean()
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def test_recognition_and_array_selection(self):
        w = self.window
        self.assertEqual(w.tabs.count(), 3)
        self.assertEqual(w._frame.shape, self.source_shape)
        self.assertEqual((len(w.selection["wafers"]), len(w.selection["metrics"])), (6, 0))
        self.assertEqual(w.parameter_list.topLevelItemCount(), self.source_shape[1])
        w.wafer_list.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
        self.assertEqual(len(w.selection["wafers"]), 5)
        w.check_all(w.parameter_list, False)
        self.assertEqual(len(w.selection["metrics"]), 0)
        w.check_all(w.parameter_list, True)
        # Wafer Map also exposes numeric MSE, GOF, NGOF and LBH; regIter
        # remains bookkeeping rather than a selectable parameter.
        self.assertEqual(len(w.selection["metrics"]), 19)

    def test_card_option_stays_disabled_without_match_workbook_cards(self):
        """A stand-alone table has no Cards, so the Data-tab option is inert."""
        w = self.window
        self.assertEqual(w.parameter_cards, {})
        self.assertFalse(w.card_check.isEnabled())
        self.assertFalse(w.card_check.isChecked())

    def test_section_guidance_is_available_from_titles_not_inline_comments(self):
        labels = self.window.findChildren(QLabel)
        titles = {label.text(): label for label in labels}
        expected_help = {
            "Measurement table": "Row 1 = headers · Ctrl+V pastes cells.",
            "Wafers": "Checked metadata headers form one measurement identity.",
            "Parameters": "Each selected parameter becomes one column.",
        }

        for title, help_text in expected_help.items():
            self.assertIn(title, titles)
            self.assertEqual(titles[title].toolTip(), help_text)

        visible_text = {label.text() for label in labels}
        for help_text in expected_help.values():
            self.assertNotIn(help_text.removesuffix("."), visible_text)
        self.assertEqual(self.window.wafer_list.toolTip(), "")
        self.assertEqual(self.window.parameter_list.toolTip(), "")

    def test_filter_keeps_selection(self):
        w = self.window
        w.search.setText("OCD_H")
        visible = [w.parameter_list.topLevelItem(i) for i in range(w.parameter_list.topLevelItemCount())
                   if not w.parameter_list.topLevelItem(i).isHidden()]
        self.assertEqual(len(visible), 3)
        self.assertEqual((len(w.selection["wafers"]), len(w.selection["metrics"])), (6, 0))

    def test_sidebar_keeps_its_scroll_position_when_the_table_is_rebuilt(self):
        w = self.window
        w.resize(1200, 520)
        w.show()
        APP.processEvents()
        bar = w.parameter_list.verticalScrollBar()
        bar.setValue(bar.maximum())
        APP.processEvents()
        scrolled = bar.value()
        self.assertGreater(scrolled, 0)

        w.recognize()
        APP.processEvents()

        self.assertEqual(w.parameter_list.verticalScrollBar().value(), scrolled)

    def test_replacing_table_keeps_available_wafer_and_parameter_selections(self):
        w = self.window
        w.check_all(w.wafer_list, False)
        chosen_wafer = w.wafer_list.topLevelItem(0)
        chosen_wafer.setCheckState(0, Qt.CheckState.Checked)
        chosen_key = chosen_wafer.data(0, Qt.ItemDataRole.UserRole)
        chosen_parameter = next(
            w.parameter_list.topLevelItem(index)
            for index in range(w.parameter_list.topLevelItemCount())
            if w.parameter_list.topLevelItem(index).text(0) == "OCD_H1"
        )
        chosen_parameter.setCheckState(0, Qt.CheckState.Checked)

        replacement = w._frame.copy()
        replacement["OCD_H1"] = "999"
        w.set_table(replacement, "Replacement clipboard")

        self.assertEqual(w.selection["wafers"], [chosen_key])
        self.assertEqual(w.selection["metrics"], ["OCD_H1"])
        self.assertEqual(w.plot_page.selection["metrics"], ["OCD_H1"])
        self.assertEqual(set(w._frame["OCD_H1"]), {"999"})

    def test_standalone_dirty_workspace_still_confirms_before_closing(self):
        w = self.window
        w.model.edit({(1, 1): "changed"})
        with patch.object(
            QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Cancel,
        ) as discard_prompt:
            closed = w.close()

        self.assertFalse(closed)
        discard_prompt.assert_called_once()

    def test_clicking_anywhere_on_a_row_toggles_it(self):
        w = self.window
        w.show()
        APP.processEvents()
        wafer = w.wafer_list.topLevelItem(0)
        rect = w.wafer_list.visualItemRect(wafer)
        QTest.mouseClick(w.wafer_list.viewport(), Qt.MouseButton.LeftButton,
                         pos=QPoint(rect.left() + 100, rect.center().y()))
        self.assertEqual(wafer.checkState(0), Qt.CheckState.Unchecked)
        self.assertEqual((len(w.selection["wafers"]), len(w.selection["metrics"])), (5, 0))

        metric = next(w.parameter_list.topLevelItem(i) for i in range(w.parameter_list.topLevelItemCount())
                      if w.parameter_list.topLevelItem(i).text(0) == "OCD_H1")
        w.parameter_list.scrollToItem(metric)
        APP.processEvents()
        rect = w.parameter_list.visualItemRect(metric)
        QTest.mouseClick(w.parameter_list.viewport(), Qt.MouseButton.LeftButton,
                         pos=QPoint(rect.left() + 100, rect.center().y()))
        self.assertEqual(metric.checkState(0), Qt.CheckState.Checked)
        self.assertEqual((len(w.selection["wafers"]), len(w.selection["metrics"])), (5, 1))

    def test_grouping_fields_are_multiselect(self):
        w = self.window
        self.assertTrue(all(w.group_checks[name].isChecked() for name in ("Wafer ID", "Lot ID", "PAD Name")))
        w.show()
        w.group_menu.popup(w.group_picker.mapToGlobal(QPoint(0, w.group_picker.height())))
        APP.processEvents()
        pad = w.group_checks["PAD Name"]
        QTest.mouseClick(w.group_menu, Qt.MouseButton.LeftButton,
                         pos=w.group_menu.actionGeometry(pad).center())
        self.assertTrue(w.group_menu.isVisible())
        self.assertFalse(pad.isChecked())
        w.group_menu.close()
        self.assertNotIn("Die Seq", w.group_checks)
        self.assertEqual((len(w.selection["wafers"]), len(w.selection["metrics"])), (3, 0))
        self.assertEqual(w.group_picker.text(), "Wafer ID / Lot ID")
        w.group_checks["PAD Name"].setChecked(True)
        self.assertEqual((len(w.selection["wafers"]), len(w.selection["metrics"])), (6, 0))

    def test_edits_reidentify_wafers_and_headers(self):
        w = self.window
        w.model.edit({(1, 1): "NEW-WAFER"})
        w.recognize()
        self.assertEqual(w.wafer_list.topLevelItemCount(), 7)
        w.model.edit({(0, 1): "Sample"})
        w.recognize()
        w.group_checks["Sample"].setChecked(True)
        self.assertEqual(w.selection["wafer_column"], "Sample")
        self.assertEqual(len(w.selection["wafers"]), 7)

    def test_grid_paste_and_keyboard_undo(self):
        w = self.window
        w.show()
        w.sheet.setFocus()
        w.sheet.setCurrentIndex(w.model.index(1, 13))
        before = w.model.cells[(1, 13)]
        APP.clipboard().setText("111\t222\n333\t444")
        QTest.keyClick(w.sheet, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(w.model.cells[(2, 14)], "444")
        QTest.keyClick(w.sheet, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(w.model.cells[(1, 13)], before)

    def test_full_table_paste_xlsx_and_save(self):
        w = self.window
        APP.clipboard().setText("Wafer ID\tValue\n001\t2.10\n002\t3.20")
        w.paste_table()
        self.assertEqual(w._frame.shape, (2, 2))
        self.assertEqual([w.selection["labels"][key] for key in w.selection["wafers"]], ["001", "002"])
        with tempfile.TemporaryDirectory() as folder:
            xlsx = Path(folder) / "sample.xlsx"
            w._frame.to_excel(xlsx, index=False)
            w.load_path(xlsx)
            self.assertEqual(w._frame.iloc[0, 0], "001")
            csv = Path(folder) / "saved.csv"
            w.model.edit({(1, 1): "9.80"})
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(csv), "")):
                w.save_table()
            self.assertEqual(read_table(csv, dtype=str).iloc[0, 1], "9.80")
            self.assertFalse(w.model.undo.isClean())
            self.assertIsNone(w.workspace_path)  # CSV export is not a WKB save.

    def test_auto_rename_numbers_duplicate_headers_in_column_order(self):
        """The Auto rename button fixes repeated row-1 names without touching data."""
        import pandas as pd

        w = self.window
        frame = pd.DataFrame([["W1", 1, 2, 3], ["W2", 4, 5, 6]],
                             columns=["Wafer ID", "Value", "Value", "Value_2"])
        w.set_table(frame, "Clipboard")
        w.recognize()
        self.assertIn("Duplicate", w.message.text())
        self.assertFalse(w.auto_rename_button.isHidden())
        self.assertFalse(w.warning_banner.isHidden())
        self.assertGreaterEqual(w.warning_banner.minimumHeight(), 44)
        self.assertIs(w.auto_rename_button.parentWidget(), w.warning_banner)
        self.assertEqual(w.message.objectName(), "warningText")
        self.assertEqual(w.auto_rename_button.objectName(), "warningAction")
        before = dict(w.model.cells)

        w.auto_rename_button.click()
        # Repeated names start at _1; an existing _2 stays unchanged.
        self.assertEqual(w.model.headers(), ["Wafer ID", "Value", "Value_1", "Value_2"])
        self.assertTrue(w.auto_rename_button.isHidden())
        self.assertTrue(w.message.isHidden())   # the warning banner is gone
        self.assertTrue(w.warning_banner.isHidden())
        self.assertEqual(w._frame.shape, (2, 4))
        # Only row-1 names change: the measurement rows are byte-identical.
        self.assertEqual({key: value for key, value in w.model.cells.items() if key[0]},
                         {key: value for key, value in before.items() if key[0]})
        self.assertEqual(sorted(w._frame.columns), ["Value", "Value_1", "Value_2", "Wafer ID"])

        w.model.undo.undo()
        self.assertEqual(w.model.headers(), ["Wafer ID", "Value", "Value", "Value_2"])
        w.model.undo.redo()
        self.assertEqual(w.model.headers(), ["Wafer ID", "Value", "Value_1", "Value_2"])

    def test_duplicate_headers_and_unsaved_cancel(self):
        w = self.window
        w.model.edit({(0, 2): "Wafer ID"})
        w.recognize()
        self.assertIn("Duplicate", w.message.text())
        self.assertEqual((len(w.selection["wafers"]), len(w.selection["metrics"])), (0, 0))
        w.model.undo.undo()
        w.recognize()
        self.assertEqual(w._frame.shape, self.source_shape)
        w.model.edit({(1, 13): "123"})
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            w.new_table()
        self.assertEqual(w.model.cells[(1, 13)], "123")


if __name__ == "__main__":
    unittest.main()
