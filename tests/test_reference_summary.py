"""Reference Summary engine and compact-window regression tests."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QTableView, QTableWidget

from metrology_app.cdsem1 import _write_workbook
from metrology_app.module_registry import create_default_registry
from metrology_app.reference_summary_window import (
    ReferenceSummaryRequest,
    ReferenceSummaryWindow,
    run_reference_summary,
)


APP = QApplication.instance() or QApplication([])
CDSEM_HEADERS = [
    "Lot_ID", "Wafer_ID", "Slot_No", "Chip_X", "Chip_Y", "File_Name",
    "Date", "Device", "Class", "Recipe_Name", "ACD_No", "MP_Name",
    "No", "Seq_No", "Wafer_X", "Wafer_Y", "Result", "Mean",
]


def synthetic_cdsem(path):
    rows = [
        CDSEM_HEADERS,
        ["L1", "W01", "01", "1", "0", "a.msr", "2026-01-01", "D", "C", "R", "CD", "MP-A", "1", "S1", "100", "200", "30.1", "30 nm"],
        ["L1", "W01", "01", "1", "0", "a.msr", "2026-01-01", "D", "C", "R", "CD", "MP-B", "2", "S2", "111", "222", "31.2", "31 nm"],
        ["L1", "W01", "01", "1", "0", "a.msr", "2026-01-01", "D", "C", "R", "ACD01", "MP-X", "3", "S3", "100", "200", "99", "99 nm"],
    ]

    def first_sheet():
        for row in rows:
            yield row, CDSEM_HEADERS

    _write_workbook(path, [
        ("Raw", first_sheet(), 1, len(CDSEM_HEADERS), [], 0),
        ("Ignored", iter([(["MP_Name", "DO_NOT_READ"], ["", ""])]), 1, 2, [], 0),
    ])


class ReferenceSummaryTests(unittest.TestCase):
    def test_registered_window_uses_compact_summary_without_measurement_preview(self):
        registry = create_default_registry()
        self.assertEqual(registry.get("reference_summary").title, "Reference Summary")
        window = registry.create("reference_summary")
        try:
            self.assertIsInstance(window, ReferenceSummaryWindow)
            self.assertEqual(
                [window.vendor.itemText(index) for index in range(window.vendor.count())],
                ["NOVA", "PMISH", "KLA", "CDSEM1"],
            )
            self.assertEqual(window.findChildren(QTableView), [])
            self.assertEqual(window.findChildren(QTableWidget), [])
            self.assertIn(
                "intentionally not previewed",
                next(label for label in window.findChildren(type(window.vendor_description))
                     if label.text() == "Run summary").toolTip(),
            )
        finally:
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_vendor_change_clears_incompatible_source_selection(self):
        window = ReferenceSummaryWindow()
        try:
            with tempfile.TemporaryDirectory() as folder:
                csv_path = Path(folder) / "nova.csv"
                csv_path.write_text("WaferID,CD\nW1,10\n", encoding="utf-8")
                window.set_source_files([csv_path])
                self.assertEqual(window.source_list.count(), 1)
                window.vendor.setCurrentText("CDSEM1")
                self.assertEqual(window.source_list.count(), 0)
                self.assertFalse(window.run_button.isEnabled())
                self.assertIn("first sheet", window.vendor_description.text())
        finally:
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_nova_summary_keeps_rows_and_removes_duplicate_header_and_lbh(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "nova.csv"
            source.write_text(
                "WaferID,CD,CD_LBH\nW1,10,1\nWaferID,CD,CD_LBH\nW2,20,2\n",
                encoding="utf-8",
            )
            report = run_reference_summary(
                ReferenceSummaryRequest("NOVA", (source,), root)
            )
            self.assertEqual(report.result.input_rows, 2)
            self.assertEqual(report.result.kept_rows, 2)
            output = report.result.output_dir / "NOVA_merged.csv"
            self.assertTrue(output.is_file())
            self.assertNotIn("CD_LBH", output.read_text(encoding="utf-8-sig").splitlines()[0])

    def test_cdsem_summary_reads_first_sheet_and_exports_results_without_row_preview(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "cdsem.xlsx"
            synthetic_cdsem(source)
            report = run_reference_summary(
                ReferenceSummaryRequest("CDSEM1", (source,), root)
            )
            self.assertEqual(report.result.input_rows, 2)
            self.assertEqual(report.result.kept_rows, 2)
            self.assertEqual(report.result.site_count, 1)
            self.assertEqual(report.result.mp_count, 2)
            self.assertEqual(len(list(report.result.output_dir.glob("*_Results.csv"))), 1)
            self.assertEqual(len(list(report.result.output_dir.glob("*.xlsx"))), 1)


if __name__ == "__main__":
    unittest.main()
