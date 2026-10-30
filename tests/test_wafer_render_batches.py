"""Dense map pages yield while retaining one complete published result."""
import threading
import gc
import weakref
from copy import deepcopy
from time import monotonic
import unittest
from unittest.mock import patch

import numpy as np
from PyQt6 import sip
from PyQt6.QtCore import QTimer, QCoreApplication, QEvent, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from metrology_app import wafer_graphics
from metrology_app.array_plot import ArrayOptions, prepare_array
from metrology_app.plot_page import PlotPage
from tests.test_wafer_static import map_fixture


APP = QApplication.instance() or QApplication([])


class WaferRenderBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame, cls.selection = map_fixture(2, 5)
        cls.small = prepare_array(cls.frame, dict(cls.selection, wafers=['W0'], metrics=['P0', 'P1']),
                                  ArrayOptions('X mm', 'Y mm'))
        changed = cls.frame.copy(deep=True)
        for name in cls.selection['metrics']:
            changed[name] = changed[name].astype(float) + np.linspace(0, .9, len(changed))**2
        cls.large = prepare_array(changed, cls.selection, ArrayOptions('X mm', 'Y mm'))

    def page(self):
        page = PlotPage()
        self.addCleanup(APP.processEvents)
        def cleanup():
            if not sip.isdeleted(page):
                page.close()
                page.deleteLater()
        self.addCleanup(cleanup)
        page.resize(1100, 800)
        page.show()
        page.render_result(deepcopy(self.small))
        self.finish(page)
        return page

    def finish(self, page):
        deadline = monotonic() + 8
        while page.background_render_pending:
            self.assertLess(monotonic(), deadline, page.status.text())
            QTest.qWait(2)
        APP.processEvents()

    def test_large_page_yields_between_batches_and_publishes_one_complete_grid(self):
        frame, selection = map_fixture(2, 5)
        old = prepare_array(frame, dict(selection, wafers=['W0'], metrics=['P0', 'P1']),
                            ArrayOptions('X mm', 'Y mm'))
        changed = frame.copy(deep=True)
        for name in selection['metrics']:
            changed[name] = changed[name].astype(float) + np.linspace(0, .9, len(changed))**2
        result = prepare_array(changed, selection, ArrayOptions('X mm', 'Y mm'))
        page = PlotPage()
        self.addCleanup(APP.processEvents)
        self.addCleanup(page.deleteLater)
        self.addCleanup(page.close)
        self.addCleanup(page.stop)
        page.resize(1100, 800)
        page.show()
        page.render_result(old)
        deadline = monotonic() + 8
        while len(page.map_grid.panels) != 2:
            self.assertLess(monotonic(), deadline, 'Initial complete map page did not publish')
            QTest.qWait(5)
        APP.processEvents()
        previous = tuple(id(panel) for panel in page.map_grid.panels)
        previous_images = [panel.image.image.copy() for panel in page.map_grid.panels]
        observations, built, between = [], [], []
        owner_thread = threading.get_ident()
        original = wafer_graphics.WaferPanel.__init__

        def create(panel, *args, **kwargs):
            self.assertEqual(threading.get_ident(), owner_thread)
            original(panel, *args, **kwargs)
            built.append(panel)
            if len(built) == 2:
                QTimer.singleShot(0, lambda: between.append(len(built)))

        def observe():
            current = tuple(id(panel) for panel in page.map_grid.panels)
            intact = (current != previous or all(
                np.array_equal(panel.image.image, image)
                for panel, image in zip(page.map_grid.panels, previous_images)))
            observations.append((len(current), intact))

        heartbeat = QTimer(interval=1)
        heartbeat.timeout.connect(observe)
        heartbeat.start()
        try:
            with patch.object(wafer_graphics.WaferPanel, '__init__', create):
                page.render_result(result)
                self.assertLessEqual(len(built), 2,
                                     'All map panels were constructed in one GUI callback')
                self.assertEqual(tuple(id(panel) for panel in page.map_grid.panels), previous)
                self.assertIs(page.result, old, 'Pending maps were marked as the published result')
                deadline = monotonic() + 8
                while len(page.map_grid.panels) != 10:
                    self.assertLess(monotonic(), deadline, 'Complete replacement map page did not publish')
                    QTest.qWait(5)
                APP.processEvents()
        finally:
            heartbeat.stop()
        self.assertGreater(len(built), 2, 'The fixture did not exercise multiple creation batches')
        self.assertIn(2, between, 'Qt could not process events between map construction batches')
        self.assertTrue(observations)
        self.assertTrue(all(count in (2, 10) and intact for count, intact in observations), observations)
        self.assertIs(page.result, result)
        self.assertEqual(len(page.map_grid.panels), 10)
        for panel, scene in zip(page.map_grid.panels, result['scenes']):
            self.assertIs(panel.source, scene)
            np.testing.assert_array_equal(panel.positions, scene['surface'][0])

    def test_latest_data_cancels_unpublished_panels_without_losing_last_update(self):
        page = self.page()
        abandoned, latest = deepcopy(self.large), deepcopy(self.large)
        latest['scenes'][0]['metric'] = 'Latest exact source'
        page.render_result(abandoned)
        QTest.qWait(8)
        page.render_result(latest)
        self.finish(page)
        self.assertIs(page.result, latest)
        self.assertEqual(page.map_grid.panels[0].source['metric'], 'Latest exact source')
        self.assertGreater(page.map_grid.render_stats['cancelled'], 0)
        self.assertEqual(len(page.scene.items()), 21)
        for panel, scene in zip(page.map_grid.panels, latest['scenes']):
            np.testing.assert_array_equal(panel.values, scene['layer'].value.to_numpy(float))
            np.testing.assert_array_equal(panel.image.image, panel.rgba[::-1])

    def test_creation_failure_retains_old_picture_as_stale_and_retry_succeeds(self):
        page = self.page()
        previous = page.result
        panels = tuple(page.map_grid.panels)
        original = wafer_graphics.WaferPanel.__init__
        count = 0
        def failing(panel, *args, **kwargs):
            nonlocal count
            count += 1
            original(panel, *args, **kwargs)
            if count == 3:
                raise RuntimeError('QA candidate failure')
        with patch.object(wafer_graphics.WaferPanel, '__init__', failing):
            page.render_result(deepcopy(self.large))
            self.finish(page)
        self.assertIs(page.result, previous)
        self.assertEqual(tuple(page.map_grid.panels), panels)
        self.assertTrue(page.dirty)
        self.assertFalse(page.export_button.isEnabled())
        with self.assertRaisesRegex(ValueError, 'finish'):
            page.png_bytes()
        page.render_result(deepcopy(self.large))
        self.finish(page)
        self.assertFalse(page.dirty)
        self.assertEqual(page.map_grid.valid_count, 10)

    def test_close_and_delete_cancel_all_queued_graphics_and_page_callbacks(self):
        for delete in (False, True):
            with self.subTest(delete=delete):
                page = self.page()
                built = []
                original = wafer_graphics.WaferPanel.__init__
                def create(panel, *args, **kwargs):
                    original(panel, *args, **kwargs)
                    built.append(panel)
                with patch.object(wafer_graphics.WaferPanel, '__init__', create), \
                        patch.object(page, '_start_surface_job') as start:
                    page.render_result(deepcopy(self.large))
                    QTest.qWait(8)
                    page._page_refresh_timer.start()
                    page.close()
                    before = len(built)
                    if delete:
                        sip.delete(page)
                    QTest.qWait(35)
                    self.assertEqual(len(built), before)
                    start.assert_not_called()
                    if not delete:
                        self.assertFalse(page.background_render_pending)

    def test_latest_style_is_atomic_and_reuses_exact_numerical_surfaces(self):
        page = self.page()
        previous = page.result
        result = deepcopy(self.large)
        page.render_result(result)
        page.opacity.setCurrentIndex(page.opacity.findData(70))
        page.contour.setChecked(True)
        page.point_outline.setChecked(True)
        page.labels.setChecked(False)
        page.font_size.setCurrentText('12')
        page.set_identity_labels({'pad': False, 'lot': False})
        self.assertIs(page.result, previous)
        self.assertEqual(previous['settings'].opacity, 1.)
        self.finish(page)
        self.assertFalse(page.dirty)
        self.assertTrue(page.result['settings'].contour)
        self.assertEqual(page.result['settings'].opacity, .7)
        self.assertFalse(page.result['settings'].labels)
        for panel, original in zip(page.map_grid.panels, result['scenes']):
            self.assertIs(panel.source['surface'], original['surface'])
            self.assertEqual(panel.font_size, 12)
            self.assertEqual(panel.image.opacity(), .7)
            self.assertEqual(panel.identity_labels, {'pad': False, 'lot': False})
        self.assertFalse(result['settings'].contour)

    def test_stale_revision_never_enables_old_export_or_publishes_candidate(self):
        page = self.page()
        previous = page.result
        page.render_result(deepcopy(self.large))
        page.revision += 1
        self.finish(page)
        self.assertIs(page.result, previous)
        self.assertTrue(page.dirty)
        self.assertFalse(page.copy_button.isEnabled())
        with self.assertRaisesRegex(ValueError, 'finish'):
            _ = page.artists

    def test_select_maps_during_preparation_keeps_current_page_choice(self):
        page = self.page()
        page.render_result(deepcopy(self.large))
        page.show_selector()
        self.finish(page)
        self.assertEqual(page.page_intent, 'selector')
        self.assertIs(page.stack.currentWidget(), page.selector_panel)
        self.assertEqual(page.map_grid.valid_count, 10)

    def test_queued_pagination_is_pending_and_close_releases_graphics_not_choices(self):
        page = self.page()
        page.drawn_cells = {('W0', 'P0'), ('W0', 'P1')}
        choices = page.draw_state()
        page._page_refresh_timer.start()
        self.assertTrue(page.background_render_pending)
        self.assertFalse(page._export_ready())
        page.close()
        self.assertFalse(page.background_render_pending)
        self.assertEqual(page.map_grid.panels, [])
        self.assertIsNone(page.result)
        self.assertEqual(page.draw_state(), choices)

    def test_repeated_replacements_release_retired_panels_after_deferred_deletion(self):
        page = self.page()
        retired = []
        for index in range(6):
            retired.extend(weakref.ref(panel) for panel in page.map_grid.panels)
            page.render_result(deepcopy(self.large if index % 2 == 0 else self.small))
            self.finish(page)
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        gc.collect()  # Resource check only, outside every performance measurement.
        self.assertTrue(all(reference() is None for reference in retired))
        self.assertFalse(any(isinstance(child, wafer_graphics._PendingWaferLayer)
                             for child in page.map_grid.children()))
        self.assertEqual(len(page.scene.items()), 5)
        page.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertEqual(len(page.scene.items()), 1)

    def test_initial_surface_completion_keeps_canvas_intent_through_next_data_update(self):
        page = self.page()
        page.result = None
        page.set_input(self.frame, self.selection)
        page.selector.selectAll()
        with patch('metrology_app.plot_page.prepare_array', return_value=deepcopy(self.large)):
            page.draw_maps()
            self.finish(page)
            self.assertEqual(page.page_intent, 'canvas')
            self.assertIs(page.stack.currentWidget(), page.scroll)
            page.set_input(self.frame.copy(deep=True), self.selection)
            self.finish(page)
            self.assertEqual(page.page_intent, 'canvas')
            self.assertIs(page.stack.currentWidget(), page.scroll)

    def test_pending_graphics_are_excluded_from_live_capture_and_saved_draw_completes(self):
        from metrology_app.window import MainWindow
        from metrology_app.analysis_export import capture_window, capture_saved_window
        from metrology_app.matching import MatchWorkbook, ParameterMapping
        window = MainWindow()
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        window.document.force_close = True
        window.plot_page.render_result(deepcopy(self.large))
        with self.assertRaisesRegex(ValueError, 'finish'):
            capture_window(window)
        self.finish(window.plot_page)
        window.set_table(self.frame.copy(), 'Owned QA data')
        window.recognize()
        window._set_checked_values(window.wafer_list, [window.wafer_list.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                                                      for i in range(window.wafer_list.topLevelItemCount())])
        window._set_checked_values(window.parameter_list, self.selection['metrics'])
        window.update_plan()
        window.plot_page.selector.selectAll()
        with patch('metrology_app.plot_page.prepare_array', return_value=deepcopy(self.large)):
            window.plot_page.draw_maps()
            self.finish(window.plot_page)
            saved = {'ui': window.workspace_snapshot().states['ui']}
            report = capture_saved_window('map', self.frame.copy(), scope='preview.map',
                saved=saved, selection=self.selection,
                workbook=MatchWorkbook(reference=self.frame[['P0']].rename(columns={'P0':'P0 Reference'}),
                    raw=self.frame.copy(), mappings=[ParameterMapping('P0', 'P0 Reference', 'P0')], match_type='NOVA'),
                parameters=self.selection['metrics'])
        self.assertIn('Wafer Map', [name for name, _png, _note in report['pictures']])

    def test_overlay_finishing_after_source_pause_restores_current_export_controls(self):
        from metrology_app.window import MainWindow
        from metrology_app.matching_window import MatchingWindow
        window = MainWindow()
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        window.document.force_close = True
        page = window.plot_page
        page.render_result(deepcopy(self.small))
        self.finish(page)
        MatchingWindow._set_child_refresh_pending(window, True)
        # Another window can change this application-wide preference while
        # this source's plots are temporarily disabled.
        page.sync_point_precision(3)
        self.assertTrue(page.overlay_timer.isActive())
        MatchingWindow._set_child_refresh_pending(window, False)
        self.assertFalse(page.copy_button.isEnabled())
        self.finish(page)
        self.assertFalse(page.dirty)
        self.assertTrue(page.copy_button.isEnabled())
        self.assertTrue(page.export_button.isEnabled())
        self.assertTrue(page._export_ready())
