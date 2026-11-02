"""Generation, source ownership and native input during linked refresh."""
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import numpy as np

from PyQt6.QtCore import QTimer, Qt, QCoreApplication, QEvent
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtTest import QTest, QSignalSpy
from PyQt6.QtWidgets import QApplication, QWidget, QGraphicsScene

from metrology_app.background_task import LatestTask
from metrology_app.sheet import SheetModel, prepare_sheet_frame
from metrology_app.matching_window import MatchingWindow
from metrology_app.sequence_page import SequencePage
from metrology_app.correlation_page import CorrelationPage, pairwise_linear_fits
from metrology_app.radius_graphics import RadiusGrid
from tests import test_workbook_copy_data as copy_fixtures

APP = QApplication.instance() or QApplication([])


def wait_until(predicate, milliseconds=5000):
    from time import monotonic
    deadline = monotonic() + milliseconds / 1000
    while not predicate():
        if monotonic() > deadline:
            raise AssertionError('Background refresh did not finish')
        QTest.qWait(5)


class LatestTaskTests(unittest.TestCase):
    def setUp(self):
        self.owner = QWidget()
        self.addCleanup(self.owner.deleteLater)
        self.release = threading.Event()
        self.entered = threading.Event()
        self.published, self.errors, self.started = [], [], []
        self.main_thread = threading.get_ident()

        def work(value, cancelled):
            self.assertNotEqual(threading.get_ident(), self.main_thread)
            self.started.append(value)
            if value == 1:
                self.entered.set()
                self.release.wait(3)
            return value

        self.task = LatestTask(work, self.published.append, self.errors.append, self.owner)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.release.set()
        if not self.task.closed:
            self.task.cancel()
            wait_until(lambda: not self.task.busy)
            self.task.close()
        APP.processEvents()

    def test_blocked_old_work_does_not_block_gui_and_only_latest_publishes(self):
        self.task.submit(1)
        wait_until(self.entered.is_set)
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(threading.get_ident()))
        self.task.submit(2)
        self.task.submit(3)
        QTest.qWait(20)
        self.assertEqual(ticks, [self.main_thread])
        self.assertEqual(self.published, [])
        self.release.set()
        wait_until(lambda: not self.task.busy)
        self.assertEqual(self.started, [1, 3])
        self.assertEqual(self.published, [3])
        self.assertEqual(self.errors, [])

    def test_cancel_rejects_even_a_completed_queued_result(self):
        self.task.submit(1)
        wait_until(self.entered.is_set)
        self.task.cancel()
        self.release.set()
        wait_until(lambda: not self.task.busy)
        self.assertEqual(self.published, [])

    def test_close_does_not_wait_for_library_call_or_publish_later(self):
        self.task.submit(1)
        wait_until(self.entered.is_set)
        self.task.close()
        self.assertFalse(self.task.busy)
        self.release.set()
        QTest.qWait(30)
        self.assertEqual(self.published, [])


class PreparedSheetTests(unittest.TestCase):
    def test_background_cells_match_normal_load_including_precision_and_blanks(self):
        frames = [pd.DataFrame(),
                  pd.DataFrame([['W', '01', '1.000000000001'], ['', '', ''], ['W', '01', '']],
                               columns=['Wafer ID', 'Die Seq', 'CD']),
                  pd.DataFrame([['', '1', ''], ['', '', '']], columns=['', 'same', 'same']),
                  pd.DataFrame({'a': [1, None, -0.0], 'b': ['0001', '1e-15', ' ']})]
        for frame in frames:
            with self.subTest(columns=list(frame)):
                literal = frame.copy(deep=True)
                normal, prepared = SheetModel(), SheetModel()
                self.addCleanup(normal.deleteLater)
                self.addCleanup(prepared.deleteLater)
                normal.load(frame)
                prepared._linked_prepared_load = prepare_sheet_frame(frame)
                prepared.load(frame)
                self.assertEqual(prepared.snapshot(), normal.snapshot())
                pd.testing.assert_frame_equal(prepared.document_frame(), normal.document_frame())
                if not normal.duplicate_header_count():
                    pd.testing.assert_frame_equal(prepared.frame(), normal.frame())
                self.assertEqual(prepared.document_shape(), normal.document_shape())
                self.assertEqual(prepared.undo.count(), 0)
                self.assertTrue(prepared.undo.isClean())
                pd.testing.assert_frame_equal(frame, literal)

    def test_worker_metadata_caches_cannot_reorder_or_retain_gui_entries(self):
        from metrology_app import measurements, match_groups
        frame = pd.DataFrame({'Wafer ID': ['main']*3, 'Die Seq': ['1', '2', '3'], 'CD': ['1', '2', '3']})
        measurements.detect_measurements(frame, 'Wafer ID')
        match_groups.row_ids(frame)
        before_measurements = [id(entry) for entry in measurements._MEASUREMENT_CACHE]
        before_rows = [id(entry) for entry in match_groups._ROW_IDS_CACHE]
        failures = []
        def work():
            try:
                other = frame.assign(**{'Wafer ID': ['worker']*3})
                self.assertEqual(measurements.detect_measurements(other, 'Wafer ID')[0].wafer, 'worker')
                self.assertNotEqual(match_groups.row_ids(other), match_groups.row_ids(frame))
            except Exception as error:
                failures.append(error)
        worker = threading.Thread(target=work)
        worker.start()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual([id(entry) for entry in measurements._MEASUREMENT_CACHE], before_measurements)
        self.assertEqual([id(entry) for entry in match_groups._ROW_IDS_CACHE], before_rows)

    def test_mismatched_prepared_frame_cannot_replace_current_load_or_undo(self):
        model = SheetModel()
        self.addCleanup(model.deleteLater)
        model._linked_prepared_load = prepare_sheet_frame(pd.DataFrame({'CD': ['old']}))
        model.load(pd.DataFrame({'CD': ['new']}))
        self.assertEqual(model.document_frame().iloc[0, 0], 'new')
        model.edit({(1, 0): 'newest'})
        model.undo.undo()
        self.assertEqual(model.document_frame().iloc[0, 0], 'new')


class LinkedSourceRefreshTests(unittest.TestCase):
    def setUp(self):
        from metrology_app.linked_refresh import prepare_linked_sources
        self.release = threading.Event()
        self.entered = threading.Event()
        self.main_thread = threading.get_ident()
        self.threads = []

        def delayed(request, cancelled):
            self.threads.append(threading.get_ident())
            self.entered.set()
            self.release.wait(20)
            return prepare_linked_sources(request, cancelled)

        with patch('metrology_app.linked_refresh.prepare_linked_sources', new=delayed):
            self.parent = MatchingWindow()
        reference, raw, _ = copy_fixtures.WorkbookCopyDataTests.sources()
        for number in range(24):
            raw[f'P{number}'] = [f'{number + i}.000000000001' for i in range(4)]
        raw = pd.concat([raw]*2500, ignore_index=True)
        reference = pd.concat([reference]*2500, ignore_index=True)
        self.assertEqual(raw.shape, (10000, 30))
        self.parent.match_type.setCurrentText('NOVA')
        self.parent.set_reference_frame(reference)
        self.parent.set_raw_frame(raw)
        self.parent.run_analysis()
        self.child = self.parent.open_correlation_workspace()
        self.child.set_reference_table(reference)
        self.column = self.parent.raw_model.source_headers().index('CD')
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.release.set()
        copy_fixtures.WorkbookCopyDataTests.close_window(self.parent)
        QTest.qWait(30)

    def start(self, value='1.10000000000001'):
        self.parent.raw_model.edit({(1, self.column): value})
        wait_until(self.entered.is_set)
        self.assertTrue(self.parent.linked_updates_pending)
        self.assertTrue(all(thread != self.main_thread for thread in self.threads))

    def finish(self):
        self.release.set()
        wait_until(lambda: not self.parent.linked_updates_pending)

    def test_latest_edit_and_undo_redo_win_while_gui_keeps_processing(self):
        self.start()
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        self.parent.raw_model.edit({(1, self.column): '1.20000000000001'})
        self.parent.raw_model.undo.undo()
        self.parent.raw_model.undo.redo()
        QTest.qWait(30)
        self.assertEqual(ticks, [True])
        self.finish()
        self.assertEqual(self.child.raw_model.document_frame().iloc[0]['CD'], '1.20000000000001')
        pd.testing.assert_frame_equal(self.child.raw_model.document_frame(), self.parent.raw_model.document_frame())

    def test_child_manual_edit_is_never_overwritten_by_a_prepared_result(self):
        self.start()
        column = self.child.raw_model.source_headers().index('CD')
        self.child.raw_model.edit({(1, column): '99.000000000001'})
        self.finish()
        self.assertEqual(self.child.raw_model.document_frame().iloc[0]['CD'], '99.000000000001')
        self.assertFalse(self.child.copy_from_wkb_action.isChecked())

    def test_closed_child_cannot_receive_prepared_sources(self):
        self.start()
        self.child.document.force_close = True
        self.child.close()
        self.child.deleteLater()
        self.finish()
        self.assertNotIn(self.child, self.parent._stage_windows)

    def test_save_during_pending_preparation_captures_current_source(self):
        from metrology_app.workspace_store import load_workspace
        self.start()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'owned.wkb'
            path = self.parent.save_workbook(path)
            self.assertIsNotNone(path)
            saved = load_workspace(path)
            self.assertEqual(saved.frames['raw'].iloc[0]['CD'], '1.10000000000001')
            self.assertEqual(self.child.raw_model.document_frame().iloc[0]['CD'], '1.10000000000001')
        self.finish()
        self.assertEqual(self.child.raw_model.document_frame().iloc[0]['CD'], '1.10000000000001')

    def test_stage_change_supersedes_inflight_preview_preparation(self):
        self.start()
        final = self.parent.raw_model.document_frame().copy(deep=True)
        final.loc[0, 'CD'] = '9.123000000001'
        self.parent.result_mode.setCurrentText('Final')
        self.parent.set_raw_frame(final)
        self.parent.run_analysis()
        self.finish()
        self.assertEqual(self.child.raw_model.document_frame().iloc[0]['CD'], '9.123000000001')

    def test_group_change_supersedes_inflight_original_order(self):
        self.start()
        self.parent.group_controls.restore({'enabled': True, 'mark_enabled': False, 'trend_order': 'groups'},
            pd.DataFrame({'TestFlag': ['1']*5000+['2']*5000}))
        self.parent.run_analysis()
        self.finish()
        self.assertTrue(self.child._group_plan.enabled)
        self.assertEqual(self.child._group_plan.row_groups, self.parent.result.group_plan.row_groups)

    def test_linked_update_does_not_flash_the_data_tab(self):
        self.child.tabs.setCurrentWidget(self.child.sequence_page)
        changes = QSignalSpy(self.child.tabs.currentChanged)
        self.start()
        self.finish()
        self.assertEqual(len(changes), 0, 'Refreshing a background source temporarily showed the full table')
        self.assertIs(self.child.tabs.currentWidget(), self.child.sequence_page)

    def test_edit_then_immediate_undo_releases_the_current_source_and_plots(self):
        before = self.child.raw_model.document_frame().copy(deep=True)
        self.parent.raw_model.edit({(1, self.column): '1.600000000001'})
        self.parent.raw_model.undo.undo()
        self.release.set()
        wait_until(lambda: not getattr(self.child, '_source_refresh_pending', False))
        self.finish()
        pd.testing.assert_frame_equal(self.child.raw_model.document_frame(), before)
        self.assertTrue(self.child.sequence_page.isEnabled())

    def test_capture_before_first_queued_refresh_uses_current_workbook_input(self):
        from metrology_app.analysis_export import capture_window
        self.parent.raw_model.edit({(1, self.column): '1.500000000001'})
        report = capture_window(self.child)
        self.assertEqual(report['frames']['Raw Data'].iloc[0]['CD'], '1.500000000001')
        self.release.set()

    def test_invalid_stage_cancels_the_previous_generation_without_publishing(self):
        self.start()
        before = self.child.raw_model.document_frame().copy(deep=True)
        previous_generation = self.parent._linked_generation
        published = []
        publish = self.parent._linked_task.publish
        self.parent._linked_task.publish = lambda result: (published.append(result["generation"]), publish(result))
        self.parent.result_mode.setCurrentText('Final')
        self.assertGreater(self.parent._linked_generation, previous_generation)
        self.finish()
        self.assertNotIn(previous_generation, published)
        pd.testing.assert_frame_equal(self.child.raw_model.document_frame(), before)
        self.assertFalse(getattr(self.child, '_source_refresh_pending', False))
        self.assertTrue(self.child.sequence_page.isEnabled())

    def test_recovery_during_pending_refresh_keeps_latest_link_and_manual_reference(self):
        self.check_recovery_during_pending_refresh(manual_raw=False)

    def test_recovery_during_pending_refresh_keeps_independent_raw_draft(self):
        self.check_recovery_during_pending_refresh(manual_raw=True)

    def check_recovery_during_pending_refresh(self, *, manual_raw):
        self.start()
        reference = self.child.reference_model.document_frame().copy(deep=True)
        if manual_raw:
            column = self.child.raw_model.source_headers().index('CD')
            self.child.raw_model.edit({(1, column): '7.000000000001'})
        with tempfile.TemporaryDirectory() as folder:
            self.parent.document.recovery_path = Path(folder)/'owned-recovery.mwkb'
            self.parent.document.write_recovery()
            self.assertTrue(self.parent.document.recovery_path.exists(), self.parent.document.last_warning)
            restored = MatchingWindow()
            self.addCleanup(copy_fixtures.WorkbookCopyDataTests.close_window, restored)
            restored.document.recover(self.parent.document.recovery_path)
            child = restored.open_correlation_workspace()
            expected = '7.000000000001' if manual_raw else '1.10000000000001'
            self.assertEqual(child.raw_model.document_frame().iloc[0]['CD'], expected)
            pd.testing.assert_frame_equal(child.reference_model.document_frame(), reference)
        self.finish()


class SourcePauseTests(unittest.TestCase):
    def test_pending_source_cannot_publish_old_map_or_export_after_style_change(self):
        from metrology_app.window import MainWindow
        child = MainWindow()
        self.addCleanup(copy_fixtures.WorkbookCopyDataTests.close_window, child)
        page = child.plot_page
        revision = page.revision
        page.input_refresh_timer.start(1000)
        MatchingWindow._set_child_refresh_pending(child, True)
        self.assertGreater(page.revision, revision)
        self.assertFalse(page.input_refresh_timer.isActive())
        page.copy_button.setEnabled(True)  # A previously queued style callback.
        self.assertFalse(page.copy_button.isEnabled())
        self.assertFalse(page.isEnabled())
        MatchingWindow._set_child_refresh_pending(child, False)
        self.assertTrue(page.isEnabled())


class BackgroundPlotTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({'Wafer ID': ['W1']*12,
                                   'Die Seq': [f'{i:03}' for i in range(1, 13)]})
        for i in range(8):
            self.frame[f'P{i}'] = [f'{j*(i+1)+(j%3)*.02:.12f}' for j in range(12)]
        self.frame.loc[4, 'P0'] = ''
        self.metrics = [f'P{i}' for i in range(8)]
        self.selection = dict(wafers=['W1'], metrics=self.metrics,
                              wafer_column='Wafer ID', groups={'W1': tuple(range(12))})
        self.pages = []

    def tearDown(self):
        for page in self.pages:
            page.stop_background_draw()
            page.input_refresh_timer.stop()
            page.close()
            page.deleteLater()
        APP.processEvents()

    def page(self, kind):
        page = kind()
        if isinstance(page, SequencePage):
            page.overlay, page.source_overlay = {}, {}
        page.set_input(self.frame, self.selection)
        page.selector.selectAll()
        self.pages.append(page)
        return page

    def test_correlation_background_matches_full_lmfit_arrays_and_precision(self):
        page = self.page(CorrelationPage)
        page.request_background_draw()
        wait_until(lambda: not page.background_render_pending)
        self.assertTrue(page.ready, page.status.text())
        expected, errors = pairwise_linear_fits(self.frame, self.metrics,
            self.selection['groups'], page.selector.selected_cells())
        self.assertEqual(page.skipped_count, len(errors))
        self.assertEqual(len(page.all_fits), len(expected))
        for actual, fit in zip(page.all_fits, expected):
            for field in ('x', 'y', 'predicted'):
                np.testing.assert_array_equal(getattr(actual, field), getattr(fit, field))
            self.assertEqual((actual.slope, actual.intercept, actual.rsquared),
                             (fit.slope, fit.intercept, fit.rsquared))

    def test_deferred_draw_can_be_finished_or_cancelled_before_submission(self):
        for kind in (CorrelationPage, SequencePage):
            with self.subTest(page=kind.__name__):
                page = self.page(kind)
                page.request_background_draw(deferred=True)
                self.assertTrue(page.background_render_pending)
                page.finish_background_draw()
                self.assertTrue(page.ready, page.status.text())
                page.request_background_draw(deferred=True)
                page.stop_background_draw()
                QTest.qWait(30)
                self.assertFalse(page.background_render_pending)

    def test_two_source_background_keeps_source_pairs_order_and_nan_filtering(self):
        from metrology_app.correlation_page import source_pairwise_linear_fits
        page = self.page(CorrelationPage)
        frame = pd.concat([self.frame, self.frame], ignore_index=True)
        frame.loc[12:, 'P0'] = pd.to_numeric(frame.loc[12:, 'P0'], errors='coerce') + .001
        keys = (('Reference', 'W1'), ('Raw Data', 'W1'))
        sources = tuple({'name': name, 'rows': tuple(range(i*12, (i+1)*12)),
                         'keys': (keys[i],), 'color': color, 'die_column': 'Die Seq'}
                        for i, (name, color) in enumerate((('Reference', '#ed7d31'), ('Raw Data', '#4472c4'))))
        selection = dict(wafers=keys, metrics=self.metrics[:4], wafer_column='Wafer ID', sources=sources, labels={key: ' / '.join(key) for key in keys},
                         groups={key: source['rows'] for key, source in zip(keys, sources)})
        page.set_input(frame, selection)
        page.selector.selectAll()
        page.request_background_draw()
        wait_until(lambda: not page.background_render_pending)
        self.assertTrue(page.ready, page.status.text())
        expected, errors = source_pairwise_linear_fits(frame, selection['metrics'], sources,
            selection['groups'], page.selector.selected_cells())
        self.assertEqual(page.skipped_count, len(errors))
        self.assertEqual(len(page.all_fits), len(expected))
        for actual, oracle in zip(page.all_fits, expected):
            self.assertEqual(actual.parameter_keys, oracle.parameter_keys)
            for entry, reference in zip(actual.sources, oracle.sources):
                self.assertEqual(entry.name, reference.name)
                for field in ('x', 'y', 'predicted'):
                    np.testing.assert_array_equal(getattr(entry.fit, field), getattr(reference.fit, field))
                self.assertEqual((entry.fit.slope, entry.fit.intercept, entry.fit.rsquared),
                                 (reference.fit.slope, reference.fit.intercept, reference.fit.rsquared))

    def test_refreshed_correlation_reuses_qualified_panels_and_swaps_the_current_fit(self):
        page = self.page(CorrelationPage)
        page.draw_plot()
        wait_until(lambda: not page.background_render_pending)
        old = {page.axis_key(fit): widget for fit, widget in zip(page.page_fits(), page.plot_widgets)}
        changed = self.frame.copy(deep=True)
        changed['P0'] = pd.to_numeric(changed['P0'], errors='coerce') + .01
        state = page.draw_state()
        page.set_input(changed, self.selection)
        page.restore_draw_state(state, background=True)
        wait_until(lambda: not page.background_render_pending)
        reused = 0
        for fit, widget in zip(page.page_fits(), page.plot_widgets):
            if page.axis_key(fit) in old:
                self.assertIs(widget, old[page.axis_key(fit)])
                reused += 1
        self.assertGreater(reused, 0)
        fit = page.page_fits()[0]
        cached = page._panel_cache[page._visible_panel_keys[0]]
        cached['swap_button'].click()
        self.assertEqual(page.oriented_fit(fit).x_name, fit.y_name)
        points, line = cached['items'][0]
        x, y = points.getData()
        np.testing.assert_array_equal(x, fit.y)
        np.testing.assert_array_equal(y, fit.x)

    def test_trend_yields_between_panels_and_preserves_full_arrays_and_nan(self):
        page = self.page(SequencePage)
        observations = []
        append = page._append_interactive_panel
        def observe(*args):
            append(*args)
            if len(page.plot_widgets) == 2:
                QTimer.singleShot(0, lambda: observations.append((len(page.plot_widgets), page.ready)))
        with patch.object(page, '_append_interactive_panel', side_effect=observe):
            page.request_background_draw()
            wait_until(lambda: not page.background_render_pending)
        self.assertTrue(page.ready, page.status.text())
        self.assertTrue(observations)
        self.assertLess(observations[0][0], 8)
        self.assertFalse(observations[0][1], 'A partial grid must not be exportable as complete')
        for metric, widget in zip(page.metrics, page.plot_widgets):
            curve, = widget.listDataItems()
            np.testing.assert_array_equal(curve.yData, pd.to_numeric(self.frame[metric], errors='coerce'))
            np.testing.assert_array_equal(curve.xData, np.arange(12))
            self.assertEqual(curve.opts['connect'], 'finite')

    def test_edit_during_trend_batch_rejects_partial_old_grid(self):
        page = self.page(SequencePage)
        state = page.draw_state()
        state['enabled'] = True
        state['cells'] = tuple(page.selector.selected_cells())
        changed = self.frame.copy(deep=True)
        changed.loc[0, 'P0'] = '123.000000000001'
        append = page._append_interactive_panel
        switched = []
        def replacing(*args):
            append(*args)
            if not switched:
                switched.append(True)
                def replace():
                    page.set_input(changed, self.selection)
                    page.restore_draw_state(state, background=True)
                QTimer.singleShot(0, replace)
        with patch.object(page, '_append_interactive_panel', side_effect=replacing):
            page.request_background_draw()
            wait_until(lambda: bool(switched) and not page.background_render_pending)
        self.assertTrue(page.ready, page.status.text())
        self.assertEqual(len(page.plot_widgets), 8)
        self.assertEqual(page.plot_widgets[0].listDataItems()[0].yData[0], 123.000000000001)

    def test_input_invalidation_discards_partial_widget_references(self):
        page = self.page(SequencePage)
        page.request_background_draw()
        wait_until(lambda: bool(getattr(page, '_batch_state', None)) and len(page.plot_widgets) >= 2)
        page.set_input(self.frame.copy(deep=True), self.selection)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertEqual(page.plot_widgets, [])


class RadiusRefreshTests(unittest.TestCase):
    def test_reused_input_container_cannot_hide_a_changed_coordinate_or_value(self):
        scenes = [QGraphicsScene(), QGraphicsScene()]
        grids = [RadiusGrid() for _ in scenes]
        for scene, grid in zip(scenes, grids):
            scene.addItem(grid)
            self.addCleanup(scene.clear)
        source = {'metric': 'CD', 'label': 'W1', 'radius': np.array([-100., -20., 10., 80.]),
                  'value': np.array([1., 2., 3., 4.]), 'die': ['001', '002', '003', '004'],
                  'limit': 150., 'unit': 'mm', 'color': 'C0', 'stats': 'Original'}
        labels = {'pad': True, 'lot': True}
        grids[0].set_result([source], (1, 1), 10, labels)
        source['value'][1] = 2.123000000001
        source['radius'][1] = -19.123000000001
        source['color'] = 'C3'
        for grid in grids:
            grid.set_result([source], (1, 1), 10, labels)
        for coordinate in ('x', 'y'):
            np.testing.assert_array_equal(grids[0].panels[0].scatter.data[coordinate],
                                          grids[1].panels[0].scatter.data[coordinate])
        self.assertEqual(grids[0].panels[0].scatter.opts['brush'].color(),
                         grids[1].panels[0].scatter.opts['brush'].color())

    def test_same_roles_reuse_graphics_with_exactly_the_fresh_render(self):
        scenes = [QGraphicsScene(), QGraphicsScene()]
        grids = [RadiusGrid() for _ in scenes]
        for scene, grid in zip(scenes, grids):
            scene.addItem(grid)
            self.addCleanup(scene.clear)
        source = {'metric': 'CD', 'label': 'W1\nLot L1', 'radius': np.array([-100., -20., 10., 80.]),
                  'value': np.array([1., 2., 3., 4.]), 'die': ['001', '002', '003', '004'],
                  'limit': 150., 'unit': 'mm', 'color': 'C0', 'stats': 'Original'}
        labels = {'pad': True, 'lot': True}
        grids[0].set_result([source], (1, 1), 10, labels)
        panel = grids[0].panels[0]
        scatter = panel.scatter
        changed = {**source, 'color': 'C3', 'value': np.array([1., 9.123000001, 3., 4.]), 'stats': 'Updated'}
        grids[0].set_result([changed], (1, 1), 12, labels)
        grids[1].set_result([changed], (1, 1), 12, labels)
        self.assertIs(grids[0].panels[0], panel)
        self.assertIs(panel.scatter, scatter)
        oracle = grids[1].panels[0]
        self.assertEqual(panel.y_limits, oracle.y_limits)
        np.testing.assert_array_equal(panel._pixel_positions, oracle._pixel_positions)
        images = []
        for scene, grid in zip(scenes, grids):
            scene.setSceneRect(grid.boundingRect())
            image = QImage(460, 450, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.white)
            painter = QPainter(image)
            scene.render(painter)
            painter.end()
            images.append(image.bits().asstring(image.sizeInBytes()))
        self.assertEqual(images[0], images[1], 'Reuse changed the existing plot style or pixels')

    def test_missing_to_populated_source_rebuilds_the_required_graphics(self):
        scene = QGraphicsScene()
        grid = RadiusGrid()
        scene.addItem(grid)
        self.addCleanup(scene.clear)
        grid.set_result([{'skip': True}], (1, 1), 10, {'pad': True, 'lot': True})
        previous = grid.panels[0]
        source = dict(metric='CD', label='W1', radius=np.array([0.]), value=np.array([2.]),
                      die=['001'], limit=150., unit='mm', color='C0', stats='Constant')
        grid.set_result([source], (1, 1), 10, {'pad': True, 'lot': True})
        self.assertIsNot(grid.panels[0], previous)
        self.assertIsNotNone(grid.panels[0].scatter)


if __name__ == '__main__':
    unittest.main()
