"""Native Die Seq ranges only when categorical positions preserve the report."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from uuid import UUID

import numpy as np
import pandas as pd
from openpyxl import load_workbook
from openpyxl.chart import LineChart, ScatterChart
from openpyxl.utils.cell import range_boundaries

from tests import test_excel_export as fixtures
from metrology_app import excel_export


class NativeDieCategoryTests(unittest.TestCase):
    tearDown = fixtures.ExcelExportTests.tearDown

    def setUp(self):
        self.window = fixtures.MatchingWindow()
        self.window.match_type.setCurrentText('NOVA')
        self.raw = pd.DataFrame({
            'Wafer ID': [f'G{g}W{w}' for g in range(2) for w in range(2) for _ in range(3)],
            'Die Seq': ['001', '007', '003'] * 4,
            'CD': [f'{i}.0000' for i in range(1, 13)],
            'EW': [f'{i + 20}.0000' for i in range(1, 13)],
        })
        self.window.set_reference_frame(pd.DataFrame({
            'CD Reference': [i * 2 + 1 for i in range(1, 13)],
            'EW Reference': [i * 3 + 2 for i in range(1, 13)],
        }))
        self.window.set_raw_frame(self.raw.copy())

    def groups(self, shown=()):
        self.window.group_controls.restore({
            'enabled': True,
            'head_names': {'0': 'Old MM1', '1': 'New MM2'},
            'show_wafer_groups': list(shown),
        }, pd.DataFrame({'TestFlag': [0] * 6 + [1] * 6}))
        self.window.group_controls.apply_button.click()
        self.window.percent_bias.setChecked(True)
        self.window.run_analysis()

    def assert_native_ranges(self, sheet):
        self.assertEqual(len(sheet._charts), 8)
        for parameter_index in range(2):
            start = parameter_index * 4
            self.assertIsInstance(sheet._charts[start], ScatterChart)
            for chart in sheet._charts[start + 1:start + 4]:
                self.assertTrue(isinstance(chart, LineChart), type(chart).__name__)
                self.assertEqual(chart.y_axis.crossBetween, 'between')
                self.assertFalse(chart.visible_cells_only)
                self.assertTrue(chart.x_axis.delete)
                for series in chart.series:
                    reference = series.cat.strRef
                    self.assertTrue(reference.f.startswith(f"'{sheet.title}'!"))
                    low_col, low_row, high_col, high_row = range_boundaries(reference.f.split('!', 1)[1])
                    self.assertEqual(low_col, high_col)
                    self.assertEqual(sheet.cell(low_row - 1, low_col).value, 'Die Seq')
                    die_columns = [c.column for c in sheet[2] if c.value == 'Die Seq']
                    self.assertEqual(low_col, die_columns[parameter_index])
                    self.assertEqual([p.v for p in reference.strCache.pt],
                                     [sheet.cell(r, low_col).value for r in range(low_row, high_row + 1)])
                    per_wafer = ['001', '007', '003'] if sheet.title.startswith('Match Wafer') else ['001', '003', '007']
                    self.assertEqual([p.v for p in reference.strCache.pt], per_wafer * (len(reference.strCache.pt) // 3))
                    self.assertIsNotNone(series.val.numRef)

    def test_uniform_reports_bind_each_parameter_own_die_range_in_both_stages(self):
        self.groups()
        with tempfile.TemporaryDirectory() as directory:
            for stage, suffix in (('Preview', 'WO Card'), ('Final', 'W Card')):
                self.window.result_mode.setCurrentText(stage)
                self.window.set_raw_frame(self.raw.copy())
                self.groups()
                book = load_workbook(self.window.export_excel(Path(directory) / f'{stage}.xlsx'))
                try:
                    for title in ('Match Group', 'Match Wafer', 'Match Old MM1', 'Match New MM2'):
                        self.assert_native_ranges(book[f'{title} ({suffix})'])
                finally:
                    book.close()

    def test_all_expanded_uses_die_but_mixed_uses_existing_xy(self):
        with tempfile.TemporaryDirectory() as directory:
            for shown in (('All:0', 'All:1'), ('All:1',)):
                self.groups(shown)
                book = load_workbook(self.window.export_excel(Path(directory) / f'{len(shown)}.xlsx'))
                try:
                    title = next(name for name in book.sheetnames if name.startswith('Match Group show Wafer'))
                    sheet = book[title]
                    if len(shown) == 2:
                        self.assert_native_ranges(sheet)
                    else:
                        self.assertIsInstance(sheet._charts[1], ScatterChart)
                        self.assertTrue(sheet._charts[1].series[0].xVal.numRef.f.startswith("'_Plot data'!"))
                        self.assert_native_ranges(book['Match Wafer (WO Card)'])
                finally:
                    book.close()

    def test_category_conversion_preserves_all_identity_drawing_bytes_and_sizes(self):
        self.groups(('All:0', 'All:1'))
        with tempfile.TemporaryDirectory() as directory:
            with patch('metrology_app.native_chart_labels.uuid4', side_effect=(UUID(int=i) for i in range(1, 10000))):
                current = self.window.export_excel(Path(directory) / 'native-die.xlsx')
            with patch('metrology_app.native_chart_labels.uuid4', side_effect=(UUID(int=i) for i in range(1, 10000))), patch.object(excel_export, '_native_die_axis_eligible', return_value=False):
                previous = self.window.export_excel(Path(directory) / 'previous-xy.xlsx')
            with ZipFile(current) as new, ZipFile(previous) as old:
                names = [name for name in new.namelist() if name.startswith('xl/drawings/identity-')]
                self.assertTrue(names)
                for name in names:
                    self.assertEqual(new.read(name), old.read(name), name)
            new, old = load_workbook(current), load_workbook(previous)
            try:
                for sheet in new:
                    for a, b in zip(sheet._charts, old[sheet.title]._charts):
                        self.assertEqual(a.anchor, b.anchor)
                        self.assertEqual(a.layout, b.layout)
                        self.assertEqual(a.y_axis.scaling, b.y_axis.scaling)
            finally:
                new.close()
                old.close()
        pd.testing.assert_frame_equal(self.window.raw_model.document_frame(), self.raw)

    def test_eligibility_rejects_nonuniform_and_mixed_even_with_uniform_points(self):
        data = pd.DataFrame({'Group': ['A'] * 3 + ['B'] * 3,
                             'Show wafer': [False] * 6, 'Die Seq': ['01', '7', '3'] * 2})
        layout = {'x': np.arange(6) + .5, 'limits': (0., 6.),
                  'source': [0., 3., 6.], 'display': [0., 3., 6.],
                  'captions': [], 'native_captions': []}
        self.assertTrue(excel_export._native_die_axis_eligible(data, layout, 'group'))
        mixed = data.assign(**{'Show wafer': [False] * 3 + [True] * 3})
        self.assertFalse(excel_export._native_die_axis_eligible(mixed, layout, 'group'))
        self.assertTrue(excel_export._native_die_axis_eligible(mixed, layout, 'wafer'))
        skewed = deepcopy(layout)
        skewed['x'][2] += .1
        self.assertFalse(excel_export._native_die_axis_eligible(data, skewed, 'group'))
        skewed = dict(layout, display=[0., 4., 6.])
        self.assertFalse(excel_export._native_die_axis_eligible(data, skewed, 'group'))
        self.assertFalse(excel_export._native_die_axis_eligible(data.iloc[:0], layout, 'group'))

    def test_long_labels_and_unequal_missing_pairs_keep_numeric_geometry(self):
        for shown in (False, True):
            data = pd.DataFrame({
                'Group': ['A'] * 2 + ['B'] * 4,
                'Group label': ['A'] * 2 + ['Very long group identity ' * 20] * 4,
                'Wafer': ['W1'] * 2 + ['Very long wafer identity ' * 20] * 4,
                'Wafer key': ['W1'] * 2 + ['W2'] * 4,
                'Show wafer': [shown] * 6, 'Die Seq': ['01', '7', '3'] * 2,
                'Raw': [1.] * 6, 'Reference': [1.] * 6,
            })
            layout = excel_export.sequence_export_layout(data, mode='group')
            self.assertFalse(excel_export._native_die_axis_eligible(data, layout, 'group'))
        data['Group label'] = data['Group']
        data['Wafer'] = data['Wafer key']
        data['Show wafer'] = False
        data.loc[0, 'Reference'] = np.nan
        layout = excel_export.sequence_export_layout(data, mode='group')
        self.assertFalse(excel_export._native_die_axis_eligible(data, layout, 'group'))
        self.assertEqual(len(layout['x']), 6)

    def test_single_observation_and_invalid_positions(self):
        data = pd.DataFrame({'Die Seq': ['0007']})
        layout = {'x': [.5], 'limits': (0., 1.), 'source': [0., 1.],
                  'display': [0., 1.], 'captions': [], 'native_captions': []}
        self.assertTrue(excel_export._native_die_axis_eligible(data, layout, 'wafer'))
        for changed in ({'x': [np.nan]}, {'limits': (0., 0.)}, {'x': [.4]}):
            self.assertFalse(excel_export._native_die_axis_eligible(data, dict(layout, **changed), 'wafer'))
