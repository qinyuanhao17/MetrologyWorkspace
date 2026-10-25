"""Horizontal Match tables and left-hand FM pictures through real exporters."""
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pandas as pd
from PIL import Image as PillowImage
from openpyxl import Workbook, load_workbook
from PyQt6.QtWidgets import QApplication

from metrology_app.excel_export import write_fullmap
from metrology_app.matching_window import MatchingWindow
from tests import test_excel_export as fixtures

APP = QApplication.instance() or QApplication([])


class TemplateLayoutTests(unittest.TestCase):
    def test_group_and_wafer_match_sheets_follow_the_same_horizontal_template(self):
        window = MatchingWindow()
        try:
            window.set_reference_frame(pd.DataFrame({'DP Reference': [3., 5., 7.], 'EW Reference': [9., 11., 13.]}))
            window.set_raw_frame(pd.DataFrame({'Wafer ID': ['W1'] * 3, 'Die Seq': ['1', '2', '3'],
                                               'DP': ['1.000', '2.000', '3.000'], 'EW': ['4.000', '5.000', '6.000']}))
            window.group_controls.restore({'enabled': True, 'head_names': {'0': 'A', '1': 'B'}},
                                          pd.DataFrame({'TestFlag': [0, 0, 1]}))
            window.group_controls.apply_button.click()
            with tempfile.TemporaryDirectory() as folder:
                for native in (True, False):
                    book = load_workbook(window.export_excel(Path(folder) / f'groups-{native}.xlsx', native=native))
                    for sheet in (s for s in book if s.title.startswith('Match ')):
                        self.assertEqual(sheet['A1'].value, 'DP', sheet.title)
                        self.assertEqual(sheet['J1'].value, 'EW', sheet.title)
                        self.assertEqual(sheet['A2'].value, 'Group', sheet.title)
                        self.assertEqual(sheet['J2'].value, 'Group', sheet.title)
                        objects = sheet._charts if native else sheet._images
                        self.assertEqual(len(objects), 6)
                        cells = [fixtures.drawing_cell(obj, sheet) for obj in objects]
                        self.assertEqual(cells[0][0], 0)
                        self.assertGreater(cells[3][1], cells[0][1])
                        self.assertEqual(cells[0][1], 4)
                    book.close()
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_legacy_saved_map_selection_rebuilds_both_pngs_without_empty_ui_overrides(self):
        from PyQt6.QtCore import Qt
        from metrology_app.window import MainWindow
        from metrology_app.analysis_export import capture_saved_window
        from metrology_app.matching import MatchWorkbook, ParameterMapping
        source = pd.DataFrame({'Wafer ID': ['W1'] * 4, 'Die Seq': ['1', '2', '3', '4'],
                               'FIELD X': ['-1', '1', '0', '0'], 'FIELD Y': ['0', '0', '-1', '1'],
                               'DP': ['10.000', '11.000', '12.000', '13.000']})
        window = MainWindow()
        try:
            window.set_table(source, 'Map')
            key = window.selection_state()['wafers'][0]
            selection = {'wafers': [key], 'metrics': ['DP'],
                         'map_draw': {'enabled': True, 'cells': [(key, 'DP')]},
                         'radius_draw': {'enabled': True, 'cells': [(key, 'DP')]}}
            book = MatchWorkbook(pd.DataFrame({'DP Reference': [21, 23, 25, 27]}), source,
                                 [ParameterMapping('DP', 'DP Reference', 'DP')])
            report = capture_saved_window('map', source, scope='map.preview', saved={},
                                          selection=selection, workbook=book, parameters=['DP'])
            self.assertEqual([p[0] for p in report['pictures']], ['Wafer Map', 'Radius'])
            pd.testing.assert_frame_equal(report['frames']['Data'], source)
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_saved_closed_dynamic_is_exported_without_opening_or_accepting_windows(self):
        from PyQt6.QtCore import Qt
        window = MatchingWindow()
        try:
            window.set_reference_frame(pd.DataFrame({'DP Reference': [3., 5., 7.]}))
            window.set_raw_frame(pd.DataFrame({'Wafer ID': ['W1'] * 3, 'Die Seq': [1, 2, 3], 'DP': [1., 2., 3.]}))
            window.run_analysis()
            child = window.open_dynamic_workspace('preview')
            child.set_table(pd.DataFrame({'Wafer ID': ['D1'] * 4, 'Die Seq': [1, 2, 1, 2],
                                          'DP': ['10.000', '20.000', '11.000', '21.000']}), 'Independent Dynamic')
            for index in range(child.parameter_list.topLevelItemCount()):
                item = child.parameter_list.topLevelItem(index)
                if item.text(0) == 'DP':
                    item.setCheckState(0, Qt.CheckState.Checked)
            with tempfile.TemporaryDirectory() as folder:
                saved = window.save_workbook(Path(folder) / 'source.mwkb')
                window.load_workbook(saved)
                self.assertEqual(window._stage_windows, [])
                before = window.workspace_snapshot()
                report = window.excel_export_snapshot()
                dynamics = [r for _, r in report['reports'] if r['kind'] == 'dynamic']
                self.assertEqual(len(dynamics), 1)
                self.assertIn('Pivot DP', dynamics[0]['frames'])
                self.assertEqual(dynamics[0]['frames']['Data']['DP'].iloc[0], '10.000')
                self.assertEqual(window._stage_windows, [])
                after = window.workspace_snapshot()
                self.assertEqual(before.states, after.states)
                for key in before.frames:
                    pd.testing.assert_frame_equal(before.frames[key], after.frames[key])
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_all_parameter_tables_are_horizontal_sources_right_and_charts_below(self):
        window = MatchingWindow()
        try:
            raw = pd.DataFrame({'Wafer ID': ['W1'] * 3, 'Die Seq': ['001', '003', '005'],
                                'DP': ['1.000', '2.000', '3.000'], 'EW': ['4.000', '5.000', '6.000']})
            window.set_reference_frame(pd.DataFrame({'DP Reference': [3., 5., 7.], 'EW Reference': [9., 11., 13.]}))
            window.set_raw_frame(raw)
            window.run_analysis()
            before = window.workspace_snapshot()
            with tempfile.TemporaryDirectory() as folder:
                for native in (True, False):
                    book = load_workbook(window.export_excel(Path(folder) / f'{native}.xlsx', native=native))
                    sheet = book['Match Original (WO Card)']
                    self.assertEqual(sheet['A1'].value, 'DP')
                    self.assertEqual(sheet['I1'].value, 'EW')
                    self.assertEqual(sheet['A2'].value, 'Wafer')
                    self.assertEqual(sheet['I2'].value, 'Wafer')
                    source = next(c.column for c in sheet[1] if c.value == 'Wafer ID')
                    self.assertGreater(source, 16)
                    self.assertEqual([sheet.cell(r, source + 2).value for r in range(2, 5)], raw['DP'].tolist())
                    self.assertIn(f'${sheet.cell(1, source + 2).column_letter}$2', sheet['C3'].value)
                    objects = sheet._charts if native else sheet._images
                    self.assertEqual(len(objects), 6)
                    cells = [fixtures.drawing_cell(obj, sheet) for obj in objects]
                    self.assertEqual(cells[0][1], 4)
                    self.assertEqual(cells[0][0], 0)
                    self.assertGreater(cells[3][1], cells[0][1])
                    self.assertEqual(sheet.freeze_panes, 'A3')
                    for view in (s for s in book if s.title.startswith('Match ')):
                        self.assertEqual(view['A1'].value, 'DP')
                        self.assertEqual(view['I1'].value, 'EW')
                        self.assertEqual(view['A2'].value, 'Wafer')
                        self.assertEqual(view['I2'].value, 'Wafer')
                        panels = view._charts if native else view._images
                        self.assertEqual(fixtures.drawing_cell(panels[0], view)[1], 4)
                    if native:
                        self.assertIn('$K$3:$K$5', objects[3].series[0].xVal.numRef.f)
                        self.assertIn('$M$3:$M$5', objects[3].series[0].yVal.numRef.f)
                    book.close()
            after = window.workspace_snapshot()
            self.assertEqual(before.states, after.states)
            for key in before.frames:
                pd.testing.assert_frame_equal(before.frames[key], after.frames[key])
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_fullmap_overlays_software_pngs_and_trends_on_editable_data_in_both_modes(self):
        frame = pd.DataFrame({'Wafer ID': ['W1', 'W1'], 'Die Seq': ['001', '002'], 'DP': ['1.000', '2.000']})
        buffer = BytesIO()
        PillowImage.new('RGB', (400, 250), 'white').save(buffer, format='PNG')
        contents = buffer.getvalue()
        for native in (True, False):
            book = Workbook()
            sheet = book.active
            write_fullmap(sheet, frame, ['DP'], native=native,
                          pictures=[('Wafer Map DP', contents, ''), ('Radius DP', contents, '')],
                          picture_shapes={'Wafer Map DP': (2, 3), 'Radius DP': (1, 3)})
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'map.xlsx'
                book.save(path)
                exported = load_workbook(path)
                view = exported.active
                source = next(c.column for c in view[1] if c.value == 'Wafer ID')
                self.assertEqual(view['A1'].value, 'Wafer')
                self.assertTrue(all(i.anchor._from.row == 4 for i in [*view._charts, *view._images]))
                self.assertEqual(view.cell(2, source + 2).value, '1.000')
                self.assertEqual(len(view._images), 2 if native else 3)
                wafer_map, radius = view._images[:2]
                self.assertEqual(wafer_map.anchor.ext.cy, radius.anchor.ext.cy)
                for image in view._images[:2]:
                    self.assertLessEqual(image.anchor.ext.cy / 360000, 30)
                    self.assertLessEqual(image.anchor.ext.cx / 360000, 72)
                if native:
                    formula = next(c.value for row in view for c in row if c.data_type == 'f')
                    self.assertIn(f'{view.cell(1, source + 2).column_letter}2', formula)
                exported.close()


if __name__ == '__main__':
    unittest.main()
