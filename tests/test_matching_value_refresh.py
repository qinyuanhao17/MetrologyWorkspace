"""Steady Workbook edits reuse artists and retain the freshly rendered geometry."""
import unittest
import numpy as np
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
