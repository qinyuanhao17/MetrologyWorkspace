"""Native trendlines and WKB-like report hierarchy through the export seams."""
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pandas as pd
from openpyxl import Workbook, load_workbook
from PIL import Image

from metrology_app.analysis_export import append_report
from metrology_app.excel_export import write_fullmap
from tests import test_excel_export as fixtures

NS = {'d': 'http://schemas.openxmlformats.org/drawingml/2006/chartDrawing',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}


class ExportWkbAxesTests(unittest.TestCase):
    tearDown = fixtures.ExcelExportTests.tearDown

    def setUp(self):
        self.window = fixtures.MatchingWindow()
        self.window.set_reference_frame(pd.DataFrame({'CD Reference': [3., 5., 7., 9., 11., 13., 15., 17.]}))
        self.window.set_raw_frame(pd.DataFrame({'Wafer ID': ['W1'] * 2 + ['W2'] * 2 + ['W1'] * 2 + ['W2'] * 2,
                                              'Die Seq': ['01', '02'] * 4,
                                              'CD': ['1.000', '2.000', '3.000', '4.000', '5.000', '6.000', '7.000', '8.000']}))
        self.window.group_controls.restore({'enabled': True, 'head_names': {'0': 'Old Unknown', '1': 'New MM1'},
                                            'show_wafer_groups': ['All:0', 'All:1']},
                                           pd.DataFrame({'TestFlag': [0] * 4 + [1] * 4}))
        self.window.group_controls.apply_button.click()

    def test_native_match_uses_excel_linear_trendline_without_fit_support_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            for native in (True, False):
                book = load_workbook(self.window.export_excel(Path(folder) / f'{native}.xlsx', native=native))
                try:
                    for sheet in (s for s in book if s.title.startswith('Match ')):
                        self.assertFalse(any(c.value == 'Fit line' for row in sheet for c in row))
                        if native:
                            scatter = sheet._charts[0]
                            self.assertEqual(len(scatter.series), 1)
                            trendline = scatter.series[0].trendline
                            self.assertIsNotNone(trendline)
                            self.assertEqual(trendline.trendlineType, 'linear')
                            self.assertTrue(trendline.dispEq)
                            self.assertTrue(trendline.dispRSqr)
                            self.assertIsNone(trendline.intercept)
                finally:
                    book.close()

    def test_group_and_wafer_have_full_height_separate_footer_levels(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.window.export_excel(Path(folder) / 'footer.xlsx')
            with ZipFile(path) as archive:
                parts = [ET.fromstring(archive.read(name)) for name in archive.namelist()
                         if name.startswith('xl/drawings/identity-')]
                def sheet_part(prefix):
                    return next(root for root in parts
                                if any(s.get('textlink', '').startswith(prefix)
                                       for s in root.findall('.//d:sp', NS)))

                def captions_for(root):
                    return [
                        (anchor, ''.join(
                            t.text or ''
                            for t in anchor.findall('.//a:t', NS)))
                        for anchor in root
                        if anchor.find('d:sp[@textlink]', NS) is not None
                        and anchor.find(
                            'd:sp/d:nvSpPr/d:cNvPr', NS)
                        .get('name', '').startswith('Caption')]

                group = sheet_part("'Match Group (")
                group_names = [text for _anchor, text in captions_for(group)]
                self.assertFalse(any(name.startswith(('W1', 'W2'))
                                     for name in group_names))
                self.assertEqual(
                    group_names, ['Old Unknown', 'New MM1'])
                shape_names = [
                    anchor.find('d:sp/d:nvSpPr/d:cNvPr', NS).get('name')
                    for anchor in group
                    if anchor.find('d:sp/d:nvSpPr/d:cNvPr', NS) is not None]
                self.assertTrue(any(
                    name.startswith('Die Seq tick')
                    for name in shape_names))
                self.assertTrue(any(
                    name.startswith('Die Seq axis title')
                    for name in shape_names))
                self.assertFalse(any(
                    anchor.find('d:sp/d:nvSpPr/d:cNvPr', NS)
                    .get('name').startswith('Leader')
                    for anchor in group))

                shown = sheet_part("'Match Group show Wafer")
                captions = captions_for(shown)
                names = [text for _, text in captions]
                self.assertEqual(names.count('W1'), 2)
                self.assertEqual(names.count('W2'), 2)
                wafer_y = [float(anchor.find('d:from/d:y', NS).text)
                           for anchor, text in captions if text.startswith('W')]
                group_y = [float(anchor.find('d:from/d:y', NS).text)
                           for anchor, text in captions
                           if text in ('Old Unknown', 'New MM1')]
                self.assertTrue(group_y and min(group_y) > max(wafer_y))
                boundaries = [anchor for anchor in shown if 'boundary' in
                              anchor.find('d:sp/d:nvSpPr/d:cNvPr', NS).get('name').lower()]
                self.assertGreaterEqual(len(boundaries), 8)
                group_boundaries = [
                    anchor for anchor in boundaries
                    if anchor.find('d:sp/d:nvSpPr/d:cNvPr', NS)
                    .get('name').lower().startswith('group boundary')]
                self.assertTrue(group_boundaries)
                self.assertTrue(all(
                    float(anchor.find('d:from/d:y', NS).text) < min(wafer_y)
                    and float(anchor.find('d:to/d:y', NS).text)
                    > max(group_y)
                    for anchor in group_boundaries))
                self.assertTrue(all(float(a.find('d:to/d:y', NS).text) -
                                    float(a.find('d:from/d:y', NS).text) >= .06 for a in boundaries))

    def test_fm_three_visual_columns_share_eight_cm_row_height(self):
        contents = BytesIO()
        Image.new('RGB', (640, 320), 'white').save(contents, format='PNG')
        frame = pd.DataFrame({'Wafer ID': ['W1', 'W2'], 'Die Seq': ['01', '03'], 'CD': ['1.000', '2.000']})
        for native in (True, False):
            book = Workbook()
            sheet = book.active
            write_fullmap(sheet, frame, ['CD'], native=native, pictures=[
                ('Wafer Map', contents.getvalue(), ''), ('Radius', contents.getvalue(), '')])
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'fm.xlsx'
                book.save(path)
                exported = load_workbook(path)
                try:
                    view = exported.active
                    wafer, radius = view._images[:2]
                    trend = view._charts[0] if native else view._images[2]
                    self.assertLess(trend.anchor._from.col, wafer.anchor._from.col)
                    self.assertLess(wafer.anchor._from.col, radius.anchor._from.col)
                    self.assertEqual([x.anchor._from.row for x in (trend, wafer, radius)], [4, 4, 4])
                    for image, height in ((wafer, 8.), (radius, 8.)):
                        self.assertAlmostEqual(image.anchor.ext.cy / 360000, height, places=4)
                        self.assertLessEqual(abs(image.anchor.ext.cx - 2 * image.anchor.ext.cy), 2)
                finally:
                    exported.close()

    def test_matplotlib_footer_keeps_wafer_then_group_and_truthful_divider_styles(self):
        from metrology_app.excel_export import (_parameter_data, parameter_footer,
                                               parameter_figure, sequence_layout)
        self.window.run_analysis()
        result = self.window.result
        data = _parameter_data(result, 'CD')
        sequence = sequence_layout(data['Group label'])
        sequence['captions'] = parameter_footer(Workbook().active, 3, data,
                                                {'Group': 1, 'Wafer': 2}, 'group')
        figure = parameter_figure('CD', data, result.card('CD'), 'Preview', 'Group', panel='Trend',
                                  reference_label=self.window.match_type.currentText(), sequence=sequence)
        try:
            axis = figure.axes[0]
            self.assertEqual(
                [text.get_text() for text in axis.texts],
                ['W1', 'W2', 'W1', 'W2', 'Old Unknown', 'New MM1'])
            self.assertEqual(axis.get_xlabel(), 'Die Seq')
            dividers = [line for line in axis.lines if line.get_linestyle() == '--']
            self.assertEqual([line.get_color() for line in dividers], ['#929292', '#929292', '#000000'])
            self.assertTrue(all(line.get_zorder() < axis.lines[0].get_zorder() for line in dividers))
            figure.canvas.draw()
            renderer = figure.canvas.get_renderer()
            for text in (*axis.texts, axis.xaxis.label, axis.title):
                bounds = text.get_window_extent(renderer)
                self.assertGreaterEqual(bounds.y0, 0)
                self.assertLessEqual(bounds.y1, figure.bbox.height)
        finally:
            figure.clear()

    def test_dynamic_native_and_matplotlib_charts_are_18_cm_wide(self):
        from metrology_app.dynamic import dynamic_pivot, prepare_dynamic_frame
        raw = pd.DataFrame({'Die Seq': [1, 2] * 3, 'CD': ['1.000', '2.000', '3.000', '4.000', '5.000', '6.000']})
        report = {'kind': 'dynamic', 'frames': {'Data': raw,
                  'Pivot CD': dynamic_pivot(prepare_dynamic_frame(raw), 'CD').reset_index()},
                  'plots': [], 'pictures': [], 'suffix': ''}
        for native in (True, False):
            book = Workbook()
            book.remove(book.active)
            append_report(book, set(), report, native=native)
            panels = book.active._charts if native else book.active._images
            self.assertEqual(len(panels), 2)
            for panel in panels:
                self.assertAlmostEqual(panel.width if native else panel.width * 2.54 / 96, 18.)

    def test_first_pyqtgraph_map_is_exported_without_a_matplotlib_cache(self):
        from metrology_app.window import MainWindow
        from metrology_app.analysis_export import capture_window
        from PyQt6.QtWidgets import QApplication
        from metrology_app.array_plot import ArrayOptions, prepare_array
        child = MainWindow()
        try:
            frame = pd.DataFrame({'Wafer ID': ['W1'] * 4, 'Die Seq': [1, 2, 3, 4],
                                  'X(mm)': [-50., 0., 50., 0.], 'Y(mm)': [0., 50., 0., -50.],
                                  'CD': ['1.000', '2.000', '3.000', '4.000']})
            child.set_table(frame, 'Synthetic export QA')
            child.recognize()
            page = child.plot_page
            selection = {'wafer_column': 'Wafer ID', 'wafers': ['W1'], 'metrics': ['CD']}
            result = prepare_array(frame, selection, ArrayOptions('X(mm)', 'Y(mm)'))
            page.render_result(result)
            self.assertGreater(page.map_grid.valid_count, 0)
            self.assertFalse(page._artists, 'Test must reach the uncached pyqtgraph export path')
            report = capture_window(child)
            self.assertIn('Wafer Map', [name for name, _, _ in report['pictures']])
        finally:
            child.document.force_close = True
            child.close()
            child.deleteLater()
            QApplication.processEvents()


if __name__ == '__main__':
    unittest.main()
