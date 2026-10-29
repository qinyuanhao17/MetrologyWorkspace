"""Correlation grid construction yields without publishing partial pages."""
import threading
import sys
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from metrology_app import correlation_page as module
from metrology_app.correlation_page import CorrelationPage


APP = QApplication.instance() or QApplication([])


def complete(page):
    from time import monotonic
    deadline = monotonic() + 8
    while page.background_render_pending:
        if monotonic() > deadline:
            raise AssertionError('Correlation rendering did not finish')
        QTest.qWait(5)
    APP.processEvents()


class CorrelationRenderBatchTests(unittest.TestCase):
    def page(self):
        rng = np.random.default_rng(4715)
        frame = pd.DataFrame({f'P{i}': np.arange(180.) * (i + 1) + rng.normal(0, .5, 180)
                              for i in range(6)})
        selection = {'wafers': ['W'], 'metrics': list(frame), 'groups': {'W': tuple(range(len(frame)))}}
        page = CorrelationPage()
        self.addCleanup(self.dispose, page)
        page.resize(1100, 800)
        page.show()
        page.set_input(frame, selection)
        page.selector.selectAll()
        page.page_intent = 'plots'
        return page

    @staticmethod
    def dispose(page):
        if not sip.isdeleted(page):
            page.stop_background_draw()
            page.close()
            page.deleteLater()
        APP.processEvents()

    def test_large_page_yields_between_small_batches_and_publishes_all_panels(self):
        page = self.page()
        built, between, published = [], [], []
        main_thread = threading.get_ident()
        original = module.InteractivePlotWidget
        def create(*args, **kwargs):
            self.assertEqual(threading.get_ident(), main_thread)
            widget = original(*args, **kwargs)
            built.append(widget)
            if len(built) == 2:
                QTimer.singleShot(0, lambda: between.append(len(built)))
            return widget
        timer = QTimer(interval=1)
        timer.timeout.connect(lambda: published.append(len(page.plot_widgets)))
        timer.start()
        try:
            with patch.object(module, 'InteractivePlotWidget', side_effect=create):
                page.draw_plot()
                self.assertLessEqual(len(built), 3, 'All panels were constructed synchronously')
                self.assertTrue(page.background_render_pending)
                complete(page)
        finally:
            timer.stop()
        self.assertEqual(len(built), 12)
        self.assertEqual(len(page.plot_widgets), 12)
        self.assertIn(2, between, 'GUI events did not run between construction batches')
        self.assertTrue(all(count in (0, 12) for count in published), published)
        self.assertTrue(page.ready)
        self.assertTrue(page.copy_button.isEnabled())
        for fit, widget in zip(page.page_fits(), page.plot_widgets):
            scatter, line = widget.listDataItems()
            np.testing.assert_array_equal(scatter.getData()[0], fit.x)
            np.testing.assert_array_equal(scatter.getData()[1], fit.y)
            order = np.argsort(fit.x)
            np.testing.assert_array_equal(line.yData, fit.predicted[order])

    def test_rebuild_keeps_complete_old_canvas_until_full_publication(self):
        page = self.page()
        page.draw_plot()
        complete(page)
        old, widgets = page.plot_host, list(page.plot_widgets)
        page.font_size.blockSignals(True)
        page.font_size.setCurrentText('12')
        page.font_size.blockSignals(False)
        page.render_fits()
        self.assertTrue(page.background_render_pending)
        self.assertIs(page.plot_host, old)
        self.assertIs(page.interactive_scroll.widget(), old)
        self.assertFalse(old.isHidden())
        self.assertEqual(page.plot_widgets, widgets)
        self.assertFalse(page.copy_button.isEnabled())
        complete(page)
        self.assertIsNot(page.plot_host, old)
        self.assertEqual(len(page.plot_widgets), 12)
        self.assertEqual(len(page._visible_panel_keys), 12)
        self.assertTrue(page.copy_button.isEnabled())

    def test_newest_input_wins_and_cancelled_staging_grid_is_destroyed(self):
        page = self.page()
        page.draw_plot()
        stale = page._batch_state['grid']
        first_generation = page._render_generation
        for offset in (100, 200):
            frame = page.frame.copy()
            frame['P0'] = np.arange(len(frame), dtype=float) ** 2 + offset
            page.set_input(frame, page.selection)
            page.draw_plot()
        self.assertGreater(page._render_generation, first_generation)
        complete(page)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertTrue(sip.isdeleted(stale))
        self.assertEqual(page.frame['P0'].iloc[0], 200)
        self.assertEqual(page._visible_panel_keys,
                         [page._panel_key(fit, int(page.font_size.currentText())) for fit in page.page_fits()])
        for fit, widget in zip(page.page_fits(), page.plot_widgets):
            scatter, line = widget.listDataItems()
            np.testing.assert_array_equal(scatter.getData()[0], fit.x)
            np.testing.assert_array_equal(scatter.getData()[1], fit.y)
            np.testing.assert_array_equal(line.yData, fit.predicted[np.argsort(fit.x)])

    def test_pagination_filter_and_threshold_changes_replace_pending_page(self):
        page = self.page()
        page.draw_plot()
        page.set_page(1)
        page.page_size.setCurrentText('6')
        page.parameter_filter.set_selection(['P2'])
        complete(page)
        self.assertEqual(page.page_index, 0)
        self.assertEqual(len(page.plot_widgets), 5)
        self.assertTrue(all('P2' in (fit.x_name, fit.y_name) for fit in page.page_fits()))
        page.font_size.setCurrentText('12')
        page.flush_updates()
        self.assertTrue(page.background_render_pending)
        page.min_rsq.setValue(1)
        self.assertIsNone(page._batch_state, 'Changed controls allowed the older render to continue')
        page.flush_updates()
        self.assertEqual(page.fits, [])
        self.assertFalse(page.copy_button.isEnabled())
        page.min_rsq.setValue(0)
        page.flush_updates()
        complete(page)
        self.assertEqual(len(page.plot_widgets), len(page.page_fits()))

    def test_retained_grid_reuses_widgets_and_keeps_custom_zoom(self):
        page = self.page()
        page.draw_plot()
        complete(page)
        host, widgets = page.plot_host, list(page.plot_widgets)
        widget = widgets[0]
        widget.getViewBox().setRange(xRange=(20, 40), yRange=(30, 60), padding=0)
        zoom = widget.getViewBox().viewRange()
        state = page.draw_state()
        changed = page.frame * 1.001 + .01
        page.set_input(changed, page.selection)
        page.restore_draw_state(state, background=True)
        complete(page)
        self.assertIs(page.plot_host, host)
        self.assertEqual(page.plot_widgets, widgets)
        np.testing.assert_allclose(widget.getViewBox().viewRange(), zoom)

    def test_swap_and_explicit_export_completion_use_current_full_page(self):
        page = self.page()
        page.draw_plot()
        fit = page.page_fits()[0]
        page.swap_axes(fit)
        page.ensure_export_figure()
        self.assertIsNone(page._batch_state)
        self.assertEqual(len(page.plot_widgets), 12)
        self.assertEqual(page.oriented_fit(fit).x_name, fit.y_name)
        self.assertEqual(page.figure.axes[0].get_xlabel(), fit.y_name)
        self.assertEqual(page.figure.axes[0].get_ylabel(), fit.x_name)
        np.testing.assert_array_equal(page.plot_widgets[0].listDataItems()[0].getData()[0], fit.y)

    def test_close_stops_construction_callbacks(self):
        page = self.page()
        page.draw_plot()
        page._render_timer.stop()
        page._render_next_panels()
        self.assertEqual(page._batch_state['position'], module.RENDER_BATCH_SIZE)
        page.close()
        self.assertFalse(page.background_render_pending)
        with patch.object(page, '_prepare_render_panel', side_effect=AssertionError('Drew after close')):
            QTest.qWait(30)
        self.assertIsNone(page._batch_state)

    def test_deletion_during_construction_does_not_touch_deleted_qobjects(self):
        page = self.page()
        original = module.InteractivePlotWidget
        errors = []
        def create(*args, **kwargs):
            widget = original(*args, **kwargs)
            page.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            return widget
        with patch.object(module, 'InteractivePlotWidget', side_effect=create), \
                patch.object(sys, 'excepthook', side_effect=lambda *args: errors.append(args)):
            page.draw_plot()
            QTest.qWait(30)
        self.assertTrue(sip.isdeleted(page))
        self.assertEqual(errors, [])

    def test_source_pair_colours_legends_and_nan_cleanup_remain_exact(self):
        page = self.page()
        frame = page.frame.copy()
        frame.loc[5, 'P0'] = np.nan
        selection = dict(page.selection, metrics=list(frame.columns[:4]), sources=(
            {'name': 'Reference', 'rows': tuple(range(90)), 'color': '#ed7d31'},
            {'name': 'Raw Data', 'rows': tuple(range(90, 180)), 'color': '#4472c4'}))
        page.set_input(frame, selection)
        page.selector.selectAll()
        page.draw_plot()
        complete(page)
        self.assertEqual(len(page.all_fits), 28)
        seen = set()
        for panel in page.all_fits:
            seen.add(module.correlation_colors(panel)[0])
        self.assertEqual(seen, {'#ed7d31', module.CORRELATION_POINT_COLOR, '#009e73'})
        for panel, key in zip(page.page_fits(), page._visible_panel_keys):
            cached = page._panel_cache[key]
            self.assertEqual(cached['widget'].getAxis('bottom').labelText, panel.x_name)
            self.assertEqual(cached['widget'].getAxis('left').labelText, panel.y_name)
            for source, (points, line) in zip(panel.sources, cached['items']):
                np.testing.assert_array_equal(points.xData, source.fit.x)
                np.testing.assert_array_equal(points.yData, source.fit.y)
                self.assertEqual(points.opts['symbolBrush'].color().name(), module.correlation_colors(panel)[0])
                np.testing.assert_array_equal(line.yData, source.fit.predicted[np.argsort(source.fit.x)])
            self.assertTrue(cached['widget'].getPlotItem().legend.items)
        self.assertTrue(pd.isna(page.frame.loc[5, 'P0']))

    def test_pending_page_copy_and_all_page_export_finish_complete_current_data(self):
        from PyQt6.QtGui import QImage
        from tempfile import TemporaryDirectory
        from pathlib import Path
        page = self.page()
        page.draw_plot()
        image = QImage(80, 40, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.white)
        with patch.object(module, 'widget_to_qimage', return_value=(image, 1)):
            page.copy_png()
        self.assertEqual(len(page.plot_widgets), 12)
        self.assertIsNone(page._batch_state)
        self.assertEqual(APP.clipboard().image().size(), image.size())
        for key in page._visible_panel_keys:
            self.assertFalse(page._panel_cache[key]['swap_button'].isHidden())
        exported = []
        def save(*args, **kwargs):
            expected = page.page_fits(len(exported))
            axes = page.figure.axes[:len(expected)]
            self.assertEqual(len(axes), len(expected))
            for ax, fit in zip(axes, expected):
                np.testing.assert_array_equal(ax.collections[0].get_offsets(),
                                              np.column_stack((fit.x, fit.y)))
                np.testing.assert_array_equal(ax.lines[0].get_ydata(), fit.predicted[np.argsort(fit.x)])
            exported.append(len(expected))
        with TemporaryDirectory() as folder, \
                patch.object(module.QFileDialog, 'getSaveFileName', return_value=(str(Path(folder) / 'all.png'), '')), \
                patch.object(page.figure, 'savefig', side_effect=save):
            page.export_all_pages()
        self.assertEqual(exported, [12, 3])

    def test_workbook_dense_paste_undo_redo_while_many_panels_are_pending(self):
        from benchmarks.benchmark_memory_storage import fixture, settle
        from metrology_app.matching_window import MatchingWindow
        book = fixture(200, 56)
        parent = MatchingWindow()
        self.addCleanup(self.close_window, parent)
        parent.match_type.setCurrentText('NOVA')
        parent.set_reference_frame(book.reference)
        parent.set_raw_frame(book.raw)
        parent._populate_mappings(book.mappings)
        parent.run_analysis()
        child = parent.open_correlation_workspace()
        self.addCleanup(self.close_window, child)
        child.set_reference_table(pd.DataFrame())
        settle(APP, [parent, child])
        child._set_checked_values(child.wafer_list, [
            child.wafer_list.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
            for i in range(child.wafer_list.topLevelItemCount())])
        child._set_checked_values(child.parameter_list, [f'P{i}' for i in range(50)])
        child.update_plan()
        page = child.correlation_page
        page.selector.selectAll()
        page.start_draw()
        self.assertIsNotNone(page._batch_state)
        changed = book.raw.iloc[:, 6:].map(lambda value: f'{float(value) + .125:.15f}')
        actions = []
        def paste():
            self.assertTrue(parent.raw_model._paste_value_matrix(changed.values.tolist(), 1, 6))
            actions.append('V')
        QTimer.singleShot(0, paste)
        QTimer.singleShot(10, lambda: (parent.raw_model.undo.undo(), actions.append('Z')))
        QTimer.singleShot(20, lambda: (parent.raw_model.undo.redo(), actions.append('Y')))
        from time import monotonic
        deadline = monotonic() + 12
        while len(actions) < 3 or parent.linked_updates_pending or page.background_render_pending:
            if monotonic() > deadline:
                self.fail('Workbook refresh did not finish')
            QTest.qWait(5)
        settle(APP, [parent, child])
        complete(page)
        self.assertEqual(actions, ['V', 'Z', 'Y'])
        pd.testing.assert_frame_equal(child.raw_model.document_frame(), parent.raw_model.document_frame())
        self.assertEqual(len(page.all_fits), 1225)
        oracle, errors = module.source_pairwise_linear_fits(
            page.frame, page.drawn_metrics, page.selection['sources'], page.row_groups(), page.drawn_cells)
        self.assertEqual(errors, [])
        self.assertEqual(len(oracle), len(page.all_fits))
        for actual, expected in zip(page.all_fits, oracle):
            self.assertEqual(actual.parameter_keys, expected.parameter_keys)
            for source, reference in zip(actual.sources, expected.sources):
                np.testing.assert_array_equal(source.fit.x, reference.fit.x)
                np.testing.assert_array_equal(source.fit.y, reference.fit.y)
                np.testing.assert_array_equal(source.fit.predicted, reference.fit.predicted)

    @staticmethod
    def close_window(window):
        window.document.force_close = True
        window.close()
        window.deleteLater()
        APP.processEvents()
