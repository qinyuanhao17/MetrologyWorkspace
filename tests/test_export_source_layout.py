"""Export source layout and scientific presentation, through real exporters."""
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
from openpyxl import Workbook, load_workbook
from matplotlib.colors import to_hex

from tests import test_excel_export as fixtures
from metrology_app.excel_export import parameter_figure, style_workbook, write_fullmap


def title_text(title):
    return '\n'.join(''.join(run.t for run in p.r) for p in title.tx.rich.p)


class ExportSourceLayoutTests(unittest.TestCase):
    tearDown = fixtures.ExcelExportTests.tearDown

    def setUp(self):
        self.window = fixtures.MatchingWindow()
        self.window.match_type.setCurrentText('NOVA')

    def test_match_reference_is_in_parameter_table_not_a_second_source_area(self):
        self.window.set_reference_frame(pd.DataFrame({'CD Reference': ['3.000', '', '7.000']}))
        self.window.set_raw_frame(pd.DataFrame({'Wafer ID': ['W1'] * 4, 'Die Seq': ['01', '02', '03', '04'],
                                              'CD': ['1.000', '2.000', '3.000', '4.000']}))
        self.window.run_analysis()
        before = self.window.workspace_snapshot()
        with tempfile.TemporaryDirectory() as folder:
            for native in (True, False):
                book = load_workbook(self.window.export_excel(Path(folder) / f'{native}.xlsx', native=native))
                try:
                    original = book['Match Original (WO Card)']
                    self.assertFalse(any('Reference (NOVA)' in str(c.value) for c in original[1]))
                    self.assertEqual([original.cell(r, 5).value for r in range(3, 7)], [3., None, 7., None])
                    wafer = book['Match Wafer (WO Card)']
                    self.assertIn("'Match Original (WO Card)'!$E$3", wafer['E3'].value)
                    self.assertIn("'Match Original (WO Card)'!$E$5", wafer['E5'].value)
                    self.assertEqual(book['_Plot data']['A2'].value, '3.000')
                    if native:
                        match, trend, _bias = original._charts
                        self.assertEqual(title_text(match.x_axis.title), 'PMISH')
                        self.assertEqual(title_text(match.y_axis.title), 'NOVA')
                        self.assertEqual(title_text(trend.x_axis.title), 'Die Seq')
                        self.assertEqual(trend.legend.position, 't')
                        self.assertEqual(trend.series[0].tx.v, 'PMISH')
                finally:
                    book.close()
        after = self.window.workspace_snapshot()
        self.assertEqual(before.states, after.states)
        for key in before.frames:
            pd.testing.assert_frame_equal(before.frames[key], after.frames[key])

    def test_fm_organized_report_precedes_literal_source_and_keeps_native_curve_editable(self):
        frame = pd.DataFrame({'Wafer ID': ['W1'] * 5, 'Die Seq': ['01', '02', '04', '05', '08'],
                              'UC': ['2.9363', '3.352', '3.4214', '2.943', '4.2821']})
        for native in (True, False):
            book = Workbook()
            sheet = book.active
            write_fullmap(sheet, frame, ['UC'], native=native)
            style_workbook(book)
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'fm.xlsx'
                book.save(path)
                exported = load_workbook(path)
                try:
                    view = exported.active
                    report_col = next(c.column for c in view[1] if c.value == 'Wafer')
                    source_col = next(c.column for c in view[1] if c.value == 'Wafer ID')
                    self.assertLess(report_col + 2, source_col)
                    self.assertEqual([view.cell(r, source_col + 2).value for r in range(2, 7)], frame['UC'].tolist())
                    self.assertIn(view.cell(2, source_col + 2).coordinate, view.cell(2, report_col + 2).value)
                    if native:
                        chart = view._charts[0]
                        self.assertEqual(len(chart.series), 1)
                        series = chart.series[0]
                        self.assertFalse(series.smooth)
                        self.assertFalse(chart.smooth)
                        self.assertEqual([p.v for p in series.cat.strRef.strCache.pt], frame['Die Seq'].tolist())
                        self.assertIn(view.cell(2, report_col + 2).column_letter, series.val.numRef.f)
                        self.assertEqual(title_text(chart.x_axis.title), 'Die Seq')
                        self.assertEqual(chart.legend.position, 't')
                finally:
                    exported.close()

    def test_matplotlib_match_header_and_trend_semantics_match_wkb(self):
        self.window.set_reference_frame(pd.DataFrame({'CD Reference': [3., 5., 7.]}))
        self.window.set_raw_frame(pd.DataFrame({'CD': [1., 2., 3.]}))
        card = self.window.run_analysis().card('CD')
        data = pd.DataFrame({'Raw': [1., 2., 3.], 'Reference': [3., 5., 7.]})
        match = parameter_figure('CD', data, card, 'Preview', 'All', reference_label='NOVA')
        trend = parameter_figure('CD', data, card, 'Preview', 'All', panel='Trend', reference_label='NOVA')
        try:
            axis = match.axes[0]
            self.assertTrue(all(text.get_position()[1] > 1 for text in axis.texts))
            self.assertEqual(to_hex(axis.collections[0].get_facecolors()[0]), '#4f8bd6')
            self.assertEqual(to_hex(axis.lines[0].get_color()), '#e09f3e')
            self.assertEqual([line.get_label() for line in trend.axes[0].lines[:2]], ['PMISH', 'NOVA'])
            self.assertEqual([line.get_marker() for line in trend.axes[0].lines[:2]], ['o', 'o'])
            self.assertEqual([to_hex(line.get_color()) for line in trend.axes[0].lines[:2]], ['#5b9bd5', '#ed7d31'])
            np.testing.assert_allclose(match.get_size_inches(), [15 / 2.54, 11 / 2.54])
            self.assertEqual(axis.title.get_fontsize(), 16)
            self.assertEqual(axis.xaxis.label.get_fontsize(), 12)
        finally:
            match.clear()
            trend.clear()


if __name__ == '__main__':
    unittest.main()
