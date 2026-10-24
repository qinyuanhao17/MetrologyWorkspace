"""Export opening view, observable preparation and application preferences."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import time
import unittest

import pandas as pd
from openpyxl import Workbook, load_workbook
from PIL import Image
from PyQt6.QtCore import QThread
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog

from metrology_app import export_job
from metrology_app.excel_export import style_workbook, write_fullmap
from metrology_app.match_groups import group_state
from metrology_app.settings import recent_wkb_paths, remember_recent_wkb
from tests import test_excel_export as fixtures

APP, MatchingWindow = fixtures.APP, fixtures.MatchingWindow


class ExportOpeningLayoutTests(unittest.TestCase):
    tearDown = fixtures.ExcelExportTests.tearDown

    def setUp(self):
        self.window = MatchingWindow()
        self.window.set_reference_frame(pd.DataFrame({'CD Reference': [3., 5., 7.]}))
        self.window.set_raw_frame(pd.DataFrame({'Wafer ID': ['W1'] * 3,
                                               'Die Seq': ['01', '02', '03'], 'CD': ['1.000', '2.000', '3.000']}))
        self.window.run_analysis()

    def wait_finished(self):
        deadline = time.monotonic() + 5
        while getattr(self.window, '_excel_export_job', None) is not None and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertIsNone(getattr(self.window, '_excel_export_job', None))

    def test_both_export_menus_paint_progress_before_gui_snapshot_preparation(self):
        for action in (self.window.export_action, self.window.images_action):
            with self.subTest(action=action.text()), TemporaryDirectory() as folder:
                painted, observed = [], []
                class PaintedProgress(QProgressDialog):
                    def paintEvent(self, event):
                        painted.append(time.perf_counter())
                        super().paintEvent(event)
                def prepare():
                    dialogs = self.window.findChildren(QProgressDialog)
                    observed.append((any(d.isVisible() for d in dialogs), bool(painted),
                                     QThread.currentThread() == APP.thread()))
                    raise ValueError('Owned preparation failure')
                target = Path(folder) / 'existing.xlsx'
                target.write_bytes(b'preserve previous export')
                with patch.object(export_job, 'QProgressDialog', PaintedProgress), \
                        patch.object(self.window, 'excel_export_snapshot', side_effect=prepare), \
                        patch.object(QFileDialog, 'getSaveFileName', return_value=(str(target), '')), \
                        patch.object(QMessageBox, 'warning') as warning:
                    action.trigger()
                    self.wait_finished()
                    self.assertEqual(observed, [(True, True, True)])
                    self.assertIn('Owned preparation failure', warning.call_args.args[2])
                self.assertTrue(self.window.export_action.isEnabled())
                self.assertTrue(self.window.images_action.isEnabled())
                self.assertEqual(target.read_bytes(), b'preserve previous export')

    def test_cancel_before_preparation_does_not_capture_or_replace_target(self):
        with TemporaryDirectory() as folder:
            target = Path(folder) / 'existing.xlsx'
            target.write_bytes(b'keep')
            with patch.object(self.window, 'excel_export_snapshot') as prepare:
                export_job.start_export(self.window, target, prepare, matching=True)
                self.window.findChild(QProgressDialog).cancel()
                self.wait_finished()
                prepare.assert_not_called()
            self.assertEqual(target.read_bytes(), b'keep')
            self.assertTrue(self.window.export_action.isEnabled())

    def test_all_match_sheets_open_with_tables_at_a1_and_plots_at_row_five(self):
        with TemporaryDirectory() as folder:
            for native in (True, False):
                book = load_workbook(self.window.export_excel(Path(folder) / f'{native}.xlsx', native=native))
                try:
                    for sheet in (s for s in book if s.title.startswith('Match ')):
                        self.assertEqual(sheet['A1'].value, 'CD')
                        panels = sheet._charts if native else sheet._images
                        column, row = fixtures.drawing_cell(panels[0], sheet)
                        self.assertEqual(row, 4)
                        self.assertEqual(column, 0)
                        self.assertEqual(sheet.freeze_panes, 'A3')
                finally:
                    book.close()

    def test_standalone_export_also_shows_progress_before_capture(self):
        child = fixtures.MainWindow()
        try:
            observed = []
            def prepare(_window):
                observed.append(any(d.isVisible() for d in child.findChildren(QProgressDialog)))
                raise ValueError('Owned standalone preparation failure')
            with TemporaryDirectory() as folder, \
                    patch('metrology_app.analysis_export.capture_window', side_effect=prepare), \
                    patch.object(QFileDialog, 'getSaveFileName', return_value=(str(Path(folder) / 'standalone.xlsx'), '')):
                child.export_excel_dialog()
                deadline = time.monotonic() + 5
                while getattr(child, '_excel_export_job', None) is not None and time.monotonic() < deadline:
                    QTest.qWait(10)
                self.assertEqual(observed, [True])
                self.assertIsNone(child._excel_export_job)
                self.assertTrue(child.export_excel_action.isEnabled())
        finally:
            child.document.force_close = True
            child.close()
            child.deleteLater()
            APP.processEvents()

    def test_close_before_preparation_cancels_without_starting_a_writer(self):
        with TemporaryDirectory() as folder, patch.object(self.window, 'excel_export_snapshot') as prepare:
            target = Path(folder) / 'closing.xlsx'
            export_job.start_export(self.window, target, prepare, matching=True)
            self.window.document.force_close = True
            self.window.close()
            self.wait_finished()
            prepare.assert_not_called()
            self.assertFalse(target.exists())

    def test_recent_menu_fallback_keeps_twenty_without_writing_settings(self):
        paths = [Path(f'case-{i}.wkb').resolve() for i in range(24)]
        self.window._recent_wkb_paths = paths[1:]
        with patch('metrology_app.matching_window.remember_recent_wkb', side_effect=OSError('owned failure')):
            self.window._remember_recent_wkb(paths[0])
        self.assertEqual(self.window._recent_wkb_paths, paths[:20])
        self.assertEqual(len(self.window.open_recent_menu.actions()), 20)

    def test_dense_original_remains_a_complete_scatter_and_two_point_line_panels(self):
        count = 600
        self.window.set_reference_frame(pd.DataFrame({'CD Reference': [2 * i + 1 for i in range(count)]}))
        self.window.set_raw_frame(pd.DataFrame({'Wafer ID': ['W1'] * count,
                                               'Die Seq': range(count), 'CD': range(count)}))
        self.window.run_analysis()
        with TemporaryDirectory() as folder:
            book = load_workbook(self.window.export_excel(Path(folder) / 'dense.xlsx'))
            try:
                match, trend, bias = book['Match Original (WO Card)']._charts
                self.assertEqual(match.scatterStyle, 'marker')
                self.assertTrue(match.series[0].graphicalProperties.line.noFill)
                self.assertEqual(match.series[0].marker.size, 5)
                self.assertTrue(match.series[0].yVal.numRef.f.endswith('$E$3:$E$602'))
                label = match.series[0].trendline.trendlineLbl
                self.assertEqual(label.txPr.p[0].pPr.algn, 'ctr')
                layout = label.layout.manualLayout
                self.assertAlmostEqual(layout.x + layout.w / 2, .5)
                self.assertEqual(match.title.tx.rich.p[0].pPr.algn, 'ctr')
                for panel in (trend, bias):
                    self.assertTrue(panel.marker)
                    self.assertEqual(panel.x_axis.tickMarkSkip, panel.x_axis.tickLblSkip)
                    for series in panel.series:
                        self.assertEqual(series.marker.symbol, 'circle')
                        self.assertEqual(series.marker.size, 6)
                        self.assertEqual(series.graphicalProperties.line.w, 31750)
                        self.assertFalse(series.graphicalProperties.line.noFill)
            finally:
                book.close()


class ReportAndPreferenceTests(unittest.TestCase):
    def test_dense_fm_keeps_standard_width_and_all_source_rows(self):
        count = 100
        book = Workbook()
        sheet = book.active
        frame = pd.DataFrame({'Wafer ID': [f'WAFER-{i:03d}' for i in range(count)],
                              'Die Seq': ['001'] * count, 'CD': ['1.000'] * count})
        write_fullmap(sheet, frame, ['CD'])
        self.assertAlmostEqual(sheet._charts[0].width, 25.)
        self.assertEqual(sheet.max_row, count + 1)
        self.assertEqual(len(sheet._charts[0].series[0].cat.strRef.strCache.pt), count)
        from xml.etree import ElementTree as ET
        from metrology_app.native_chart_labels import _drawing
        root = ET.fromstring(_drawing(sheet._charts[0]._identity_captions))
        names = [node.get('name') for node in root.iter() if node.tag.endswith('}cNvPr')]
        self.assertEqual(sum('plot divider' in name for name in names), count - 1)
        self.assertLessEqual(sum('boundary' in name for name in names), 8)

    def test_nova_fm_still_has_prepared_data_at_a1_without_extra_trends(self):
        book = Workbook()
        sheet = book.active
        frame = pd.DataFrame({'Wafer ID': ['W1'], 'Die Seq': ['001'], 'CD': ['1.000']})
        write_fullmap(sheet, frame, ['CD'], include_trends=False)
        self.assertEqual([sheet.cell(1, i).value for i in range(1, 4)], ['Wafer', 'Die Seq', 'CD'])
        self.assertEqual(sheet['G2'].value, '1.000')
        self.assertEqual(sheet['C2'].data_type, 'f')
        self.assertEqual(sheet._charts, [])

    def test_two_level_footer_uses_unique_shape_ids_even_for_crowded_neighbors(self):
        from xml.etree import ElementTree as ET
        from metrology_app.native_chart_labels import _drawing
        labels = [dict(text=f'W{index}', source=f"'Sheet'!A{index + 1}", start=index / 8,
                       end=(index + 1) / 8, center=(index + .5) / 8, role='wafer', level=0)
                  for index in range(8)]
        labels += [dict(text='POR', source="'Sheet'!B1", start=0, end=1,
                        center=.5, role='group', level=1)]
        root = ET.fromstring(_drawing(labels))
        ids = [node.get('id') for node in root.iter() if node.tag.endswith('}cNvPr')]
        self.assertEqual(len(ids), len(set(ids)))

    def test_recent_settings_keep_twenty_unique_paths_newest_first(self):
        with TemporaryDirectory() as folder:
            settings = Path(folder) / 'settings.yaml'
            paths = [Path(folder) / f'case-{i}.wkb' for i in range(23)]
            for path in paths:
                remember_recent_wkb(path, settings_path=settings)
            self.assertEqual(recent_wkb_paths(settings_path=settings), tuple(reversed(paths[-20:])))
            remember_recent_wkb(paths[-2], settings_path=settings)
            self.assertEqual(recent_wkb_paths(settings_path=settings)[0], paths[-2])
            self.assertEqual(len(recent_wkb_paths(settings_path=settings)), 20)

    def test_grouped_legacy_wafer_order_migrates_draft_and_applied_separately(self):
        for head, mark in ((True, False), (False, True), (True, True)):
            state = group_state({'enabled': head, 'mark_enabled': mark, 'trend_order': 'wafers',
                                 'applied': {'enabled': True, 'trend_order': 'wafers'}})
            self.assertEqual(state['trend_order'], 'groups')
            self.assertEqual(state['applied']['trend_order'], 'groups')
        self.assertEqual(group_state({'trend_order': 'wafers'})['trend_order'], 'wafers')

    def test_fm_report_starts_a1_and_three_plot_columns_overlay_from_row_five(self):
        buffer = BytesIO()
        Image.new('RGB', (640, 320), 'white').save(buffer, format='PNG')
        frame = pd.DataFrame({'Wafer ID': ['W1'] * 40, 'Die Seq': [str(i) for i in range(40)],
                              'CD': ['1.000'] * 40})
        for native in (True, False):
            book = Workbook()
            sheet = book.active
            write_fullmap(sheet, frame, ['CD'], native=native, pictures=[
                ('Wafer Map', buffer.getvalue(), ''), ('Radius', buffer.getvalue(), '')])
            style_workbook(book)
            self.assertEqual([sheet.cell(1, i).value for i in range(1, 4)], ['Wafer', 'Die Seq', 'CD'])
            self.assertEqual(sheet.cell(1, sheet._source_start_column).value, 'Wafer ID')
            with TemporaryDirectory() as folder:
                path = Path(folder) / 'fm.xlsx'
                book.save(path)
                saved = load_workbook(path)
                try:
                    view = saved.active
                    panels = [view._charts[0], *view._images] if native else [view._images[-1], *view._images[:2]]
                    self.assertEqual([p.anchor._from.row for p in panels], [4, 4, 4])
                    self.assertEqual(panels[0].anchor._from.col, 0)
                    self.assertLess(panels[0].anchor._from.col, panels[1].anchor._from.col)
                    self.assertLess(panels[1].anchor._from.col, panels[2].anchor._from.col)
                    self.assertEqual(view.cell(2, 3).value, '=IFERROR(IF(G2="",NA(),G2*1),NA())')
                    self.assertEqual(view['G2'].value, '1.000')
                    if native:
                        axis = panels[0].x_axis
                        self.assertGreater(axis.tickLblSkip, 1)
                        self.assertEqual(axis.tickMarkSkip, axis.tickLblSkip)
                finally:
                    saved.close()
