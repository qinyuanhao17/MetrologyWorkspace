"""Linked edits refresh full Trend values without rebuilding identical axes."""
import unittest

import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QApplication

from metrology_app.sequence_page import SequencePage
from metrology_app.correlation_page import source_pairwise_linear_fits, fit_numeric_pair
from metrology_app.matching_window import MatchingWindow
from tests import test_workbook_copy_data as copy_fixtures

APP = QApplication.instance() or QApplication([])


class CountingRows(list):
    def __init__(self, values):
        super().__init__(values)
        self.walks = 0

    def __iter__(self):
        self.walks += 1
        return super().__iter__()


class PairSelectionReuseTests(unittest.TestCase):
    def test_many_pairs_share_one_source_row_walk_without_changing_fits(self):
        frame = pd.DataFrame({
            'A': ['1.000000000001', '2', '', '4', '5'],
            'B': ['2', '4.2', '6', '8', '9.7'],
            'C': ['3', '5.9', '9', '12.3', '15'],
            'D': ['4', '8.1', '12', '15.8', '20'],
        })
        literal = frame.copy(deep=True)
        # Source order and repeated source positions remain authoritative.
        rows = CountingRows([4, 1, 0, 3, 1, 2])
        sources = ({'name': 'Raw Data', 'rows': rows, 'color': '#123456'},)
        groups = {'w': (0, 1, 2, 3, 4)}
        cells = {('w', metric) for metric in frame}
        fits, errors = source_pairwise_linear_fits(frame, list(frame), sources, groups, cells)
        self.assertEqual(errors, [])
        self.assertEqual(len(fits), 6)
        self.assertEqual(rows.walks, 1, 'Repeated parameter pairs rescan the same source rows')
        for panel in fits:
            fit = panel.sources[0].fit
            expected = fit_numeric_pair(frame.iloc[[4, 1, 0, 3, 1, 2]], fit.x_name, fit.y_name)
            for field in ('x', 'y', 'predicted'):
                np.testing.assert_array_equal(getattr(fit, field), getattr(expected, field))
            self.assertEqual((fit.slope, fit.intercept, fit.rsquared),
                             (expected.slope, expected.intercept, expected.rsquared))
        pd.testing.assert_frame_equal(frame, literal)


class LinkedPlotRefreshTests(unittest.TestCase):
    def setUp(self):
        self.page = SequencePage()
        self.page.overlay = {}
        self.page.source_overlay = {}
        self.frame = pd.DataFrame({
            'Wafer ID': ['W1']*4 + ['W2']*4,
            'Die Seq': ['01', '02', '03', '04']*2,
            'CD': ['1.000000000001', '2', '', '4', '5', '6', '7', '8'],
            'EW': ['2', '4', '6', '8', '10', '12', '14', '16'],
        })
        self.selection = dict(wafers=['W1', 'W2'], metrics=['CD', 'EW'],
                              wafer_column='Wafer ID', groups={'W1': (0, 1, 2, 3), 'W2': (4, 5, 6, 7)})
        self.page.set_input(self.frame, self.selection)
        self.page.selector.selectAll()
        self.page.draw_plot()
        self.assertTrue(self.page.ready)

    def tearDown(self):
        self.page.input_refresh_timer.stop()
        self.page.close()
        self.page.deleteLater()
        APP.processEvents()

    def refresh(self, frame=None, selection=None):
        state = self.page.draw_state()
        self.page.set_input(self.frame if frame is None else frame,
                            self.selection if selection is None else selection)
        self.page.restore_draw_state(state)
        self.assertTrue(self.page.ready, self.page.status.text())

    def assert_current_data(self, frame):
        exported = self.page.export_plot_data()
        for metric, widget, output in zip(self.page.metrics, self.page.plot_widgets, exported):
            curve, = widget.listDataItems()
            values = pd.to_numeric(frame[metric], errors='coerce').to_numpy(float)
            np.testing.assert_array_equal(curve.yData, values)
            np.testing.assert_array_equal(curve.xData, np.arange(8))
            np.testing.assert_array_equal(output['series'][0]['data']['Y'], values)
            self.assertEqual(curve.opts['connect'], 'finite')

    def test_value_refresh_reuses_widgets_and_curves_with_full_nan_data(self):
        widgets = self.page.plot_widgets.copy()
        curves = [widget.listDataItems()[0] for widget in widgets]
        changed = self.frame.copy(deep=True)
        changed.loc[1, 'CD'] = '200.000000000001'
        literal = changed.copy(deep=True)
        self.refresh(changed)
        pd.testing.assert_frame_equal(changed, literal)
        self.assertEqual(self.page.plot_widgets, widgets)
        self.assertEqual([w.listDataItems()[0] for w in widgets], curves)
        self.assert_current_data(changed)
        self.assertEqual(self.page.wafer_ticks, [(1.5, 'W1'), (5.5, 'W2')])
        self.assertIn('200', widgets[0]._statistics_text)
        self.page.ensure_export_figure()
        exported = next(line for line in self.page.figure.axes[0].lines
                        if len(line.get_ydata()) == len(curves[0].yData))
        np.testing.assert_array_equal(exported.get_ydata(), curves[0].yData)
        # Reverting the source follows the same route as the linked Undo.
        self.refresh(self.frame)
        self.assertEqual(self.page.plot_widgets, widgets)
        self.assert_current_data(self.frame)

    def test_coordinate_change_rebuilds_axes_and_retains_exact_dies(self):
        widgets = self.page.plot_widgets.copy()
        changed = self.frame.copy(deep=True)
        changed.loc[1, 'Die Seq'] = '20'
        self.refresh(changed)
        self.assertNotEqual(self.page.plot_widgets, widgets)
        self.assertEqual(self.page.plot_widgets[0].getAxis('bottom').ticks[:4],
                         [(0., '1'), (1., '3'), (2., '4'), (3., '20')])

    def test_group_membership_change_rebuilds_the_geometry(self):
        widgets = self.page.plot_widgets.copy()
        changed = {**self.selection, 'groups': {'W1': (0, 1, 3), 'W2': (4, 5, 6, 7)}}
        self.refresh(selection=changed)
        self.assertNotEqual(self.page.plot_widgets, widgets)
        self.assertEqual(len(self.page.plot_widgets[0].listDataItems()[0].xData), 7)

    def test_comparisons_use_complete_renderer_after_value_refresh(self):
        self.assertTrue(self.page.set_overlay('CD', 'EW'))
        widgets = self.page.plot_widgets.copy()
        changed = self.frame.copy(deep=True)
        changed.loc[1, 'CD'] = '200'
        self.refresh(changed)
        self.assertNotEqual(self.page.plot_widgets, widgets)
        self.assertEqual(len(self.page.export_plot_data()[0]['series']), 2)

    def test_pending_manual_selection_does_not_show_or_export_old_curves(self):
        self.page.selector.set_selected_cells({('W1', 'CD')})
        self.assertFalse(self.page.ready)
        self.assertEqual(self.page.plot_widgets, [])
        self.assertFalse(self.page.copy_button.isEnabled())

    def test_expanded_wafer_spacing_uses_complete_renderer(self):
        self.page.expand_wafer_ids.setChecked(True)
        widgets = self.page.plot_widgets.copy()
        self.refresh()
        self.assertNotEqual(self.page.plot_widgets, widgets)

    def test_clearing_input_discards_retained_widgets_and_filter_state(self):
        self.page.set_input(pd.DataFrame(), dict(wafers=[], metrics=[]))
        self.assertEqual(self.page.plot_widgets, [])
        self.assertEqual(self.page.parameter_filter.names, ())
        self.assertFalse(self.page.copy_button.isEnabled())
        self.page.set_input(self.frame, self.selection)
        self.page.selector.selectAll()
        self.page.draw_plot()
        self.assertEqual(set(self.page.parameter_filter.names), {'CD', 'EW'})


class LinkedWorkbookRefreshTests(unittest.TestCase):
    def test_parent_edit_undo_redo_keep_trend_widgets_and_literal_sources(self):
        parent = MatchingWindow()
        self.addCleanup(copy_fixtures.WorkbookCopyDataTests.close_window, parent)
        reference, raw, _ = copy_fixtures.WorkbookCopyDataTests.sources()
        parent.match_type.setCurrentText('NOVA')
        parent.set_reference_frame(reference)
        parent.set_raw_frame(raw)
        parent.run_analysis()
        before = parent.raw_model.document_frame().copy(deep=True)
        summary = parent.result.summary.copy(deep=True)
        child = parent.open_correlation_workspace()
        child.set_reference_table(reference)
        for tree in (child.wafer_list, child.parameter_list,
                     child.reference_wafer_list, child.reference_parameter_list):
            child.check_all(tree, True)
        page = child.sequence_page
        page.overlay, page.source_overlay = {}, {}
        page.expand_wafer_ids.setChecked(False)
        page.selector.selectAll()
        page.draw_plot()
        widgets = page.plot_widgets.copy()
        originals = [widget.listDataItems()[0].yData.copy() for widget in widgets]
        column = parent.raw_model.source_headers().index('CD')
        parent.raw_model.edit({(1, column): '1.10000000000001'})
        parent.run_analysis()
        self.assertEqual(page.plot_widgets, widgets)
        self.assertEqual(child.raw_model.document_frame().iloc[0]['CD'], '1.10000000000001')
        parent.raw_model.undo.undo()
        parent.run_analysis()
        self.assertEqual(page.plot_widgets, widgets)
        pd.testing.assert_frame_equal(parent.raw_model.document_frame(), before)
        pd.testing.assert_frame_equal(parent.result.summary, summary)
        for widget, original in zip(widgets, originals):
            np.testing.assert_array_equal(widget.listDataItems()[0].yData, original)
        parent.raw_model.undo.redo()
        parent.run_analysis()
        self.assertEqual(page.plot_widgets, widgets)
        self.assertEqual(child.raw_model.document_frame().iloc[0]['CD'], '1.10000000000001')
        exported = page.export_plot_data()
        for widget, plot in zip(widgets, exported):
            np.testing.assert_array_equal(widget.listDataItems()[0].yData,
                                          plot['series'][0]['data']['Y'])


if __name__ == '__main__':
    unittest.main()
