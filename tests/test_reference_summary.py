"""Reference Summary engine and compact-window regression tests."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel, QTableView, QTableWidget
from metrology_app.reference_merge import parse_file

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
    def test_every_vendor_selects_and_scans_csv_and_first_sheet_excel(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            sources=[root/'a.csv',root/'b.xlsx',root/'c.xlsm']
            for path in sources:
                path.write_bytes(b'test selection only')
            (root/'~$lock.xlsx').write_bytes(b'ignore')
            window=ReferenceSummaryWindow()
            self.addCleanup(window.close)
            self.addCleanup(window.deleteLater)
            for vendor in ('NOVA','PMISH','KLA','CDSEM1'):
                window.vendor.setCurrentText(vendor)
                window.set_source_files(sources)
                self.assertEqual(set(window.files),set(sources),vendor)
                window.set_source_folders([root])
                self.assertEqual(set(window.files),set(sources),vendor)

    def test_multiple_source_folders_scan_recursively_without_duplicate_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first, second = root/'first',root/'second'
            first.mkdir(); second.mkdir()
            (first/'a.csv').write_text('WaferID,X\nA,1\n')
            (second/'b.CSV').write_text('WaferID,X\nB,2\n')
            (second/'ignored.txt').write_text('not CSV')
            window = ReferenceSummaryWindow()
            self.addCleanup(window.close)
            window.set_source_folders((first,second,root))
            self.assertEqual(set(window.files),{(first/'a.csv').resolve(),(second/'b.CSV').resolve()})
            self.assertEqual(window.output_parent,first)

    def test_long_pmish_channel_output_can_be_loaded_into_alignment(self):
        from metrology_app.reference_alignment import load_alignment_output
        from metrology_app.file_paths import filesystem_path
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / ('nested-' * 12)
            root.mkdir()
            import shutil
            source = root / 'pmish.csv'
            source.write_text('WaferID:,W1,LotID:,L1\n'
                'Num,Seq,Pad name,RefDieCol,RefDieRow,X(mm),Y(mm),Recipe,Metrology unit,AzimuthAngle\n'
                '1,1,P,0,0,1.00,2.00,Recipe_very_long_channel_name_1234567890,UVSE,45\n',encoding='utf-8')
            report = run_reference_summary(ReferenceSummaryRequest('PMISH',(source,),root))
            output = next(p for p in report.output_files if not p.name.startswith('_'))
            self.assertGreater(len(str(output.resolve())),260)
            self.assertTrue(filesystem_path(output).is_file())
            frame = load_alignment_output(output)
            self.assertEqual(frame['X(mm)'].tolist(),['1.00'])
            # Python's plain TemporaryDirectory cleanup cannot traverse >260-char paths.
            shutil.rmtree(filesystem_path(root.resolve()))

    def test_nova_trailing_empty_fields_keep_values_and_collapse_lbh(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "results.csv"
            path.write_text('WaferID,Note,CD,A_LBH,B_LBH\n'
                            'W1,"quoted, comma", 10.000 ,NO_LBH,NO_LBH,\n'
                            'W2,plain,20,NO_LBH,OTHER,,\n'
                            'W3,plain,30,,NO_LBH,\n', encoding="utf-8")
            parsed = parse_file(path, "NOVA")
            rows = [record["data"] for record in parsed.records]
            self.assertEqual([row["LBH"] for row in rows], ["0", "1", "1"])
            self.assertEqual(rows[0]["Note"], "quoted, comma")
            self.assertEqual(rows[0]["CD"], " 10.000 ")
            self.assertNotIn("A_LBH", rows[0])
            self.assertNotIn("B_LBH", rows[0])
            self.assertEqual([record["line"] for record in parsed.records], [2, 3, 4])
            path.write_text('WaferID,CD\nW1,10,unexpected\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "width mismatch"):
                parse_file(path, "NOVA")
            path.write_text('WaferID,CD\nW1\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "width mismatch"):
                parse_file(path, "NOVA")

    def test_registered_window_uses_compact_summary_without_measurement_preview(self):
        registry = create_default_registry()
        self.assertEqual(registry.get("reference_summary").title, "Reference Summarizer")
        window = registry.create("reference_summary")
        try:
            self.assertIsInstance(window, ReferenceSummaryWindow)
            self.assertTrue(window.windowTitle().startswith("Reference Summarizer"))
            self.assertEqual(
                [window.vendor.itemText(index) for index in range(window.vendor.count())],
                ["NOVA", "PMISH", "KLA", "CDSEM1"],
            )
            self.assertEqual(window.tabs.widget(0).findChildren(QTableView), [])
            self.assertEqual(window.tabs.widget(0).findChildren(QTableWidget), [])
            self.assertEqual([window.tabs.tabText(i) for i in range(2, window.tabs.count())],
                             ["3. XY Bias", "4. Data", "5. Correlation",
                              "6. Trend", "7. WaferMap", "8. Radius Plot"])
            self.assertIn(
                "intentionally not previewed",
                next(label for label in window.findChildren(QLabel)
                     if label.text() == "Run summary").toolTip(),
            )
            labels = [label.text() for label in window.findChildren(QLabel)]
            self.assertIn("Vendor", labels)
            self.assertNotIn("Source", labels)
            self.assertFalse(window.findChildren(QLabel, "pageTitle"))
            self.assertNotIn("Consolidate NOVA", " ".join(labels))
            self.assertNotIn("Combine regular NOVA", " ".join(labels))
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
                self.assertIn("first sheet", window.vendor.toolTip())
        finally:
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_scanned_folders_offer_checkboxes_and_run_only_checked_files(self):
        from time import monotonic
        from PyQt6.QtCore import QPoint, Qt
        from PyQt6.QtTest import QTest
        from unittest.mock import patch

        window = ReferenceSummaryWindow()
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                folders = [root / name for name in ('A', 'B')]
                paths = []
                for subfolder in folders:
                    subfolder.mkdir()
                    path = subfolder / 'reference.csv'
                    path.write_text('WaferID,CD\nW1,10\n')
                    paths.append(path.resolve())
                with patch('metrology_app.reference_summary_window.choose_folders',
                           return_value=(*folders, root)):
                    window.choose_folder()
                self.assertEqual(window.selected_source_files(), tuple(paths))
                window.show()
                APP.processEvents()
                row = window.source_list.visualItemRect(window.source_list.item(0))
                position = QPoint(row.left() + 80, row.center().y())
                for check in (False, True, False):
                    QTest.mouseClick(window.source_list.viewport(), Qt.MouseButton.LeftButton, pos=position)
                    self.assertEqual(paths[0] in window.selected_source_files(), check)
                self.assertEqual(window.selected_source_files(), (paths[1],))
                window.run()
                deadline = monotonic() + 5
                while window.worker is not None and monotonic() < deadline:
                    QTest.qWait(10)
                self.assertIsNone(window.worker)
                self.assertEqual(window.report.request.files, (paths[1],))
        finally:
            window.close()
            window.deleteLater()
            APP.processEvents()

    @unittest.skipUnless(os.name == 'nt', 'Windows native folder dialog')
    def test_native_folder_dialog_enables_multiple_filesystem_folders(self):
        import ctypes
        from unittest.mock import patch
        from metrology_app import windows_folder_dialog as dialog

        def cancel(instance, owner):
            flags = ctypes.c_uint32()
            dialog._invoke(instance, 10, (ctypes.POINTER(ctypes.c_uint32),), ctypes.byref(flags))
            expected = dialog.FOS_PICKFOLDERS | dialog.FOS_ALLOWMULTISELECT | dialog.FOS_FORCEFILESYSTEM
            self.assertEqual(flags.value & expected, expected)
            return dialog.CANCELLED

        with tempfile.TemporaryDirectory() as folder, patch.object(dialog, '_show', side_effect=cancel) as show:
            self.assertEqual(dialog.choose_windows_folders(0, 'Load folders', folder), ())
            show.assert_called_once()

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
