"""Selection history and portable point selection never edit checks or samples."""
import json
import unittest
from dataclasses import replace

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtTest import QTest
from metrology_app.sme_spectra import LoadResult
from metrology_app.spectra_map import SpectraMapWindow
from metrology_app.spectra_viewer import SpectraViewerWindow
from tests.test_spectra_viewer import APP, make_spectrum


class DieMapSelectionTests(unittest.TestCase):
    def viewer(self, sources=None):
        viewer = SpectraViewerWindow()
        viewer.document.force_close = True
        self.addCleanup(viewer.deleteLater)
        self.addCleanup(viewer.close)
        if sources is None:
            sources = tuple(make_spectrum(i) for i in (1, 2, 3))
        viewer.apply_load_result(LoadResult(sources, ()), replace=True)
        viewer.check_all_spectra()
        mapping = viewer.open_wafer_map()
        QTest.qWait(40)
        return viewer, mapping, sources

    def test_ctrl_box_adds_dies_and_wheel_keeps_the_full_wafer_in_view(self):
        sources = tuple(replace(make_spectrum(die), x_mm=x) for die, x in enumerate((-20., 0., 20.), 1))
        viewer, mapping, _ = self.viewer(sources)
        plot = next(iter(mapping.wafer_plots.values())).plot
        view = plot.getViewBox()

        def box(source, modifier):
            start, end = [plot.mapFromScene(view.mapViewToScene(QPointF(source.x_mm + offset, offset)))
                          for offset in (-5, 5)]
            QTest.mousePress(plot.viewport(), Qt.MouseButton.LeftButton, modifier, pos=start)
            QTest.mouseMove(plot.viewport(), end, delay=15)
            QTest.mouseRelease(plot.viewport(), Qt.MouseButton.LeftButton, modifier, pos=end)
            APP.processEvents()

        box(sources[0], Qt.KeyboardModifier.NoModifier)
        self.assertEqual(viewer._selected_keys, {sources[0].key})
        original_range = view.viewRange()
        box(sources[1], Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(viewer._selected_keys, {sources[0].key, sources[1].key})
        self.assertEqual(view.viewRange(), original_range)

        center = plot.mapFromScene(view.mapViewToScene(QPointF(0, 0)))
        for modifier in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ControlModifier):
            wheel = QWheelEvent(QPointF(center), QPointF(plot.viewport().mapToGlobal(center)),
                                QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton, modifier,
                                Qt.ScrollPhase.NoScrollPhase, False)
            APP.sendEvent(plot.viewport(), wheel)
            self.assertEqual(view.viewRange(), original_range)

    def test_buttons_and_shortcuts_undo_redo_point_selection_without_document_edits(self):
        viewer, mapping, sources = self.viewer()
        checked, edits = set(viewer._checked_keys), viewer.edit_history.count()
        first, second = sources[0].key, sources[1].key
        mapping._points_selected({first}, Qt.KeyboardModifier.NoModifier)
        mapping._points_selected({second}, Qt.KeyboardModifier.ControlModifier)
        mapping.undo_selection_button.click()
        self.assertEqual(viewer._selected_keys, {first})
        mapping.redo_selection_button.click()
        self.assertEqual(viewer._selected_keys, {first, second})
        mapping.activateWindow()
        plot = next(iter(mapping.wafer_plots.values())).plot
        plot.setFocus()
        QTest.qWait(10)
        QTest.keyClick(plot, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(viewer._selected_keys, {first})
        QTest.keyClick(plot, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(viewer._selected_keys, {first, second})
        mapping._points_selected(set(), Qt.KeyboardModifier.NoModifier)
        mapping.undo_selection_button.click()
        self.assertEqual(viewer._selected_keys, {first, second})
        self.assertEqual(viewer._checked_keys, checked)
        self.assertEqual(viewer.edit_history.count(), edits)
        viewer.set_test_flags({first: 1})
        for _ in range(mapping.selection_history.count() + 1):
            mapping.undo_selection_shortcut_action.trigger()
        self.assertFalse(viewer._selected_keys)
        self.assertEqual(viewer.test_flags, {first: 1})
        mapping.redo_selection_shortcut_action.trigger()
        self.assertEqual(viewer._selected_keys, {first})
        self.assertEqual(viewer.test_flags, {first: 1})

    def test_read_only_outlier_map_copies_identity_selection_to_all_sme_members(self):
        from metrology_app.bias_die_map import DieMapPoint
        viewer, target, sources = self.viewer()
        duplicate = replace(sources[1], key='second-channel-same-die')
        viewer.apply_load_result(LoadResult((*sources, duplicate), ()), replace=True)
        viewer.check_all_spectra()
        origin = SpectraMapWindow(read_only=True)
        self.addCleanup(origin.close)
        points = tuple(DieMapPoint(f'row-{i}', s.identity, s.x_mm, s.y_mm)
                       for i, s in enumerate(sources))
        origin.set_data(points, checked_keys={'row-1', 'row-2'})
        origin.update_participation({'row-0', 'row-1'})
        QTest.qWait(40)
        origin.select_out_of_range_button.click()
        self.assertEqual(origin._selected_keys, {'row-1'})
        origin.copy_select_button.click()
        payload = APP.clipboard().text()
        self.assertNotIn('row-1', payload)
        self.assertNotIn('checked', payload)
        target.paste_select_button.click()
        self.assertEqual(viewer._selected_keys, {sources[1].key, duplicate.key})
        before = set(viewer._checked_keys)
        target.undo_selection_button.click()
        self.assertFalse(viewer._selected_keys)
        self.assertEqual(viewer._checked_keys, before)

    def test_invalid_or_unmatched_paste_does_not_clear_selection_and_empty_script_can_clear(self):
        viewer, mapping, sources = self.viewer()
        first = sources[0].key
        mapping._points_selected({first}, Qt.KeyboardModifier.NoModifier)
        mapping.copy_select_button.click()
        saved = APP.clipboard().text()
        for text in ('not JSON', saved.replace('W1', 'UNKNOWN_WAFER')):
            APP.clipboard().setText(text)
            mapping.paste_select_button.click()
            self.assertEqual(viewer._selected_keys, {first})
        mapping._points_selected(set(), Qt.KeyboardModifier.NoModifier)
        mapping.copy_select_button.click()
        empty = APP.clipboard().text()
        self.assertEqual(json.loads(empty)['records'], [])
        mapping._points_selected({first}, Qt.KeyboardModifier.NoModifier)
        APP.clipboard().setText(empty)
        mapping.paste_select_button.click()
        self.assertFalse(viewer._selected_keys)

    def test_history_survives_pagination_but_new_source_data_resets_it(self):
        _, mapping, sources = self.viewer()
        mapping._points_selected({sources[0].key}, Qt.KeyboardModifier.NoModifier)
        mapping._change_page_size(1)
        self.assertTrue(mapping.undo_selection_button.isEnabled())
        mapping.set_data((make_spectrum(5),), checked_keys=set())
        self.assertFalse(mapping.undo_selection_button.isEnabled())
        self.assertFalse(mapping.redo_selection_button.isEnabled())
