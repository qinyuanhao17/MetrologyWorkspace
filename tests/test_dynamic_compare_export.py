"""Dynamic editor ownership and parameter comparisons through the live UI."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from metrology_app.analysis_export import capture_window
from metrology_app.dynamic_window import DynamicWindow

APP = QApplication.instance() or QApplication([])


class DynamicCompareExportTests(unittest.TestCase):
    def setUp(self):
        self.window = DynamicWindow()
        self.frame = pd.DataFrame({'Wafer ID': ['W1'] * 6, 'Cycle': [1, 1, 2, 2, 3, 3],
                                   'Die Seq': [1, 2] * 3,
                                   'DP': ['65.000', '66.000', '65.001', '66.001', '65.002', '66.002'],
                                   'EW': ['30.000', '31.000', '30.100', '31.100', '30.200', '31.200']})
        self.window.set_table(self.frame, 'synthetic.csv')
        for i in range(self.window.parameter_list.topLevelItemCount()):
            item = self.window.parameter_list.topLevelItem(i)
            if item.text(0) in ('DP', 'EW'):
                item.setCheckState(0, Qt.CheckState.Checked)
        APP.processEvents()

    def tearDown(self):
        self.window.document.force_close = True
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def test_measurement_editor_is_owned_only_by_dynamic_and_docks_without_copying(self):
        controller = getattr(self.window, 'measurement_floating_editor', None)
        self.assertIsNotNone(controller, 'Dynamic measurement table has no floating controller')
        panel, model, undo = controller.panel, self.window.sheet.model(), self.window.model.undo
        controller.detach()
        self.assertTrue(controller.floating)
        self.assertIs(controller.owner, self.window)
        self.assertIsNone(controller.dialog.parentWidget())
        self.assertFalse(controller.pinned)
        self.assertFalse(controller.dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.window.model.setData(self.window.model.index(1, 3), '65.250')
        controller.dock()
        self.assertIs(self.window.sheet.model(), model)
        self.assertIs(self.window.model.undo, undo)
        self.assertIs(controller.splitter.widget(0), panel)
        self.assertEqual(self.window.model.document_frame().iloc[0, 3], '65.250')
        undo.undo()
        self.assertEqual(self.window.model.document_frame().iloc[0, 3], '65.000')

    def test_compare_parameters_have_independent_y_axes_and_export_mirror(self):
        page = self.window.dynamic_trend
        page.comparisons.clear()
        page.render_interactive(dict(page.panel_tables))
        page.add_compare('DP')
        widget = page.panel_widgets['DP']
        self.assertEqual(len(widget.secondary_views), 1)
        self.assertEqual(widget.secondary_axes[0].labelText, 'EW')
        self.assertEqual(len(widget.listDataItems()), 1)
        secondary = widget.secondary_views[0]
        curves = [c for c in secondary.addedItems if hasattr(c, 'dynamic_series')]
        self.assertEqual(len(curves), 1)
        self.assertTrue(all(c.dynamic_series[0] == 'EW' for c in curves))
        self.assertEqual(curves[0].opts["pen"].widthF(), 2.5)
        self.assertEqual(curves[0].opts["symbol"], "o")
        self.assertEqual(curves[0].opts["symbolSize"], 6)
        expected = page.panel_tables['EW'].iloc[:, 0].to_numpy(float)
        np.testing.assert_array_equal(curves[0].getData()[1], expected)
        self.assertTrue(page.panel_hosts[0].findChildren(QPushButton, 'dynamicAddCompare'))
        page.ensure_export_figure()
        ew_axes = [a for a in page.figure.axes if a.get_ylabel() == 'EW']
        self.assertTrue(any(len(a.lines) == 1 for a in ew_axes))
        # Secondary curves must update from live source edits too.
        changed = self.window.model.document_frame().copy()
        changed.iloc[0, 4] = '30.333'
        page.set_input(changed, page.selection)
        self.assertAlmostEqual(curves[0].getData()[1][0], 30.333)

    def test_dynamic_report_exports_sigma_but_not_per_die_cycle_trends(self):
        page = self.window.dynamic_trend
        page.add_compare('DP')
        report = capture_window(self.window)
        self.assertEqual({p['sheet'] for p in report['plots']}, {'Dynamic'})
        self.assertEqual(len(report['plots']), 2)
        self.assertTrue(all(p['kind'] == 'bar' for p in report['plots']))
        self.assertEqual(len(page.panel_curves('DP')), 2, 'Live comparisons must remain available')
        pd.testing.assert_frame_equal(report['frames']['Data'], self.window.model.document_frame())

    def test_font_change_keeps_cycle_curves_gaps_comparisons_and_views(self):
        page = self.window.dynamic_trend
        frame = self.window.model.document_frame().copy()
        frame.loc[2, 'DP'] = ''
        page.set_input(frame, page.selection)
        page.add_compare('DP')
        self.window.tabs.setCurrentWidget(page)
        self.window.resize(1200, 800)
        self.window.show()
        APP.processEvents()
        widgets, hosts = list(page.plot_widgets), list(page.panel_hosts)
        pickers = dict(page.die_pickers)
        curves = [c for widget in widgets for c in page.data_curves(widget)]
        values = [(c.xData.copy(), c.yData.copy()) for c in curves]
        self.assertTrue(np.isnan(values[0][1][1]))
        widget = page.panel_widgets['DP']
        widget.getViewBox().setRange(xRange=(1.2, 2.8), yRange=(64.9, 65.1), padding=0)
        widget.secondary_views[0].setYRange(29.5, 31.5, padding=0)
        APP.processEvents()
        primary = widget.getViewBox().viewRange()
        secondary = widget.secondary_views[0].viewRange()
        selected = dict(page.selected_dies)
        comparisons = {p: list(names) for p, names in page.comparisons.items()}
        page.ensure_export_figure()
        exported = [(line.get_xdata().copy(), line.get_ydata().copy())
                    for axis in page.figure.axes for line in axis.lines]
        page.font_size.setCurrentText('16')
        APP.processEvents()
        self.assertIn('17pt', page.panel_hosts[0].findChild(QLabel, 'panelTitle').styleSheet())
        for name in ('left', 'bottom'):
            self.assertEqual(widget.getPlotItem().getAxis(name).labelStyle['size'], '15pt')
        self.assertEqual(page.plot_widgets, widgets)
        self.assertEqual(page.panel_hosts, hosts)
        self.assertEqual(page.die_pickers, pickers)
        self.assertEqual(page.selected_dies, selected)
        self.assertEqual(page.comparisons, comparisons)
        self.assertEqual([c for w in widgets for c in page.data_curves(w)], curves)
        np.testing.assert_allclose(widget.getViewBox().viewRange(), primary)
        np.testing.assert_allclose(widget.secondary_views[0].viewRange(), secondary)
        for curve, (x, y) in zip(curves, values):
            np.testing.assert_array_equal(curve.xData, x)
            np.testing.assert_array_equal(curve.yData, y)
            self.assertEqual(curve.opts['connect'], 'finite')
        page.ensure_export_figure()
        self.assertEqual(page.figure.axes[0].title.get_fontsize(), 17)
        after = [line for axis in page.figure.axes for line in axis.lines]
        self.assertEqual(len(after), len(exported))
        for line, (x, y) in zip(after, exported):
            np.testing.assert_array_equal(line.get_xdata(), x)
            np.testing.assert_array_equal(line.get_ydata(), y)

    def test_native_dynamic_sigma_charts_link_editable_pivots_and_summary_is_top_aligned(self):
        from openpyxl import Workbook
        from metrology_app.analysis_export import append_report
        page = self.window.dynamic_trend
        page.add_compare('DP')
        book = Workbook()
        book.remove(book.active)
        append_report(book, set(), capture_window(self.window))
        sheet = book['Dynamic']
        self.assertEqual(len(sheet._charts), 3, 'Only parameter and combined sigma charts are exported')
        ranges = [s.val.numRef.f for c in sheet._charts[:2] for s in c.series]
        self.assertEqual(len(set(ranges)), 2)
        for value_range in ranges:
            from openpyxl.utils.cell import range_boundaries
            left, first, right, last = range_boundaries(value_range.split('!')[1])
            for row in range(first, last + 1):
                cell = sheet.cell(row, left)
                self.assertEqual(cell.data_type, 'f')
                self.assertIn('3*STDEV(', cell.value)
        summary = next(c for c in reversed(sheet[1]) if c.value == 'Die Seq')
        self.assertEqual(sheet.cell(2, summary.column).value, '1')
        self.assertEqual(sheet.cell(2, summary.column + 1).data_type, 'f')
        from openpyxl.utils.cell import coordinate_from_string, column_index_from_string
        letter, row = coordinate_from_string(sheet._charts[-1].anchor)
        self.assertEqual(row, 1)
        self.assertGreater(column_index_from_string(letter), summary.column + 2)
        for root in sheet._charts:
            for chart in root._charts:
                self.assertIsNone(chart.y_axis.scaling.max, 'Editable values must not clip at old fixed bounds')


if __name__ == '__main__':
    unittest.main()
