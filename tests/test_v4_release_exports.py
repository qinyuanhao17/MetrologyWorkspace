"""Acceptance checks for docs/todos/Todolist/20261019 Todo List.md."""
from io import BytesIO
from pathlib import Path
import tempfile
import unittest

import pandas as pd
from openpyxl import Workbook, load_workbook
from PIL import Image

from tests import test_excel_export as fixtures
from metrology_app.excel_export import write_fullmap
from metrology_app.analysis_export import append_report


class ReleaseExportTests(unittest.TestCase):
    tearDown = fixtures.ExcelExportTests.tearDown

    def setUp(self):
        from metrology_app.matching_window import MatchingWindow
        self.window = MatchingWindow()
        self.window.match_type.setCurrentText('NOVA')
        self.raw = pd.DataFrame({'Wafer ID': ['W2', 'W1'] * 3,
            'Die Seq': ['10', '10', '17', '17', '23', '23'],
            'CD': ['1.000', '8.000', '2.000', '9.000', '3.000', '10.000']})
        self.window.set_reference_frame(pd.DataFrame({'CD Reference': [3, 17, 5.2, 19, 7, 21.3]}))
        self.window.set_raw_frame(self.raw)
        self.window.set_preview_frame(self.raw.copy())
        self.window.group_controls.restore({'enabled': True,
            'head_names': {'0': 'Old MM1', '1': 'New MM2'}},
            pd.DataFrame({'TestFlag': [0, 1, 0, 1, 0, 1]}))
        self.window.group_controls.apply_button.click()

    def test_match_views_and_group_names_without_redundant_sheets(self):
        with tempfile.TemporaryDirectory() as folder:
            for native in (True, False):
                with self.subTest(native=native):
                    book = load_workbook(self.window.export_excel(Path(folder) / f'{native}.xlsx', native=native))
                    for name in ('Match Original', 'Match Group', 'Match Wafer', 'Match Old MM1', 'Match New MM2'):
                        self.assertIn(name + ' (WO Card)', book.sheetnames)
                    for name in ('Original', 'Match', 'All Trend', 'Group Fits', 'Order'):
                        self.assertNotIn(name + ' (WO Card)', book.sheetnames)
                    original = book['Match Original (WO Card)']
                    self.assertEqual([fixtures.source_cell(original, 'CD', row).value for row in range(2, 8)], self.raw['CD'].tolist())
                    self.assertFalse(book['FullMap (WO Card)']._charts)
                    self.assertFalse(book['FullMap (WO Card)']._images)

    def test_native_die_group_and_wafer_axes_and_symmetric_bias(self):
        with tempfile.TemporaryDirectory() as folder:
            book = load_workbook(self.window.export_excel(Path(folder) / 'axes.xlsx'))
            original = book['Match Original (WO Card)']
            group = book['Match Group (WO Card)']
            wafer = book['Match Wafer (WO Card)']
            self.assertEqual(len(original._charts), 3)
            self.assertEqual(len(group._charts), 3)
            self.assertEqual(len(wafer._charts), 3)
            original_cat = original._charts[1].series[0].cat
            self.assertIsNone(original_cat.multiLvlStrRef)
            self.assertIsNotNone(original_cat.strRef)
            group_axis = group._charts[1]
            for sheet in (group, wafer):
                for chart in sheet._charts[1:]:
                    self.assertEqual(chart.y_axis.crossBetween, 'between')
                    for series in chart.series:
                        categories = series.cat.strRef
                        self.assertEqual(categories.f, f"'{sheet.title}'!$C$3:$C$8")
                        self.assertEqual([point.v for point in categories.strCache.pt],
                                         ['10', '17', '23'] * 2)
                        self.assertTrue(series.val.numRef.f.startswith(f"'{sheet.title}'!"))
            # openpyxl round-trips the valid OOXML "none" as None.
            self.assertIsNone(group_axis.x_axis.tickLblPos)
            self.assertEqual(
                group_axis.x_axis.txPr.p[0].pPr.defRPr
                .solidFill.srgbClr,
                "FFFFFF")
            from zipfile import ZipFile
            from xml.etree import ElementTree as ET
            with ZipFile(Path(folder) / 'axes.xlsx') as archive:
                hidden_numeric_axes = 0
                for name in archive.namelist():
                    if not (name.startswith('xl/charts/chart')
                            and name.endswith('.xml')):
                        continue
                    tree = ET.fromstring(archive.read(name))
                    ns = {
                        'c': 'http://schemas.openxmlformats.org/'
                             'drawingml/2006/chart'}
                    numeric_axis = (
                        tree.find('.//c:valAx', ns)
                        if tree.find('.//c:scatterChart', ns) is not None
                        else tree.find('.//c:catAx', ns))
                    if (numeric_axis is not None
                            and numeric_axis.find('c:delete', ns) is not None
                            and numeric_axis.find('c:delete', ns).get('val')
                            == '1'):
                        hidden_numeric_axes += 1
                self.assertGreaterEqual(hidden_numeric_axes, 2)
            self.assertIsNone(wafer._charts[1].x_axis.title)
            for sheet in book:
                for chart in sheet._charts:
                    if chart.x_axis.delete:
                        self.assertIsNone(chart.x_axis.majorTickMark)
                    else:
                        self.assertEqual(chart.x_axis.majorTickMark, 'out')
                    self.assertEqual(chart.y_axis.majorTickMark, 'out')
                if sheet.title.startswith('Match '):
                    for chart in sheet._charts[2:]:
                        self.assertAlmostEqual(chart.y_axis.scaling.min, -chart.y_axis.scaling.max)
            self.assertAlmostEqual(original._charts[1].anchor.ext.cx / 360000, 25)
            self.assertEqual(group._charts[1].anchor.ext.cx,
                             group._charts[2].anchor.ext.cx)
            self.assertEqual(wafer._charts[1].anchor.ext.cx,
                             wafer._charts[2].anchor.ext.cx)
            self.assertLess(group._charts[1].anchor.ext.cx,
                            original._charts[1].anchor.ext.cx)
            points, = original._charts[0].series
            self.assertIsNotNone(points.trendline)
            self.assertTrue(points.xVal.numRef.f.startswith("'Match Original (WO Card)'!"))
            self.assertFalse(any(d.hidden for d in original.row_dimensions.values()))

    def test_single_wafer_metrics_exposes_the_plotted_row_number(self):
        self.window.results_tabs.setCurrentIndex(1)
        fixtures.APP.processEvents()
        group = self.window.plot_groups['CD']
        frame = group['wafer_model'].frame
        self.assertIn('Row', frame)
        self.assertEqual(frame['Row'].tolist(), list(range(1, len(frame) + 1)))

    def test_fullmap_software_images_have_fixed_physical_height(self):
        buffer = BytesIO()
        Image.new('RGB', (640, 320), 'white').save(buffer, format='PNG')
        contents = buffer.getvalue()
        book = Workbook()
        write_fullmap(book.active, self.raw, ['CD'], pictures=[
            ('Wafer Map CD', contents, ''), ('Radius CD', contents, '')])
        self.assertEqual(len(book.active._images), 2)
        heights = [picture.height for picture in book.active._images]
        for height, expected in zip(heights, (8, 8)):
            self.assertAlmostEqual(height, expected * 96 / 2.54)
        self.assertTrue(all(picture.width <= 72 * 96 / 2.54 for picture in book.active._images))
        self.assertNotEqual(book.active._images[0].anchor, book.active._images[1].anchor)

    def test_dynamic_raw_pivots_parameter_charts_and_summary_share_one_sheet(self):
        from metrology_app.dynamic import dynamic_pivot, prepare_dynamic_frame
        from metrology_app.analysis_export import _series
        raw = pd.DataFrame({'Wafer ID': ['W1'] * 6, 'Die Seq': [1, 2] * 3,
            'DP': ['1.000', '2.000', '3.000', '4.000', '5.000', '6.000'],
            'EW': ['2.000', '3.000', '3.000', '4.000', '4.000', '5.000']})
        prepared = prepare_dynamic_frame(raw)
        frames, plots = {'Data': raw}, []
        for parameter in ('DP', 'EW'):
            pivot = dynamic_pivot(prepared, parameter)
            frames[f'Pivot {parameter}'] = pivot.reset_index()
            plots.append({'sheet': 'Dynamic', 'title': parameter + ' 3 Sigma', 'kind': 'bar',
                'x': 'Die Seq', 'y': '3 Sigma', 'series': [
                    _series(parameter, list(pivot.columns), pivot.loc['3 Sigma'].to_numpy(float))]})
        with tempfile.TemporaryDirectory() as folder:
            for native in (True, False):
                book = Workbook()
                book.remove(book.active)
                append_report(book, set(), {'frames': frames, 'plots': plots, 'pictures': [],
                    'suffix': '', 'kind': 'dynamic', 'pivot_sources': {
                        parameter: {(i // 2, i % 2): (i + 1, raw.columns.get_loc(parameter)) for i in range(6)}
                        for parameter in ('DP', 'EW')}}, native=native)
                self.assertEqual(book.sheetnames, ['Dynamic'])
                sheet = book['Dynamic']
                self.assertEqual(sheet['C2'].value, '1.000')
                panels = sheet._charts if native else sheet._images
                self.assertEqual(len(panels), 3)
                for panel in panels:
                    width = panel.width if native else panel.width * 2.54 / 96
                    self.assertAlmostEqual(width, 18, places=2)
                formulas = [cell.value for cells in sheet for cell in cells if cell.data_type == 'f']
                self.assertIn('=IF(C2="","",IFERROR(C2*1,""))', formulas)
                self.assertTrue(any('3*STDEV(' in formula for formula in formulas))
                anchors = [panel.anchor for panel in panels]
                self.assertNotEqual(anchors[0], anchors[1])
                path = Path(folder) / f'dynamic-{native}.xlsx'
                book.save(path)
                self.assertEqual(load_workbook(path).sheetnames, ['Dynamic'])

    def test_nearly_equal_sigma_values_use_zero_based_bar_tick_spacing(self):
        from openpyxl.chart import BarChart
        from metrology_app.excel_export import chart_limits
        from metrology_app.analysis_export import plot_figure, _series
        values = [.03, .030000000000001]
        chart = BarChart()
        chart_limits(chart, values, bars=True)
        self.assertEqual(chart.y_axis.scaling.min, 0)
        self.assertLess(chart.y_axis.scaling.max / chart.y_axis.majorUnit, 20)
        figure = plot_figure({'title': '3 Sigma', 'kind': 'bar', 'x': 'Die Seq', 'y': '3 Sigma',
            'series': [_series('DP', [1, 2], values)]})
        try:
            figure.canvas.draw()
            self.assertLess(len(figure.axes[0].get_yticks()), 20)
        finally:
            figure.clear()

    def test_dynamic_export_keeps_selected_second_sets_exact_source_cells(self):
        from metrology_app.dynamic_window import DynamicWindow
        from metrology_app.analysis_export import capture_window
        from openpyxl.utils import get_column_letter
        window = DynamicWindow()
        try:
            window.set_table(pd.DataFrame({'Wafer ID': ['W1'] * 6 + ['W2'] * 6,
                'Die Seq': ['01', '02'] * 6,
                'DP': ['10', '20', '12', '22', '14', '24', '100', '200', '120', '220', '140', '240']}), 'QA')
            fixtures.APP.processEvents()
            window.refresh_timer.stop()
            raw = window.model.document_frame()
            window.dynamic_page.set_input(raw, {'metrics': ['DP'], 'wafers': ['second'],
                'groups': {'second': list(range(6, 12))}})
            report = capture_window(window)
            book = Workbook()
            book.remove(book.active)
            append_report(book, set(), report)
            sheet = book['Dynamic']
            column = get_column_letter(raw.columns.get_loc('DP') + 1)
            formula = f'=IF({column}8="","",IFERROR({column}8*1,""))'
            self.assertEqual(float(report['frames']['Pivot DP'].iloc[0, 1]), 100)
            formulas = [cell.value for row in sheet for cell in row if cell.data_type == 'f']
            self.assertIn(formula, formulas)
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            fixtures.APP.processEvents()

    def test_dynamic_source_derived_labels_starting_with_equals_remain_literal(self):
        from metrology_app.dynamic import dynamic_pivot, prepare_dynamic_frame
        raw = pd.DataFrame({'Die Seq': ['=1+1', '02'] * 3, '=DP': range(6)})
        pivot = dynamic_pivot(prepare_dynamic_frame(raw), '=DP').reset_index()
        book = Workbook()
        book.remove(book.active)
        append_report(book, set(), {'frames': {'Data': raw, 'Pivot =DP': pivot},
            'plots': [], 'pictures': [], 'suffix': '', 'kind': 'dynamic'})
        for label in ('=1+1', '=DP'):
            cells = [cell for row in book.active for cell in row if cell.value == label]
            self.assertGreater(len(cells), 1)
            self.assertTrue(all(cell.data_type == 's' for cell in cells))

    def test_native_identity_captions_are_detached_editable_chart_shapes(self):
        from zipfile import ZipFile
        from xml.etree import ElementTree as ET
        with tempfile.TemporaryDirectory() as folder:
            path = self.window.export_excel(Path(folder) / 'captions.xlsx')
            with ZipFile(path) as archive:
                shapes = [name for name in archive.namelist() if name.startswith('xl/drawings/identity-')]
                self.assertTrue(shapes, 'Native identity labels need independent chart shapes, not joined axis brackets')
                root = ET.fromstring(archive.read(shapes[0]))
                ns = {'cdr': 'http://schemas.openxmlformats.org/drawingml/2006/chartDrawing'}
                captions = root.findall('.//cdr:sp[@textlink]', ns)
                self.assertTrue(captions)
                self.assertTrue(all('Match Group' in shape.attrib['textlink'] for shape in captions))
                drawing_ns = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
                self.assertTrue(all(shape.find('.//a:fld[@type="TxLink"]', drawing_ns) is not None
                                    for shape in captions))
                for anchor in root.findall('cdr:relSizeAnchor', ns):
                    name = anchor.find('cdr:sp/cdr:nvSpPr/cdr:cNvPr', ns).get('name')
                    top = float(anchor.find('cdr:from/cdr:y', ns).text)
                    bottom = float(anchor.find('cdr:to/cdr:y', ns).text)
                    if 'plot divider' in name:
                        self.assertEqual(top, .15)
                        self.assertLess(bottom, .80)
                        self.assertIsNotNone(anchor.find('.//a:prstDash[@val="dash"]', drawing_ns))
                    else:
                        self.assertGreater(top, .70)
                    self.assertGreaterEqual(float(anchor.find('cdr:from/cdr:x', ns).text), 0)
                    self.assertLessEqual(float(anchor.find('cdr:to/cdr:x', ns).text), 1)

    def test_native_caption_write_failure_or_cancellation_keeps_previous_report(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'existing.xlsx'
            self.window.export_excel(path)
            previous = path.read_bytes()
            for error in (OSError('drawing write failed'), InterruptedError('Export cancelled')):
                with self.subTest(error=type(error).__name__):
                    with patch('metrology_app.native_chart_labels._drawing', side_effect=error):
                        with self.assertRaises(type(error)):
                            self.window.export_excel(path)
                    self.assertEqual(path.read_bytes(), previous)
                    self.assertEqual(list(Path(folder).glob('.export-*')), [])

    def test_short_neighboring_groups_keep_all_names_without_overlapping_captions(self):
        from zipfile import ZipFile
        from xml.etree import ElementTree as ET
        flags = [0] * 20 + [1] * 3 + [2] * 2 + [3]
        names = ['Old MM1', 'Old MM2', 'New MM1', "New MM2's long name"]
        self.window.set_reference_frame(pd.DataFrame({'CD Reference': [2 * i + 1 for i in range(26)]}))
        self.window.set_raw_frame(pd.DataFrame({'Wafer ID': ['W1'] * 26, 'Die Seq': range(26), 'CD': range(26)}))
        self.window.group_controls.restore({'enabled': True, 'head_names': {str(i): name for i, name in enumerate(names)}},
            pd.DataFrame({'TestFlag': flags}))
        self.window.group_controls.apply_button.click()
        with tempfile.TemporaryDirectory() as folder:
            path = self.window.export_excel(Path(folder) / 'short-groups.xlsx')
            with ZipFile(path) as archive:
                part = next(name for name in archive.namelist() if name.startswith('xl/drawings/identity-'))
                root = ET.fromstring(archive.read(part))
                ns = {'d': 'http://schemas.openxmlformats.org/drawingml/2006/chartDrawing',
                      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
                captions = [
                    anchor for anchor in root
                    if anchor.find('d:sp[@textlink]', ns) is not None
                    and anchor.find(
                        'd:sp/d:nvSpPr/d:cNvPr', ns)
                    .get('name', '').startswith('Caption')]
                self.assertEqual([''.join(t.text for t in anchor.findall('.//a:t', ns)) for anchor in captions], names)
                self.assertFalse(any(
                    anchor.find('d:sp/d:nvSpPr/d:cNvPr', ns)
                    .get('name', '').startswith('Leader')
                    for anchor in root))
                for left, right in zip(captions, captions[1:]):
                    self.assertLess(float(left.find('d:to/d:x', ns).text), float(right.find('d:from/d:x', ns).text))
                for anchor in root:
                    if 'boundary' in anchor.find('d:sp/d:nvSpPr/d:cNvPr', ns).get('name').lower():
                        top = float(anchor.find('d:from/d:y', ns).text)
                        bottom = float(anchor.find('d:to/d:y', ns).text)
                        self.assertGreater(top, .70)
                        self.assertGreaterEqual(bottom - top, .06)
                        self.assertLessEqual(bottom, 1.)
