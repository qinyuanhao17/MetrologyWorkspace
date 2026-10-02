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

    def test_pasting_a_new_table_at_a1_replaces_and_reidentifies(self):
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
            w.sheet.paste()
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
            self.assertTrue(w.model.undo.isClean())

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
        # The second "Value" skips the suffix already taken by the last column,
        # so renaming never introduces a fresh duplicate.
        self.assertEqual(w.model.headers(), ["Wafer ID", "Value", "Value_3", "Value_2"])
        self.assertTrue(w.auto_rename_button.isHidden())
        self.assertTrue(w.message.isHidden())   # the warning banner is gone
        self.assertTrue(w.warning_banner.isHidden())
        self.assertEqual(w._frame.shape, (2, 4))
        # Only row-1 names change: the measurement rows are byte-identical.
        self.assertEqual({key: value for key, value in w.model.cells.items() if key[0]},
                         {key: value for key, value in before.items() if key[0]})
        self.assertEqual(sorted(w._frame.columns), ["Value", "Value_2", "Value_3", "Wafer ID"])

        w.model.undo.undo()
        self.assertEqual(w.model.headers(), ["Wafer ID", "Value", "Value", "Value_2"])
        w.model.undo.redo()
        self.assertEqual(w.model.headers(), ["Wafer ID", "Value", "Value_3", "Value_2"])

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
