"""Steady Workbook edits reuse artists and retain the freshly rendered geometry."""
import unittest
from time import monotonic
import numpy as np
import pandas as pd
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from metrology_app.matching_window import MatchingWindow
from tests import test_workbook_copy_data as fixtures

APP = QApplication.instance() or QApplication([])

class MatchingValueRefreshTests(unittest.TestCase):
    def setUp(self):
        self.window = self.create()
        self.column = self.window.raw_model.source_headers().index('CD')

    def create(self):
        window = MatchingWindow()
        self.addCleanup(fixtures.WorkbookCopyDataTests.close_window, window)
        reference, raw, _ = fixtures.WorkbookCopyDataTests.sources()
        window.match_type.setCurrentText('NOVA')
        window.set_reference_frame(reference)
        window.set_raw_frame(raw)
        window.percent_bias.setChecked(True)
        window.run_analysis()
        return window

    def compare(self, expected):
        for parameter, group in self.window.plot_groups.items():
            other = expected.plot_groups[parameter]
            for name, plot in group['plots'].items():
                with self.subTest(parameter=parameter, plot=name):
                    actual, fresh = plot.listDataItems(), other['plots'][name].listDataItems()
                    self.assertEqual(len(actual),len(fresh))
                    for item, reference in zip(actual,fresh):
                        np.testing.assert_array_equal(item.xData,reference.xData)
                        np.testing.assert_array_equal(item.yData,reference.yData)
                        for key in ('symbol','symbolSize','name','connect'):
                            self.assertEqual(item.opts.get(key),reference.opts.get(key))
                    self.assertEqual(plot.getAxis('left').labelText,other['plots'][name].getAxis('left').labelText)

    def test_value_edit_and_undo_redo_reuse_curves_and_match_fresh_render(self):
        old = {name: tuple(plot.listDataItems()) for name,plot in self.window.plot_groups['CD']['plots'].items()}
        self.window.raw_model.edit({(1,self.column):'1.1234567890123'})
        expected = self.create()
        for operation in (lambda: None,self.window.raw_model.undo.undo,self.window.raw_model.undo.redo):
            operation()
            self.window.run_analysis(apply_groups=False)
            expected.set_raw_frame(self.window.raw_model.document_frame())
            expected.run_analysis()
            self.compare(expected)
            for name,plot in self.window.plot_groups['CD']['plots'].items():
                self.assertEqual(tuple(plot.listDataItems()),old[name])

    def test_nan_edit_uses_full_fallback_with_the_same_gaps_as_fresh_render(self):
        old = tuple(self.window.plot_groups['CD']['plots']['match'].listDataItems())
        self.window.raw_model.edit({(1,self.column):''})
        self.window.run_analysis(apply_groups=False)
        expected=self.create()
        expected.set_raw_frame(self.window.raw_model.document_frame())
        expected.run_analysis()
        self.compare(expected)
        self.assertNotEqual(tuple(self.window.plot_groups['CD']['plots']['match'].listDataItems()),old)

    def test_large_automatic_refresh_yields_before_plotting_and_finishes_latest_values(self):
        from benchmarks.benchmark_memory_storage import settle
        reference, raw, _ = fixtures.WorkbookCopyDataTests.sources()
        reference = pd.concat([reference] * 500, ignore_index=True)
        raw = pd.concat([raw] * 500, ignore_index=True)
        w = self.window
        w.set_reference_frame(reference)
        w.set_raw_frame(raw)
        w.run_analysis()
        observations = []
        w.raw_model.edit({(1, self.column): '1.1234567890123'})
        QTimer.singleShot(0, lambda: observations.append((
            w.result.series('CD')['Raw'].iloc[0],
            w.plot_groups['CD']['plots']['match'].listDataItems()[0].xData[0])))
        deadline = monotonic() + 5
        while not observations:
            self.assertLess(monotonic(), deadline, 'Automatic analysis did not reach the event loop')
            QTest.qWait(5)
        self.assertEqual(observations, [(1.1234567890123, 1.0)],
                         'Native input must get an event-loop turn between analysis and plotting')
        w.raw_model.undo.undo()
        w.raw_model.undo.redo()
        settle(APP, [w])
        expected = self.create()
        expected.set_reference_frame(reference)
        expected.set_raw_frame(w.raw_model.document_frame())
        expected.run_analysis()
        self.compare(expected)

    def test_undoing_a_missing_value_restores_points_and_die_hover_together(self):
        self.window.raw_model.edit({(1, self.column): ''})
        self.window.run_analysis(apply_groups=False)
        self.window.raw_model.undo.undo()
        self.window.run_analysis(apply_groups=False)
        self.compare(self.create())
        points = self.window.plot_groups['CD']['plots']['match'].listDataItems()[0]
        self.assertEqual(points.opts['data'], ['002', '036', '050', '085'])

    def test_numeric_edit_retains_single_wafer_metric_points_with_fresh_fit_values(self):
        w = self.window
        old = {key: tuple(w.plot_groups['CD'][key].listDataItems()) for key in ('wafer_r2', 'wafer_slope')}
        w.raw_model.edit({(1, self.column): '1.1234567890123'})
        w.run_analysis(apply_groups=False)
        expected = self.create()
        expected.set_raw_frame(w.raw_model.document_frame())
        expected.run_analysis()
        for key, items in old.items():
            actual = tuple(w.plot_groups['CD'][key].listDataItems())
            self.assertEqual(actual, items)
            np.testing.assert_array_equal(actual[0].yData, expected.plot_groups['CD'][key].listDataItems()[0].yData)

    def test_selected_wafer_detail_reuses_curves_for_a_numeric_edit(self):
        w = self.window
        model = w.plot_groups['CD']['wafer_model']
        model.setData(model.index(0, model.frame.columns.get_loc('Draw')),
                      Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
        detail = next(iter(w.plot_groups['CD']['wafer_details'].values()))
        points = detail['plots']['match'].listDataItems()[0]
        w.raw_model.edit({(1, self.column): '1.1234567890123'})
        w.run_analysis(apply_groups=False)
        current = next(iter(w.plot_groups['CD']['wafer_details'].values()))
        self.assertIs(current['card'], detail['card'])
        self.assertIs(current['plots']['match'].listDataItems()[0], points)
        np.testing.assert_array_equal(points.xData, [1.1234567890123, 2., 3., 4.])
