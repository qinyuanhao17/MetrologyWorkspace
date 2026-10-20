"""Editable source identities and their Wafer selectors stay independent."""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from metrology_app.correlation_window import CorrelationWindow
from metrology_app.matching_window import MatchingWindow

APP = QApplication.instance() or QApplication([])


class CorrelationSourceIdentityTests(unittest.TestCase):
    def setUp(self):
        self.window = CorrelationWindow()
        self.raw = pd.DataFrame({
            "Wafer ID": ["RAW1"] * 3, "Lot ID": ["LOT1"] * 3,
            "Die Seq": ["001", "003", "008"], "CD": ["1.00", "2.00", "3.00"],
        })

    def tearDown(self):
        self.window.document.force_close = True
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def test_ref_only_edits_refresh_wafer_recognition_and_grouping_menu(self):
        w = self.window
        w.set_reference_table(self.raw)
        w.reference_model.edit({(0, 0): "Sample", (1, 0): "REF2"})
        w.recognize()
        self.assertIn("Sample", w.reference_group_checks)
        self.assertNotIn("Wafer ID", w.reference_group_checks)
        w.reference_group_checks["Sample"].setChecked(True)
        self.assertEqual(w.reference_wafer_list.topLevelItemCount(), 2)
        self.assertTrue(w.reference_group_picker.isEnabled())

    def test_pasting_cells_into_initially_blank_ref_enables_wafer_menu(self):
        w = self.window
        w.set_reference_table(pd.DataFrame())
        w.reference_model.edit({
            (0, 0): "Wafer ID", (0, 1): "CD", (1, 0): "REF1", (1, 1): "1.000",
        })
        # Wait for the ordinary edit debounce, not a fixed delay sensitive to
        # queued rendering from other GUI tests. Never invoke recognize here.
        for _ in range(80):
            if w.reference_group_picker.isEnabled():
                break
            QTest.qWait(25)
        self.assertTrue(w.reference_group_picker.isEnabled())
        self.assertIn("Wafer ID", w.reference_group_checks)
        self.assertEqual(w.reference_wafer_list.topLevelItem(0).text(0), "REF1")

    def test_ref_only_measurements_can_draw_both_analysis_pages(self):
        w = self.window
        reference = self.raw.assign(Depth=["2.00", "4.00", "6.00"])
        w.set_reference_table(reference)
        w.recognize()
        self.assertEqual([source["name"] for source in w.selection["sources"]], ["Reference"])
        for page in (w.correlation_page, w.sequence_page):
            page.selector.selectAll()
            page.draw_plot()
            self.assertTrue(page.ready, page.status.text())
        pd.testing.assert_frame_equal(w.reference_model.document_frame(), reference)

    def test_imported_ref_identity_is_not_replaced_by_existing_or_later_raw(self):
        w = self.window
        reference = self.raw.assign(**{"Wafer ID": ["REF1"] * 3, "Die Seq": ["010", "020", "030"]})
        for ref_first in (False, True):
            with self.subTest(ref_first=ref_first):
                w.set_reference_table(pd.DataFrame())
                w.set_table(pd.DataFrame(), "Empty Raw")
                if ref_first:
                    w.set_reference_table(reference)
                    w.set_table(self.raw, "Raw")
                else:
                    w.set_table(self.raw, "Raw")
                    w.set_reference_table(reference)
                pd.testing.assert_frame_equal(w.reference_model.document_frame(), reference)
                w.set_workbook_sources(self.raw, ())
                pd.testing.assert_frame_equal(w.reference_model.document_frame(), reference)

    def test_ref_identity_edits_survive_recognition_and_wafer_check_changes(self):
        w = self.window
        w.set_sources(pd.DataFrame({"REF CD": ["2.00", "4.00", "6.00"]}), self.raw, ())
        w.reference_model.edit({(1, 0): "REF2", (1, 3): "8.12345000"})
        before = w.reference_model.document_frame().copy()
        w.recognize()
        pd.testing.assert_frame_equal(w.reference_model.document_frame(), before)
        item = w.reference_wafer_list.topLevelItem(0)
        item.setCheckState(0, Qt.CheckState.Unchecked)
        w.reference_group_checks["Lot ID"].setChecked(True)
        pd.testing.assert_frame_equal(w.reference_model.document_frame(), before)
        self.assertTrue(w.reference_model.undo.canUndo())

    def test_ref_header_and_literal_edits_can_be_undone_after_grouping_changes(self):
        w = self.window
        w.set_sources(pd.DataFrame({"REF CD": ["2.00", "4.00", "6.00"]}), self.raw, ())
        original = w.reference_model.document_frame().copy()
        w.reference_model.edit({(0, 0): "Sample", (1, 0): "REF2", (1, 3): "8.12345000"})
        edited = w.reference_model.document_frame().copy()
        w.recognize()
        w.reference_group_checks["Sample"].setChecked(True)
        w.reference_group_checks["Lot ID"].setChecked(True)
        w.reference_wafer_list.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
        w.recognize()
        pd.testing.assert_frame_equal(w.reference_model.document_frame(), edited)
        w.reference_model.undo.undo()
        w.recognize()
        pd.testing.assert_frame_equal(w.reference_model.document_frame(), original)
        w.reference_model.undo.redo()
        w.recognize()
        pd.testing.assert_frame_equal(w.reference_model.document_frame(), edited)

    def test_linked_raw_refresh_and_reopen_preserve_manual_ref_identity(self):
        parent = MatchingWindow()
        restored = None
        try:
            parent.match_type.setCurrentText("NOVA")
            parent.set_reference_frame(pd.DataFrame({"CD": ["2", "4", "6"]}))
            parent.set_raw_frame(self.raw)
            parent.mapping_table.cellWidget(0, 3).setCurrentText("CD")
            parent.mapping_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
            parent.run_analysis()
            child = parent.open_correlation_workspace()
            manual = self.raw.assign(**{"Wafer ID": ["REF1"] * 3})
            child.set_reference_table(manual)
            child.reference_model.edit({(1, 0): "REF2", (1, 3): "9.12345000"})
            child.recognize()
            child.reference_group_checks["Lot ID"].setChecked(True)
            child.reference_wafer_list.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
            before = child.reference_model.document_frame().copy()
            selected = child.selected(child.reference_wafer_list)
            parent.raw_model.edit({(1, 0): "RAW2", (1, 3): "1.23450000"})
            parent.run_analysis()
            pd.testing.assert_frame_equal(child.reference_model.document_frame(), before)
            self.assertTrue(child.reference_group_checks["Lot ID"].isChecked())
            self.assertEqual(child.selected(child.reference_wafer_list), selected)
            self.assertTrue(child.reference_model.undo.canUndo())
            with TemporaryDirectory() as folder:
                path = Path(folder) / "manual-ref-identity.mwkb"
                parent.save_workbook(path)
                restored = MatchingWindow()
                restored.load_workbook(path)
                reopened = restored.open_correlation_workspace()
                pd.testing.assert_frame_equal(reopened.reference_model.document_frame(), before)
        finally:
            for window in (parent, restored):
                if window is not None:
                    window.document.force_close = True
                    window.close()
                    window.deleteLater()
            APP.processEvents()

    def test_ref_and_raw_grouping_menus_remain_open_after_repeated_check_changes(self):
        w = self.window
        w.set_sources(pd.DataFrame({"REF CD": ["2.00", "4.00", "6.00"]}), self.raw, ())
        w.show()
        APP.processEvents()
        for page, picker, menu, checks in (
            (w.reference_page, w.reference_group_picker, w.reference_group_menu, w.reference_group_checks),
            (w.tabs.widget(1), w.group_picker, w.group_menu, w.group_checks),
        ):
            with self.subTest(source=page):
                w.tabs.setCurrentWidget(page)
                menu.popup(picker.mapToGlobal(QPoint(0, picker.height())))
                APP.processEvents()
                self.assertTrue(menu.isVisible())
                action = checks["Lot ID"]
                initial = action.isChecked()
                for expected in (not initial, initial):
                    QTest.mouseClick(menu, Qt.MouseButton.LeftButton,
                                     pos=menu.actionGeometry(action).center())
                    APP.processEvents()
                    self.assertEqual(action.isChecked(), expected)
                    self.assertTrue(menu.isVisible())
                menu.close()

    def test_raw_identity_edits_survive_recognition_and_wafer_check_changes(self):
        w = self.window
        w.set_sources(pd.DataFrame({"REF CD": ["2.00", "4.00", "6.00"]}), self.raw, ())
        w.raw_model.edit({(1, 0): "RAW2", (1, 3): "9.12345000"})
        before = w.raw_model.document_frame().copy()
        w.recognize()
        w.wafer_list.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
        w.group_checks["Lot ID"].setChecked(True)
        pd.testing.assert_frame_equal(w.raw_model.document_frame(), before)
        self.assertTrue(w.raw_model.undo.canUndo())
