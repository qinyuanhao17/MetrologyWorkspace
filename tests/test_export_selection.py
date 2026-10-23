"""Selectable report outputs keep their editable calculation dependencies."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import time
import unittest

import pandas as pd
from PIL import Image
from openpyxl import Workbook, load_workbook
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QDialogButtonBox, QFileDialog

from metrology_app.excel_export import report_sequence_layout, write_fullmap, write_workbook
from metrology_app.export_sheet_dialog import ExportSheetDialog
from metrology_app.export_sheets import export_sheet_names, select_export_sheets
from tests import test_excel_export as fixtures


class ExportSelectionTests(unittest.TestCase):
    tearDown = fixtures.ExcelExportTests.tearDown

    def setUp(self):
        self.window = fixtures.MatchingWindow()
        self.window.set_reference_frame(pd.DataFrame({'CD Reference': [3., 5., 7., 9.]}))
        self.window.set_raw_frame(pd.DataFrame({'Wafer ID': ['W1', 'W1', 'W2', 'W2'],
                                               'Die Seq': ['001', '002'] * 2, 'CD': ['1.000', '2.000', '3.000', '4.000']}))
        self.window.group_controls.restore({'enabled': True, 'head_names': {'0': 'POR', '1': 'New'}},
                                           pd.DataFrame({'TestFlag': [0, 0, 1, 1]}))
        self.window.group_controls.apply_button.click()
        self.window.run_analysis()

    def test_manifest_matches_actual_visible_outputs_with_group_names_and_suffixes(self):
        snapshot = self.window.excel_export_snapshot()
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'manifest.xlsx'
            write_workbook(path, **snapshot)
            book = load_workbook(path)
            try:
                self.assertEqual(export_sheet_names(snapshot, matching=True),
                                 [sheet.title for sheet in book if sheet.sheet_state == 'visible'])
            finally:
                book.close()

    def test_select_all_ungrouped_sheets_accepts_original_without_footer_captions(self):
        self.window.group_controls.enabled.setChecked(False)
        self.window.group_controls.apply_button.click()
        snapshot = self.window.excel_export_snapshot()
        names = export_sheet_names(snapshot, matching=True)
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'all.xlsx'
            write_workbook(path, **snapshot, selected_sheets=names)
            book = load_workbook(path)
            try:
                self.assertEqual([sheet.title for sheet in book if sheet.sheet_state == 'visible'], names)
                self.assertEqual(len(book['Match Original (WO Card)']._charts), 3)
            finally:
                book.close()

    def test_selected_wafer_keeps_required_original_and_card_sources_hidden(self):
        snapshot = self.window.excel_export_snapshot()
        for native in (True, False):
            with self.subTest(native=native), TemporaryDirectory() as folder:
                path = Path(folder) / 'selected.xlsx'
                write_workbook(path, **snapshot, native=native, selected_sheets=['Match Wafer (WO Card)'])
                book = load_workbook(path)
                try:
                    self.assertEqual([sheet.title for sheet in book if sheet.sheet_state == 'visible'], ['Match Wafer (WO Card)'])
                    self.assertEqual(book.active.title, 'Match Wafer (WO Card)')
                    self.assertEqual(set(book.sheetnames), {'Match Wafer (WO Card)', 'Match Original (WO Card)', '_Plot data'})
                    original = book['Match Original (WO Card)']
                    self.assertEqual(original.sheet_state, 'hidden')
                    self.assertEqual((len(original._charts), len(original._images)), (0, 0))
                    self.assertEqual(fixtures.source_cell(original, 'CD', 2).value, '1.000')
                    self.assertIn("'Match Original (WO Card)'!", book['Match Wafer (WO Card)']['D3'].value)
                    self.assertEqual(len(book.active._charts if native else book.active._images), 3)
                finally:
                    book.close()

    def test_rsq_only_has_no_unnecessary_hidden_outputs(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'rsq.xlsx'
            write_workbook(path, **self.window.excel_export_snapshot(), selected_sheets=['RSQ (WO Card)'])
            book = load_workbook(path)
            try:
                self.assertEqual(book.sheetnames, ['RSQ (WO Card)'])
            finally:
                book.close()

    def test_invalid_or_empty_selection_never_replaces_previous_file(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'existing.xlsx'
            path.write_bytes(b'previous export')
            snapshot = self.window.excel_export_snapshot()
            for choice in ([], ['Unknown sheet']):
                with self.assertRaisesRegex(ValueError, 'at least one available'):
                    write_workbook(path, **snapshot, selected_sheets=choice)
                self.assertEqual(path.read_bytes(), b'previous export')

    def test_cancel_sheet_choice_preserves_existing_target_and_starts_no_writer(self):
        for action in (self.window.export_action, self.window.images_action):
            with TemporaryDirectory() as folder:
                path = Path(folder) / 'existing.xlsx'
                path.write_bytes(b'previous export')
                with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(path), '')), \
                        patch('metrology_app.export_job.choose_export_sheets', return_value=None) as choose, \
                        patch('metrology_app.export_job.ExportJob.start') as start:
                    action.trigger()
                    deadline = time.monotonic() + 5
                    while self.window._excel_export_job is not None and time.monotonic() < deadline:
                        QTest.qWait(10)
                    self.assertIsNone(self.window._excel_export_job)
                    self.assertIn('Match Wafer (WO Card)', choose.call_args.args[1])
                    start.assert_not_called()
                self.assertEqual(path.read_bytes(), b'previous export')
                self.assertTrue(action.isEnabled())

    def test_owner_close_rejects_sheet_choice_without_waiting_or_writing(self):
        from metrology_app.export_sheet_dialog import choose_export_sheets
        fallback = QTimer()
        fallback.setSingleShot(True)
        timed_out = []
        def release_stuck_dialog():
            timed_out.append(True)
            for dialog in self.window.findChildren(ExportSheetDialog):
                dialog.reject()
        fallback.timeout.connect(release_stuck_dialog)
        def choose(owner, names):
            QTimer.singleShot(0, owner.close)
            fallback.start(1000)
            return choose_export_sheets(owner, names)
        self.window.document.force_close = True
        with TemporaryDirectory() as folder, \
                patch.object(QFileDialog, 'getSaveFileName', return_value=(str(Path(folder) / 'closed.xlsx'), '')), \
                patch('metrology_app.export_job.choose_export_sheets', side_effect=choose), \
                patch('metrology_app.export_job.ExportJob.start') as start:
            try:
                self.window.export_action.trigger()
                deadline = time.monotonic() + 5
                while self.window._excel_export_job is not None and time.monotonic() < deadline:
                    QTest.qWait(10)
                self.assertEqual(timed_out, [])
                self.assertIsNone(self.window._excel_export_job)
                start.assert_not_called()
            finally:
                fallback.stop()


class ExportLayoutChoiceTests(unittest.TestCase):
    def test_footer_text_is_painted_after_all_structural_lines(self):
        from xml.etree import ElementTree as ET
        from metrology_app.native_chart_labels import _drawing
        ns = {'d': 'http://schemas.openxmlformats.org/drawingml/2006/chartDrawing'}
        labels = [dict(text='Wafer with a long name', source="'Sheet'!A1", start=0, end=1,
                       center=.5, level=0, role='wafer', show=True),
                  dict(text='Group', source="'Sheet'!B1", start=0, end=1,
                       center=.5, level=1, role='group', show=True)]
        root = ET.fromstring(_drawing(labels))
        text = [i for i, anchor in enumerate(root) if anchor.find('d:sp/d:txBody', ns) is not None]
        lines = [i for i, anchor in enumerate(root) if anchor.find('d:sp/d:txBody', ns) is None]
        self.assertGreater(min(text), max(lines))

    def test_sheet_checkboxes_default_all_and_prevent_empty_acceptance(self):
        dialog = ExportSheetDialog(['Original', 'Wafer', 'FM'])
        try:
            self.assertEqual(dialog.selected_sheets(), ['Original', 'Wafer', 'FM'])
            dialog.set_all(Qt.CheckState.Unchecked)
            self.assertFalse(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled())
            dialog.sheets.item(1).setCheckState(Qt.CheckState.Checked)
            self.assertEqual(dialog.selected_sheets(), ['Wafer'])
            self.assertTrue(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled())
        finally:
            dialog.deleteLater()
            fixtures.APP.processEvents()

    def test_long_or_close_labels_expand_width_without_padding_or_dropping_points(self):
        dies = ['001'] * 100
        captions = [dict(text='Long neighboring Group A', center=.90, level=0, show=True),
                    dict(text='Long neighboring Group B', center=.95, level=0, show=True)]
        ordinary = report_sequence_layout(dies)
        wide = report_sequence_layout(dies, captions)
        self.assertGreater(wide['width'], ordinary['width'])
        self.assertEqual(wide['limits'], (.5, 100.5))
        self.assertEqual(len(wide['x']), 100)

    def test_whole_grid_map_scales_to_eight_cm_per_row_without_changing_png_bytes(self):
        buffer = BytesIO()
        Image.new('RGB', (1200, 800), 'white').save(buffer, format='PNG')
        contents = buffer.getvalue()
        frame = pd.DataFrame({'Wafer ID': ['W1'], 'Die Seq': ['001'], 'CD': ['1.000']})
        for native in (True, False):
            book = Workbook()
            write_fullmap(book.active, frame, ['CD'], native=native,
                          pictures=[('Wafer Map', contents, '')], picture_shapes={'Wafer Map': (2, 3)})
            with TemporaryDirectory() as folder:
                path = Path(folder) / 'map.xlsx'
                book.save(path)
                saved = load_workbook(path)
                try:
                    image = saved.active._images[0]
                    self.assertAlmostEqual(image.anchor.ext.cy / 360000 / 2, 8., places=4)
                    self.assertLessEqual(abs(image.anchor.ext.cx - 1.5 * image.anchor.ext.cy), 2)
                    self.assertEqual(image._data(), contents)
                finally:
                    saved.close()

    def test_dependency_names_with_apostrophes_and_unused_sheets_are_safe(self):
        book = Workbook()
        selected = book.active
        selected.title = 'Selected'
        source = book.create_sheet("Source's data")
        source['A1'] = '1.000'
        selected['A1'] = "='Source''s data'!A1*1"
        book.create_sheet('Unused')
        select_export_sheets(book, ['Selected'])
        self.assertEqual(book.sheetnames, ['Selected', "Source's data"])
        self.assertEqual(source.sheet_state, 'hidden')
