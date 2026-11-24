"""Reference Summary engine and compact-window regression tests."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
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
    def test_reference_summarizer_exposes_match_workbook_group_controls(self):
        import pandas as pd
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        window = ReferenceSummaryWindow()
        window.document.force_close = True
        self.addCleanup(window.close)
        self.assertEqual(
            [action.text() for action in window.menuBar().actions()],
            ["File", "Data", "Groups", "Analysis"],
        )
        self.assertIsNone(window._analysis)
        startup_ui = window.workspace_snapshot().states["ui"]
        self.assertIsNone(window._analysis)
        window.show()
        menu_bar = window.menuBar()
        QTest.mouseClick(menu_bar, Qt.MouseButton.LeftButton,
                         pos=menu_bar.actionGeometry(window.groups_menu.menuAction()).center())
        app.processEvents()
        texts = [action.text() for action in window.groups_menu.actions() if not action.isSeparator()]
        for expected in ("Enable Groups", "Group settings…", "Manage groups…", "Plot labels"):
            self.assertIn(expected, texts)
        window.groups_menu.hide()
        self.assertEqual(window.workspace_snapshot().states["ui"], startup_ui)
        self.assertIs(window.tabs.widget(3), window.analysis.reference_page)

        aligned_ref = pd.DataFrame({
            "Wafer ID": ["R1", "R1", "R2", "R2"],
            "Lot ID": ["L1"] * 4,
            "PAD Name": ["P1"] * 4,
            "Die Seq": [1, 2, 1, 2],
            "CD": [25.0, 26.0, 27.0, 28.0],
        })
        raw = pd.DataFrame({
            "Wafer ID": ["D1", "D1", "D2", "D2"],
            "Lot ID": ["L1"] * 4,
            "PAD Name": ["P1"] * 4,
            "Die Seq": [1, 2, 1, 2],
            "TestFlag": [0, 0, 1, 1],
            "CD": [25.1, 26.1, 27.1, 28.1],
        })
        values = pd.DataFrame({"CD Reference": [25.0, 26.0, 27.0, 28.0]})
        window.analysis.set_alignment_inputs(
            (aligned_ref, raw, values, ("Field X", "Field Y"), {}), set(), False,
        )
        controls = window.analysis.display_options.controls
        controls.enabled.setChecked(True)
        self.assertTrue(window.analysis.display_options.apply_groups())
        plan = window.analysis._group_plan
        self.assertIsNotNone(plan)
        self.assertTrue(plan.enabled)
        self.assertTrue(plan.group_keys)
        shown = plan.group_keys[0]
        controls.set_display_groups([], [shown])
        window.analysis.display_options._context_cache = None
        window.analysis.display_options.refresh()
        self.assertEqual(window.analysis._group_plan.state["show_wafer_groups"], [shown])
        saved = window.workspace_snapshot().states["ui"]["analysis_options"]
        self.assertTrue(saved["local_applied"])
        self.assertEqual(saved["grouping"]["show_wafer_groups"], [shown])

        settings = next(action for action in window.groups_menu.actions()
                        if action.text() == "Group settings…")
        settings.trigger()
        dialog = window.analysis.display_options.dialog
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog.isVisible())
        self.assertTrue(dialog.set_flags_button.isEnabled())
        split = len(window.analysis.reference_model.frame())
        window.analysis._write_chart_flags({split}, "1")
        self.assertEqual(window.analysis.display_options.controls.flags_frame().iloc[0, 0], "1")
        self.assertEqual(window.analysis._group_plan.row_groups[-1], "All:1")
        dialog.reject()
        app.processEvents()

        from unittest.mock import patch
        from PyQt6.QtWidgets import QDialog
        from metrology_app.match_group_ui import CombinedGroupDialog
        manage = next(action for action in window.groups_menu.actions()
                      if action.text() == "Manage groups…")
        with patch.object(CombinedGroupDialog, "exec",
                          return_value=QDialog.DialogCode.Rejected) as open_manage:
            manage.trigger()
        open_manage.assert_called_once()

    def test_ref_save_suggests_wafer_and_date_and_writes_only_the_workspace(self):
        from unittest.mock import patch
        from PyQt6.QtCore import QDateTime
        from PyQt6.QtWidgets import QDialog, QFileDialog

        window, reopened = ReferenceSummaryWindow(), ReferenceSummaryWindow()
        for item in (window, reopened):
            item.document.force_close = True
            self.addCleanup(item.deleteLater)
            self.addCleanup(item.close)
        now = QDateTime.fromString("2026-11-21 22:03:59", "yyyy-MM-dd HH:mm:ss")

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'NOVA-source.csv'
            source.write_text('WaferID,LotID,SiteName,DateTime,ToolName,MARS_Library_Name,CD\n'
                              'W01,L03,PAD1,8/18/2026 12:11:14 PM,QH01,LIB1,25.20\n', encoding='utf-8')
            window.set_source_files([source])
            original = window.workspace_snapshot()
            with (patch.object(QDateTime, "currentDateTime", return_value=now),
                  patch.object(QDialog, "exec") as naming,
                  patch.object(QFileDialog, 'getSaveFileName', return_value=('', ''))):
                self.assertIsNone(window.save_reference())
            naming.assert_not_called()
            self.assertEqual(window.workspace_snapshot().states, original.states)

            name = 'NOVA_Wafer-W01_Lot-L03_PAD-PAD1_20261121_2203.ref'
            path = root / name
            unrelated = path.with_suffix('.txt')
            unrelated.write_text('Keep this note', encoding='utf-8')
            with (patch.object(QDateTime, "currentDateTime", return_value=now),
                  patch.object(QDialog, "exec") as naming,
                  patch.object(QFileDialog, 'getSaveFileName', return_value=(str(path), '')) as dialog):
                self.assertEqual(window.save_reference(), path)
            naming.assert_not_called()
            self.assertEqual(Path(dialog.call_args.args[2]).name, name)
            self.assertEqual(unrelated.read_text(encoding='utf-8'), 'Keep this note')
            self.assertEqual(list(root.glob('*.txt')), [unrelated])
            self.assertEqual(list(root.glob('*.html')), [])
            source.unlink()
            reopened.load_workspace(path)
            with (patch.object(QDialog, "exec") as naming,
                  patch.object(QFileDialog, "getSaveFileName") as location):
                self.assertEqual(reopened.save_reference(), path)
            naming.assert_not_called()
            location.assert_not_called()
            self.assertEqual(list(root.glob('*.txt')), [unrelated])
            self.assertEqual(list(root.glob('*.html')), [])

    def test_tab_one_loads_selected_ref_output_files(self):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QPushButton

        window = ReferenceSummaryWindow()
        window.document.force_close = True
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            outputs = [root / f"NOVA_{wafer}.csv" for wafer in ("W1", "W2")]
            for index, output in enumerate(outputs, 1):
                output.write_text(f"WaferID,ToolName,CD\nW{index},Tool{index},25\n", encoding="utf-8")
            self.assertIn(window.load_files_button, window.tabs.widget(0).findChildren(QPushButton))
            with patch("metrology_app.reference_summary_window.choose_files", return_value=outputs):
                window.load_files_button.click()
            picker = window.summary_output_picker
            self.assertEqual([picker.itemData(index) for index in range(picker.count())],
                             [str(output) for output in outputs])
            picker.setCurrentIndex(1)
            self.assertIn("Tool2", window.metadata_preview.toPlainText())
            self.assertEqual(window.alignment.output_picker.currentData(), str(outputs[1]))

    def test_tab_one_loads_ref_folders_and_switches_between_html_summaries(self):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QDialog, QPushButton
        from metrology_app.reference_metadata import MARKER

        window = ReferenceSummaryWindow()
        window.document.force_close = True
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / 'NOVA_merged.csv'
            input_text = ('WaferID,LotID,SiteName,DateTime,ToolName,MARS_Library_Name,CD\n'
                          'W01,L03,PAD1,8/18/2026 12:11:14 PM,QH01,A&B <LIB>,25.20\n')
            output.write_text(input_text, encoding='utf-8')
            second = root / 'PMISH_other.csv'
            second.write_text('WaferID,ToolSN,Recipe,CD\nW02,PM01,R1,25.30\n', encoding='utf-8')
            note = output.with_suffix('.summary.html')
            note.write_text('Keep this note', encoding='utf-8')
            self.assertIn(window.load_folders_button, window.tabs.widget(0).findChildren(QPushButton))
            for button in window.alignment.findChildren(QPushButton):
                self.assertFalse(button.text().startswith(('Load CSV', 'Load folders')))
            with patch('metrology_app.reference_alignment_ui.choose_folders', return_value=(root,)), \
                    patch.object(QDialog, 'exec', return_value=QDialog.DialogCode.Accepted):
                window.load_folders_button.click()
            summary = output.with_suffix('.summary2.html')
            text = summary.read_text(encoding='utf-8')
            self.assertTrue(text.startswith(MARKER))
            self.assertLess(text.index('ToolName'), text.index('WaferID'))
            self.assertLess(text.index('MARS_Library_Name'), text.index('Measurement time'))
            for value in ('QH01', 'A&amp;B &lt;LIB&gt;', 'W01', '8/18/2026 12:11:14 PM'):
                self.assertIn(value, text)
            self.assertEqual(note.read_text(encoding='utf-8'), 'Keep this note')
            self.assertEqual(output.read_text(encoding='utf-8'), input_text)
            picker = window.summary_output_picker
            self.assertEqual({picker.itemData(index) for index in range(picker.count())},
                             {str(output), str(second)})
            self.assertIn('A&B <LIB>', window.metadata_preview.toPlainText())
            self.assertEqual(window.result_path.text(), str(root))
            self.assertTrue(window.result_path.isReadOnly())
            listed = [window.output_list.item(index) for index in range(window.output_list.count())]
            self.assertEqual({item.text() for item in listed},
                             {output.name, second.name, summary.name, second.with_suffix('.summary.html').name})
            html_item = next(item for item in listed if item.text() == summary.name)
            window.output_list.setCurrentItem(html_item)
            window.output_list.itemClicked.emit(html_item)
            self.assertEqual(picker.currentData(), str(output))
            with patch('metrology_app.reference_summary_window.QDesktopServices.openUrl') as open_url:
                window.open_output_file()
            open_url.assert_not_called()
            self.assertIn('A&B <LIB>', window.metadata_preview.toPlainText())
            csv_item = next(item for item in listed if item.text() == output.name)
            window.output_list.setCurrentItem(csv_item)
            with patch('metrology_app.reference_summary_window.QDesktopServices.openUrl') as open_url:
                window.open_output_file()
            self.assertEqual(open_url.call_args.args[0].toLocalFile(), output.as_posix())
            window.output_list.itemClicked.emit(next(item for item in listed if item.text() == second.name))
            self.assertEqual(picker.currentData(), str(second))
            self.assertEqual(window.alignment.output_picker.currentData(), str(second))
            self.assertEqual(window.trend_page.output_picker.currentData(), str(second))
            self.assertIn('PM01', window.metadata_preview.toPlainText())
            self.assertTrue(second.with_suffix('.summary.html').is_file())
            window.trend_page.output_picker.setCurrentIndex(0)
            self.assertEqual(window.summary_output_picker.currentData(), str(output))
            self.assertIn('QH01', window.metadata_preview.toPlainText())

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
            root = Path(folder) / ('nested-' * 16)
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
            self.assertEqual([window.tabs.tabText(i) for i in range(window.tabs.count())],
                             ["1. Summary", "2. Wafer Alignment", "3. XY Bias", "4. Ref Data", "5. Raw Data",
                              "6. Correlation", "7. Trend", "8. Ref WaferMap", "9. Ref Radius Plot"])
            self.assertIn(
                "intentionally not previewed",
                next(label for label in window.findChildren(QLabel)
                     if label.text() == "Output").toolTip(),
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
        from openpyxl import load_workbook

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "nova.csv"
            source.write_text(
                "WaferID,LotID,SiteName,DateTime,ToolName,MARS_Library_Name,CD,CD_LBH\n"
                "W1,LOT-01,PAD1,8/18/2026 12:11:14 PM,tool,lib,10,1\n"
                "W1,LOT-01,PAD1,8/18/2026 12:11:14 PM,tool,lib,10,1\n"
                "WaferID,LotID,SiteName,DateTime,ToolName,MARS_Library_Name,CD,CD_LBH\n"
                "W2,LOT-01,PAD1,8/18/2026 12:11:14 PM,tool,lib,20,2\n",
                encoding="utf-8",
            )
            broken = root / 'broken.csv'
            broken.write_text('WaferID,CD\nW3,30,unexpected\n', encoding='utf-8')
            report = run_reference_summary(
                ReferenceSummaryRequest("NOVA", (source, broken), root)
            )
            self.assertEqual(report.result.input_rows, 3)
            self.assertEqual(report.result.kept_rows, 2)
            self.assertEqual(report.result.duplicates, 1)
            self.assertEqual(report.result.error_count, 2)
            self.assertIn('broken.csv', report.issue_lines[0])
            output = report.result.output_dir / 'NOVA_Wafer-W1(2)_Lot-LOT-01_PAD-PAD1.csv'
            self.assertTrue(output.parent.name.startswith('NOVA_20260818_121114_'))
            self.assertTrue(output.is_file())
            self.assertNotIn("CD_LBH", output.read_text(encoding="utf-8-sig").splitlines()[0])
            self.assertEqual({path.name for path in report.output_files},
                             {output.name, '_reports.xlsx', output.with_suffix('.summary.html').name})
            book = load_workbook(output.parent / '_reports.xlsx', read_only=True)
            try:
                self.assertEqual(book.sheetnames, ['_channels', '_files', '_issues', '_provenance', '_schemas'])
                self.assertEqual(list(book['_channels'].values)[1], (3, 1, 2, 1, output.name))
                self.assertEqual(list(book['_files'].values)[1][0], str(broken))
                self.assertEqual(list(book['_issues'].values)[1][2], 'FILE')
                self.assertEqual(list(book['_provenance'].values)[1:],
                                 [(output.name, 2, str(source), 2), (output.name, 3, str(source), 5)])
                self.assertEqual(list(book['_schemas'].values)[1][2],
                                 'WaferID | LotID | SiteName | DateTime | ToolName | MARS_Library_Name | CD | LBH')
            finally:
                book.close()
            text = output.with_suffix('.summary.html').read_text(encoding='utf-8')
            self.assertIn('MARS_Library_Name', text)
            self.assertIn(output.name, text)

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
            result_csv = next(report.result.output_dir.glob('*_Results.csv'))
            self.assertTrue(result_csv.name.startswith('CDSEM1_Wafer-W01_Lot-L1_Slot-01_'))
            self.assertTrue(result_csv.parent.name.startswith('CDSEM1_20260101_'))
            text = result_csv.with_suffix('.summary.html').read_text(encoding='utf-8')
            for value in ('Device', 'Recipe_Name', '2026-01-01', 'W01'):
                self.assertIn(value, text)
            window = ReferenceSummaryWindow()
            window.document.force_close = True
            self.addCleanup(window.deleteLater)
            self.addCleanup(window.close)
            window._completed(report)
            self.assertEqual(window.summary_output_picker.count(), 1)
            self.assertEqual(window.summary_output_picker.currentData(), str(result_csv))
            pivot = next(report.result.output_dir.glob('*.xlsx'))
            self.assertEqual(window.alignment.output_picker.currentData(), str(pivot))

    def test_sectioned_vendor_html_keeps_original_instrument_fields_and_selected_kla_test(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pmish = root / 'pmish.csv'
            pmish.write_text('RcpName:,Recipe A,ToolSN:,PM01,PPID:,pp-01,WaferID:,W02,Date:,2026-10-02\n'
                             'Num,Seq,Pad name,RefDieCol,RefDieRow,Recipe,Metrology unit,AzimuthAngle,CD\n'
                             '1,1,P,0,0,Recipe A,UVSE,45,34.20\n', encoding='utf-8')
            report = run_reference_summary(ReferenceSummaryRequest('PMISH', (pmish,), root))
            output = next(path for path in report.output_files if path.suffix == '.csv')
            self.assertTrue(output.name.startswith('PMISH_Wafer-W02_PAD-P_'))
            self.assertTrue(output.parent.name.startswith('PMISH_20261002_'))
            summary = next(path for path in report.output_files if path.suffix == '.html')
            html = summary.read_text(encoding='utf-8')
            for value in ('RcpName:', 'PM01', 'ToolSN:', 'PPID:', 'pp-01'):
                self.assertIn(value, html)

            kla = root / 'kla.csv'
            kla.write_text('TOOL ID,KLA07\nSOFTWARE VERSION,12.0\nRECIPE,R1\nMACHINE TYPE,Offline\n'
                           'DATE/TIME,2026-11-21 20:00:00\n'
                           'Head,TEST ID:,A1,TEST LABEL:,First\nSite #,CD\n1,23.40\n'
                           'Head,TEST ID:,B2,TEST LABEL:,Second\nSite #,CD\n1,25.40\n', encoding='utf-8')
            report = run_reference_summary(ReferenceSummaryRequest('KLA', (kla,), root))
            self.assertEqual(report.result.channel_count, 2)
            self.assertTrue(report.result.output_dir.name.startswith('KLA_20261121_200000_'))
            for test_id, other in (('A1', 'B2'), ('B2', 'A1')):
                summary = next(path for path in report.output_files
                               if f'TestID-{test_id}' in path.name and path.suffix == '.html')
                html = summary.read_text(encoding='utf-8')
                for value in ('TOOL ID', 'KLA07', 'SOFTWARE VERSION', 'RECIPE', 'MACHINE TYPE', 'DATE/TIME'):
                    self.assertIn(value, html)
                self.assertIn(f'<td>{test_id}</td>', html)
                self.assertNotIn(f'<td>{other}</td>', html)


if __name__ == "__main__":
    unittest.main()
