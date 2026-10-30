"""Small source tables still defer expensive linked graphical refreshes."""
from time import monotonic
from threading import Event
import unittest
from unittest.mock import patch

import pandas as pd
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from metrology_app.matching import ParameterMapping
from metrology_app.matching_window import MatchingWindow
from tests.test_wafer_static import map_fixture

APP = QApplication.instance() or QApplication([])


class SmallSourceGraphicsTests(unittest.TestCase):
    def setUp(self):
        self.parent = MatchingWindow()
        self.addCleanup(self.close, self.parent)
        frame, self.selection = map_fixture(2, 5)
        self.frame = frame
        self.assertLess(frame.size, 8192)
        self.parent.match_type.setCurrentText('NOVA')
        self.parent.set_reference_frame(pd.DataFrame({'P0 Reference': pd.to_numeric(frame.P0) * 1.02 + .3}))
        self.parent.set_raw_frame(frame)
        self.parent._populate_mappings([ParameterMapping('P0', 'P0 Reference', 'P0')])
        self.parent.run_analysis()

    @staticmethod
    def close(window):
        window.document.force_close = True
        window.close()
        window.deleteLater()
        APP.processEvents()

    def finish(self, child):
        deadline = monotonic() + 15
        while True:
            pending = self.parent.linked_updates_pending or self.parent._auto_run_pending
            pending |= self.parent._raw_keyboard_timer.isActive()
            pending |= child.refresh_timer.isActive()
            for name in ('plot_page', 'correlation_page', 'sequence_page'):
                page = getattr(child, name, None)
                pending |= bool(getattr(page, 'background_render_pending', False))
                pending |= any(getattr(page, timer, None) is not None
                               and getattr(page, timer).isActive()
                               for timer in ('input_refresh_timer', 'update_timer'))
            if not pending:
                break
            self.assertLess(monotonic(), deadline, 'Linked source and graphics did not complete')
            QTest.qWait(5)

    def correlation(self, size):
        child = self.parent.open_correlation_workspace()
        self.addCleanup(self.close, child)
        child.set_reference_table(pd.DataFrame())
        self.finish(child)
        child._set_checked_values(child.parameter_list, self.selection['metrics'])
        child.update_plan()
        self.finish(child)
        page = child.correlation_page
        page.min_rsq.setValue(0)
        page.page_size.setCurrentText(str(size))
        page.selector.selectAll()
        page.start_draw()
        self.finish(child)
        self.assertEqual(len(page.plot_widgets), min(size, 10), page.status.text())
        return child

    def update(self, child, *, deferred):
        column = self.parent.raw_model.document_frame().columns.get_loc('P0')
        with patch.object(self.parent, 'sync_stage_windows', wraps=self.parent.sync_stage_windows) as sync, \
                patch.object(self.parent._linked_task, 'submit', wraps=self.parent._linked_task.submit) as submit:
            self.parent.raw_model.edit({(1, column): '12.00000000000001'})
            self.finish(child)
            if deferred:
                sync.assert_not_called()
                self.assertGreater(submit.call_count, 0)
            else:
                self.assertGreater(sync.call_count, 0)
                submit.assert_not_called()
        return column

    def test_many_correlation_panels_use_existing_async_source_commit(self):
        child = self.correlation(12)
        self.update(child, deferred=True)
        pd.testing.assert_frame_equal(child.raw_model.document_frame(), self.parent.raw_model.document_frame())
        self.assertEqual(len(child.correlation_page.plot_widgets), 10)

    def test_light_correlation_retains_small_source_shortcut(self):
        child = self.correlation(6)
        self.update(child, deferred=False)
        pd.testing.assert_frame_equal(child.raw_model.document_frame(), self.parent.raw_model.document_frame())

    def test_many_maps_defer_without_changing_source_selection(self):
        child = self.parent.open_stage_workspace('preview')
        self.addCleanup(self.close, child)
        child._set_checked_values(child.parameter_list, self.selection['metrics'])
        child.update_plan()
        page = child.plot_page
        page.selector.selectAll()
        page.draw_maps()
        self.finish(child)
        self.assertEqual(page.map_grid.valid_count, 10)
        choices = page.draw_state()
        self.update(child, deferred=True)
        self.assertEqual(page.draw_state(), choices)
        self.assertEqual(page.map_grid.valid_count, 10)
        self.assertEqual(page.frame['P0'].iloc[0], '12.00000000000001')

    def test_independent_heavy_child_keeps_its_owned_input(self):
        child = self.correlation(12)
        child.copy_from_wkb_action.setChecked(False)
        original = child.raw_model.document_frame().copy(deep=True)
        self.update(child, deferred=False)
        pd.testing.assert_frame_equal(child.raw_model.document_frame(), original)

    def test_rapid_edit_undo_redo_on_heavy_page_commits_latest_literal_version(self):
        child = self.correlation(12)
        column = self.parent.raw_model.document_frame().columns.get_loc('P0')
        self.parent.raw_model.edit({(1, column): '12.00000000000001'})
        self.parent.raw_model.undo.undo()
        self.parent.raw_model.undo.redo()
        expected = self.parent.raw_model.document_frame().copy(deep=True)
        self.finish(child)
        pd.testing.assert_frame_equal(child.raw_model.document_frame(), expected)
        self.assertEqual(child.raw_model.document_frame().P0.iloc[0], '12.00000000000001')

    def test_undo_redo_to_published_map_version_releases_pending_without_false_dirty(self):
        child = self.parent.open_stage_workspace('preview')
        self.addCleanup(self.close, child)
        child._set_checked_values(child.parameter_list, self.selection['metrics'])
        child.update_plan()
        page = child.plot_page
        page.selector.selectAll()
        page.draw_maps()
        self.finish(child)
        previous = page.result
        self.assertFalse(page.dirty)
        self.parent._set_child_refresh_pending(child, True)
        self.assertFalse(page.dirty, 'Pausing a clean picture cannot make identical sources stale')
        with self.assertRaisesRegex(ValueError, 'finish'):
            page.png_bytes()
        self.parent._set_child_refresh_pending(child, False)
        self.assertTrue(page._export_ready())
        column = self.parent.raw_model.document_frame().columns.get_loc('P0')
        self.parent.raw_model.edit({(1, column): '12.00000000000001'})
        self.finish(child)
        published = page.result
        self.assertIsNot(published, previous)
        self.parent.raw_model.undo.undo()
        self.parent.raw_model.undo.redo()
        self.finish(child)
        self.assertIs(page.result, published)
        self.assertFalse(page.dirty)
        self.assertFalse(child._source_refresh_pending)
        self.assertTrue(page._export_ready())
        self.assertTrue(page.copy_button.isEnabled())

    def test_unchanged_source_commit_resumes_an_interrupted_latest_map_job(self):
        from metrology_app.plot_page import prepare_array
        child = self.parent.open_stage_workspace('preview')
        self.addCleanup(self.close, child)
        child._set_checked_values(child.parameter_list, self.selection['metrics'])
        child.update_plan()
        page = child.plot_page
        page.selector.selectAll()
        page.draw_maps()
        self.finish(child)
        entered, release = Event(), Event()
        self.addCleanup(release.set)
        def blocked(*args, **kwargs):
            entered.set()
            release.wait(5)
            return prepare_array(*args, **kwargs)
        with patch('metrology_app.plot_page.prepare_array', side_effect=blocked):
            column = self.parent.raw_model.document_frame().columns.get_loc('P0')
            self.parent.raw_model.edit({(1, column): '12.00000000000001'})
            deadline = monotonic() + 8
            while not entered.is_set() or self.parent.linked_updates_pending:
                self.assertLess(monotonic(), deadline)
                QTest.qWait(5)
            self.parent.raw_model.undo.undo()
            self.parent.raw_model.undo.redo()
            QTest.qWait(250)
            release.set()
            self.finish(child)
        self.assertFalse(page.dirty, page.status.text())
        self.assertEqual(page.frame['P0'].iloc[0], '12.00000000000001')
        self.assertEqual(page.result['scenes'][0]['layer'].value.iloc[0], 12.00000000000001)
