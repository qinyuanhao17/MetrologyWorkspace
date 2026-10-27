"""Workbook data remains linked; automatic plots follow the viewed child."""
import tempfile
import threading
from unittest.mock import patch
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt, QMimeData
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from metrology_app.matching_window import MatchingWindow
from tests import test_workbook_copy_data as fixtures

APP = QApplication.instance() or QApplication([])

def wait_for(predicate):
    from time import monotonic
    deadline = monotonic() + 8
    while not predicate():
        if monotonic() >= deadline:
            raise AssertionError('Linked data or viewed plot did not settle')
        QTest.qWait(10)

class ViewedPlotRefreshTests(unittest.TestCase):
    def setUp(self):
        self.parent = MatchingWindow()
        self.addCleanup(fixtures.WorkbookCopyDataTests.close_window, self.parent)
        reference, raw, _ = fixtures.WorkbookCopyDataTests.sources()
        self.parent.match_type.setCurrentText('NOVA')
        self.parent.set_reference_frame(reference)
        self.parent.set_raw_frame(raw)
        self.parent.run_analysis()
        self.child = self.parent.open_correlation_workspace()
        self.child.set_reference_table(reference)
        for tree in (self.child.wafer_list, self.child.parameter_list,
                     self.child.reference_wafer_list, self.child.reference_parameter_list):
            self.child.check_all(tree, True)
        self.page = self.child.sequence_page
        self.page.overlay, self.page.source_overlay = {}, {}
        self.page.selector.selectAll()
        self.page.draw_plot()
        self.column = self.parent.raw_model.source_headers().index('CD')

    def edit(self, value):
        self.parent.raw_model.edit({(1, self.column): value})
        wait_for(lambda: self.child.raw_model.document_frame().iloc[0]['CD'] == value
                 and not getattr(self.child, '_source_refresh_pending', False))

    def view(self):
        self.child.show()
        self.child.tabs.setCurrentWidget(self.page)
        self.child.activateWindow()
        QApplication.setActiveWindow(self.child)
        QTest.qWait(20)

    def test_hidden_child_syncs_data_without_drawing_then_refreshes_on_view(self):
        widgets = list(self.page.plot_widgets)
        arrays = [w.listDataItems()[0].yData.copy() for w in widgets]
        self.child.hide()
        self.edit('1.700000000001')
        QTest.qWait(350)
        self.assertFalse(self.page.ready, 'An unviewed graph was automatically rebuilt')
        self.assertEqual(self.page.plot_widgets, widgets)
        for widget, original in zip(widgets, arrays):
            np.testing.assert_array_equal(widget.listDataItems()[0].yData, original)
        self.view()
        wait_for(lambda: self.page.ready and not self.page.background_render_pending)
        self.assertTrue(any(np.any(w.listDataItems()[0].yData == 1.700000000001)
                            for w in self.page.plot_widgets))

    def test_export_of_unviewed_graph_uses_current_values_without_activation(self):
        from metrology_app.analysis_export import capture_window
        self.child.hide()
        self.edit('1.800000000001')
        self.assertFalse(self.page.ready)
        report = capture_window(self.child)
        self.assertFalse(self.child.isVisible())
        values = [series['data']['Y'].to_numpy(float) for plot in report['plots']
                  if plot['sheet'] == 'Trend' for series in plot['series']]
        self.assertTrue(any(np.any(value == 1.800000000001) for value in values))

    def test_save_keeps_current_data_and_draw_choices_without_drawing_hidden_child(self):
        from metrology_app.workspace_store import load_workspace
        self.child.hide()
        self.edit('1.900000000001')
        with tempfile.TemporaryDirectory() as folder:
            path = self.parent.save_workbook(Path(folder)/'owned.wkb')
            saved = load_workspace(path)
            self.assertEqual(saved.frames['raw'].iloc[0]['CD'], '1.900000000001')
        self.assertTrue(self.page.has_drawn_once)
        self.assertFalse(self.page.ready)

    def test_data_tab_is_not_a_plot_view(self):
        self.child.tabs.setCurrentIndex(0)
        self.child.show()
        QApplication.setActiveWindow(self.child)
        self.edit('2.000000000001')
        QTest.qWait(350)
        self.assertFalse(self.page.ready)
        self.view()
        wait_for(lambda: self.page.ready and not self.page.background_render_pending)

    def floating_raw(self):
        self.parent.raw_floating_editor.detach()
        dialog = self.parent.raw_floating_editor.dialog
        QApplication.setActiveWindow(dialog)
        self.parent.raw_view.setFocus()
        QTest.qWait(20)
        self.assertIs(QApplication.activeWindow(), dialog)
        return dialog

    def test_floating_workbook_raw_paste_and_undo_keep_the_watched_trend_live(self):
        self.view()
        self.assertIs(self.parent._viewed_plot_workspace, self.child)
        self.assertIs(self.page.stack.currentWidget(), self.page.interactive_scroll)
        dialog = self.floating_raw()
        before = self.parent.raw_model.document_frame().copy(deep=True)
        clipboard = APP.clipboard()
        old = {name: bytes(clipboard.mimeData().data(name)) for name in (clipboard.mimeData().formats() if clipboard.mimeData() is not None else ())}
        text = '2.100000000001'
        def restore_clipboard():
            if clipboard.text() == text:
                mime = QMimeData()
                for name, value in old.items():
                    mime.setData(name, value)
                clipboard.setMimeData(mime)
        self.addCleanup(restore_clipboard)
        clipboard.setText(text)
        self.parent.raw_view.setCurrentIndex(self.parent.raw_model.index(1, self.column))
        QTest.keyClick(self.parent.raw_view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        wait_for(lambda: self.child.raw_model.document_frame().iloc[0]['CD'] == text
                 and self.page.ready and not self.page.background_render_pending)
        self.assertIs(QApplication.activeWindow(), dialog)
        self.assertIs(self.page.stack.currentWidget(), self.page.interactive_scroll)
        self.assertTrue(any(np.any(w.listDataItems()[0].yData == float(text)) for w in self.page.plot_widgets))
        QTest.keyClick(self.parent.raw_view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        wait_for(lambda: self.child.raw_model.document_frame().equals(before)
                 and self.page.ready and not self.page.background_render_pending)
        self.assertIs(self.parent._viewed_plot_workspace, self.child)
        self.assertIs(QApplication.activeWindow(), dialog)
        self.assertIs(self.page.stack.currentWidget(), self.page.interactive_scroll)
        pd.testing.assert_frame_equal(self.parent.raw_model.document_frame(), before)

    def test_only_the_last_viewed_child_draws_while_both_sources_update(self):
        reference = self.child.reference_model.document_frame().copy(deep=True)
        scope = 'correlation.' + '0'*32 + '.preview'
        self.parent._workspace_states[scope] = {'window': {'name': 'Correlation and Trend 2', 'checked': True}}
        second = self.parent.open_correlation_workspace(scope=scope)
        second.set_reference_table(reference)
        for tree in (second.wafer_list, second.parameter_list, second.reference_wafer_list, second.reference_parameter_list):
            second.check_all(tree, True)
        page = second.sequence_page
        page.overlay, page.source_overlay = {}, {}
        page.selector.selectAll()
        page.draw_plot()
        second.tabs.setCurrentWidget(page)
        QApplication.setActiveWindow(second)
        QTest.qWait(20)
        self.assertIs(self.parent._viewed_plot_workspace, second)
        self.floating_raw()
        self.edit('2.200000000001')
        wait_for(lambda: page.ready and not page.background_render_pending)
        self.assertEqual(second.raw_model.document_frame().iloc[0]['CD'], '2.200000000001')
        self.assertFalse(self.page.ready)
        self.view()
        wait_for(lambda: self.page.ready and not self.page.background_render_pending)
        self.floating_raw()
        self.edit('2.300000000001')
        wait_for(lambda: self.page.ready and not self.page.background_render_pending)
        self.assertFalse(page.ready)

    def test_minimized_target_waits_for_restore_and_close_forgets_target(self):
        self.view()
        self.child.showMinimized()
        QApplication.setActiveWindow(self.parent)
        self.edit('2.400000000001')
        QTest.qWait(100)
        self.assertFalse(self.page.ready)
        self.child.showNormal()
        self.view()
        wait_for(lambda: self.page.ready and not self.page.background_render_pending)
        self.child.document.force_close = True
        self.child.close()
        self.assertIsNone(getattr(self.parent, '_viewed_plot_workspace', None))

    def test_pending_manual_box_choice_is_never_replaced_by_deferred_draw(self):
        self.child.hide()
        self.edit('2.500000000001')
        cells = self.page.selector.selected_cells()
        chosen = {next(iter(cells))}
        self.page.selector.set_selected_cells(chosen)
        self.view()
        QTest.qWait(150)
        self.assertEqual(self.page.selector.selected_cells(), chosen)
        self.assertTrue(self.page.selector.pending_draw)
        self.assertFalse(self.page.ready)

    def test_immediate_manual_draw_after_activation_supersedes_the_queued_draw(self):
        self.child.hide()
        self.edit('2.600000000001')
        chosen = {next(iter(self.page.selector.selected_cells()))}
        self.child.show()
        self.child.tabs.setCurrentWidget(self.page)
        QApplication.setActiveWindow(self.child)
        self.page.selector.set_selected_cells(chosen)
        self.page.draw_plot()
        self.assertTrue(self.page.ready)
        QTest.qWait(150)
        self.assertEqual(self.page.selector.selected_cells(), chosen)
        self.assertTrue(self.page.ready)

    def test_manual_pending_choice_survives_leaving_a_running_background_draw(self):
        from metrology_app.sequence_data import prepare_sequence_values
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def delayed(request, cancelled):
            entered.set()
            release.wait(10)
            return prepare_sequence_values(request, cancelled)
        self.view()
        self.floating_raw()
        with patch('metrology_app.sequence_data.prepare_sequence_values', new=delayed):
            self.edit('2.700000000001')
            wait_for(entered.is_set)
        chosen = {next(iter(self.page.selector.selected_cells()))}
        self.page.selector.set_selected_cells(chosen)
        self.assertTrue(self.page.selector.pending_draw)
        self.child.hide()
        QTest.qWait(50)
        self.assertTrue(self.page.selector.pending_draw, 'Pausing automatic work accepted a manual choice')
        release.set()
        wait_for(lambda: not self.page.background_render_pending)
        self.view()
        QTest.qWait(50)
        self.assertEqual(self.page.selector.selected_cells(), chosen)
        self.assertTrue(self.page.selector.pending_draw)
        self.assertFalse(self.page.ready)

    def test_rapid_edit_undo_redo_undo_keeps_the_latest_source_and_curves(self):
        self.view()
        self.floating_raw()
        before = self.parent.raw_model.document_frame().copy(deep=True)
        arrays = [w.listDataItems()[0].yData.copy() for w in self.page.plot_widgets]
        count = self.parent.raw_model.undo.count()
        self.parent.raw_model.edit({(1, self.column): '2.800000000001'})
        self.parent.raw_model.undo.undo()
        self.parent.raw_model.undo.redo()
        self.parent.raw_model.undo.undo()
        wait_for(lambda: not getattr(self.child, '_source_refresh_pending', False)
                 and self.page.ready and not self.page.background_render_pending)
        QTest.qWait(100)
        pd.testing.assert_frame_equal(self.parent.raw_model.document_frame(), before)
        pd.testing.assert_frame_equal(self.child.raw_model.document_frame(), before)
        self.assertEqual(self.parent.raw_model.undo.count(), count+1)
        for widget, original in zip(self.page.plot_widgets, arrays):
            np.testing.assert_array_equal(widget.listDataItems()[0].yData, original)

    def test_recovery_of_deferred_plots_keeps_current_source_and_draw_choices(self):
        self.child.hide()
        self.edit('2.900000000001')
        cells = self.page.draw_state()['cells']
        with tempfile.TemporaryDirectory() as folder:
            self.parent.document.recovery_path = Path(folder)/'owned-recovery.mwkb'
            self.parent.document.write_recovery()
            self.assertTrue(self.parent.document.recovery_path.exists())
            restored = MatchingWindow()
            try:
                restored.document.recover(self.parent.document.recovery_path)
                child = restored.open_correlation_workspace()
                self.assertEqual(child.raw_model.document_frame().iloc[0]['CD'], '2.900000000001')
                self.assertTrue(child.sequence_page.has_drawn_once)
                self.assertEqual(child.sequence_page.draw_state()['cells'], cells)
                from metrology_app.analysis_export import capture_window
                report = capture_window(child)
                values = [series['data']['Y'].to_numpy(float) for plot in report['plots']
                          if plot['sheet'] == 'Trend' for series in plot['series']]
                self.assertTrue(any(np.any(value == 2.900000000001) for value in values))
            finally:
                fixtures.WorkbookCopyDataTests.close_window(restored)

    def test_new_workbook_data_does_not_accept_a_pending_manual_draw_choice(self):
        self.view()
        chosen = {next(iter(self.page.selector.selected_cells()))}
        self.page.selector.set_selected_cells(chosen)
        self.floating_raw()
        self.edit('3.000000000001')
        QTest.qWait(100)
        self.assertEqual(self.page.selector.selected_cells(), chosen)
        self.assertTrue(self.page.selector.pending_draw, 'Source refresh accepted an unconfirmed Draw choice')
        self.assertFalse(self.page.ready)
        from metrology_app.analysis_export import capture_window
        with self.assertRaisesRegex(ValueError, 'Draw selected'):
            capture_window(self.child)

    def test_export_materializes_current_data_without_leaving_the_selector_view(self):
        from metrology_app.analysis_export import capture_window
        self.child.hide()
        self.edit('3.200000000001')
        self.page.show_selector()
        self.assertIs(self.page.stack.currentWidget(), self.page.selector_panel)
        report = capture_window(self.child)
        self.assertIs(self.page.stack.currentWidget(), self.page.selector_panel)
        values = [series['data']['Y'].to_numpy(float) for plot in report['plots']
                  if plot['sheet'] == 'Trend' for series in plot['series']]
        self.assertTrue(any(np.any(value == 3.200000000001) for value in values))

    def test_watched_correlation_keeps_its_canvas_while_trend_waits(self):
        page = self.child.correlation_page
        self.child.tabs.setCurrentWidget(page)
        self.child.show()
        QApplication.setActiveWindow(self.child)
        page.selector.selectAll()
        page.start_draw()
        self.assertTrue(page.ready, page.status.text())
        self.assertIs(page.stack.currentWidget(), page.interactive_scroll)
        QTest.qWait(20)
        self.floating_raw()
        self.edit('3.300000000001')
        wait_for(lambda: page.ready and not page.background_render_pending)
        self.assertIs(page.stack.currentWidget(), page.interactive_scroll)
        self.assertFalse(self.page.ready)
        fits = [entry.fit for pair in page.all_fits for entry in pair.sources]
        self.assertTrue(any(np.any(fit.x == 3.300000000001) or np.any(fit.y == 3.300000000001)
                            for fit in fits))

    def test_disabled_saved_draw_discards_deferred_graphs_and_stays_disabled_on_edit(self):
        correlation = self.child.correlation_page
        correlation.selector.selectAll()
        correlation.start_draw()
        self.child.hide()
        self.edit('3.400000000001')
        state = self.child.selection_state()
        state['trend_draw']['enabled'] = False
        state['correlation_draw']['enabled'] = False
        self.child.restore_selection(state)
        QTest.qWait(50)
        for page in (correlation, self.page):
            self.assertFalse(page.has_drawn_once)
            self.assertFalse(page.ready)
            self.assertEqual(page.plot_widgets, [])
            self.assertNotIn(page, self.child.viewed_plots.pending)
            self.assertFalse(page.input_refresh_timer.isActive())
        self.view()
        self.floating_raw()
        self.edit('3.500000000001')
        QTest.qWait(100)
        for page in (correlation, self.page):
            self.assertFalse(page.ready)
            self.assertFalse(page.has_drawn_once)
            self.assertEqual(page.plot_widgets, [])

if __name__ == '__main__':
    unittest.main()
