"""Report projection edits and Test Flags share reversible Viewer state."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from metrology_app.sme_spectra import LoadResult
from metrology_app.spectra_viewer import SpectraViewerWindow
from tests import test_spectra_info as fixtures


class SpectraInfoEditTests(unittest.TestCase):
    def viewer(self):
        viewer = SpectraViewerWindow()
        viewer.document.force_close = True
        self.addCleanup(viewer.close)
        self.addCleanup(viewer.deleteLater)
        raw, sources = fixtures.SpectraInfoTests().sources()
        viewer.apply_load_result(LoadResult(sources, ()), replace=True)
        viewer.set_spectra_info_source(lambda:(raw, pd.DataFrame({'Depth':['8.1','9.2']})))
        viewer.check_all_spectra()
        return viewer, raw, sources

    def test_delete_column_shifts_report_and_exports_without_changing_source(self):
        viewer, raw, sources = self.viewer()
        before = raw.copy(deep=True)
        info = viewer.open_spectra_info()
        original = info.table_frame()
        menu = info.build_column_menu(0, original.columns.get_loc('Lot ID'))
        next(a for a in menu.actions() if a.text() == 'Delete Column').trigger()
        expected = original.drop(columns='Lot ID')
        pd.testing.assert_frame_equal(info.table_frame(), expected)
        self.assertEqual(info.models[0].frame.columns[1], 'Tool SN')
        self.assertIn('Lot ID', info.models[1].frame)
        info.copy_table()
        self.assertNotIn('Lot ID', fixtures.APP.clipboard().text().splitlines()[0].split('\t'))
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'info.csv'
            info.export_csv(path)
            self.assertEqual(pd.read_csv(path).columns.tolist(), expected.columns.tolist())
        info.undo_action.trigger()
        pd.testing.assert_frame_equal(info.table_frame(), original)
        info.redo_action.trigger()
        pd.testing.assert_frame_equal(info.table_frame(), expected)
        pd.testing.assert_frame_equal(raw, before)
        self.assertEqual(viewer.checked_spectra(), sources)

    def test_edit_report_flag_updates_matching_die_in_place_with_shared_undo_redo(self):
        viewer, raw, sources = self.viewer()
        maps = viewer.open_wafer_map()
        QTest.qWait(100)
        plot = next(iter(maps.wafer_plots.values()))
        plot.grab()
        limits = plot.plot.getViewBox().viewRange()
        scatter, markers = plot.scatter, plot.flag_markers
        checks = viewer.checked_spectra()
        info = viewer.open_spectra_info()
        info.tabs.setCurrentIndex(1)
        model = info.models[1]
        index = model.index(0, model.frame.columns.get_loc('Test Flag'))
        self.assertTrue(model.flags(index) & Qt.ItemFlag.ItemIsEditable)
        self.assertFalse(model.flags(model.index(0, 0)) & Qt.ItemFlag.ItemIsEditable)
        self.assertTrue(model.setData(index, '-1'))
        # Raw row 0 is Die 2, whereas catalogue row 0 is Die 1.
        self.assertEqual(viewer.test_flags, {sources[1].key:-1})
        self.assertEqual(len(markers.points()), 1)
        self.assertEqual(markers.points()[0].brush().color().name(), '#dc2626')
        self.assertEqual(info.table_frame()['Test Flag'].tolist(), [-1, 0])
        for invalid in ('1.5', 'bad', '', True):
            index = model.index(0, model.frame.columns.get_loc('Test Flag'))
            self.assertFalse(model.setData(index, invalid))
            self.assertEqual(viewer.test_flags, {sources[1].key:-1})
        info.undo_action.trigger()
        self.assertEqual(viewer.test_flags, {})
        self.assertEqual(len(markers.points()), 0)
        maps.redo_action.trigger()
        self.assertEqual(viewer.test_flags, {sources[1].key:-1})
        self.assertIs(next(iter(maps.wafer_plots.values())), plot)
        self.assertIs(plot.scatter, scatter)
        self.assertIs(plot.flag_markers, markers)
        self.assertEqual(plot.plot.getViewBox().viewRange(), limits)
        self.assertEqual(viewer.checked_spectra(), checks)

    def test_keyboard_shortcuts_and_saved_report_projection(self):
        viewer, raw, sources = self.viewer()
        info = viewer.open_spectra_info()
        original = info.table_frame()
        info.column_picker.accept()
        info.build_column_menu(0, original.columns.get_loc('Lot ID')).actions()[0].trigger()
        info.activateWindow()
        info.tables[0].setFocus()
        QTest.qWait(20)
        QTest.keyClick(info.tables[0], Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertIn('Lot ID', info.table_frame())
        QTest.keyClick(info.tables[0], Qt.Key.Key_Z,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        self.assertNotIn('Lot ID', info.table_frame())
        viewer.set_test_flags({sources[0].key:1})
        maps = viewer.open_wafer_map()
        maps.activateWindow()
        maps.setFocus()
        QTest.qWait(20)
        QTest.keyClick(maps, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(viewer.test_flags, {})
        QTest.keyClick(maps, Qt.Key.Key_Z,
                       Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(viewer.test_flags, {sources[0].key:1})
        with TemporaryDirectory() as directory:
            saved = viewer.save_spec(Path(directory) / 'report.spec')
            restored = SpectraViewerWindow()
            restored.document.force_close = True
            self.addCleanup(restored.close)
            self.addCleanup(restored.deleteLater)
            restored.load_workspace(saved)
            reopened = restored.open_spectra_info()
            self.assertNotIn('Lot ID', reopened.table_frame())
            self.assertIn('Lot ID', reopened.models[1].frame)
            self.assertEqual(restored.test_flags, {sources[0].key:1})
            self.assertFalse(restored.undo_action.isEnabled())

    def test_first_column_picker_and_restored_columns_follow_workbook_edits(self):
        from PyQt6.QtWidgets import QTabWidget
        from metrology_app.matching_window import MatchingWindow
        owner = MatchingWindow()
        owner.document.force_close = True
        self.addCleanup(owner.close)
        raw, sources = fixtures.SpectraInfoTests().sources()
        owner.set_raw_frame(raw)
        owner.set_reference_frame(pd.DataFrame({'Depth': ['8.1', '9.2'], 'Width': ['10.1', '11.2']}))
        viewer = owner.open_spectra_workspace()
        viewer.apply_load_result(LoadResult(sources, ()), replace=True)
        viewer.check_all_spectra()
        info = viewer.open_spectra_info()
        picker = info.column_picker
        self.assertTrue(picker.isVisible())
        choices = picker.findChild(QTabWidget).widget(0)
        depth = next(choices.item(i) for i in range(choices.count()) if choices.item(i).text() == 'Depth')
        depth.setCheckState(Qt.CheckState.Unchecked)
        picker.accept()
        self.assertNotIn('Depth', info.models[0].frame)
        self.assertIn('Depth', info.models[1].frame)
        self.assertIsNone(viewer.open_spectra_info().column_picker)

        owner.reference_model.edit({(1, 0): '42.125', (1, 1): '99.125'})
        QTest.qWait(30)
        self.assertNotIn('Depth', info.models[0].frame)
        self.assertEqual(info.models[0].frame.Width.iloc[0], '99.125')
        menu = info.build_column_menu(0, -1)
        restore = next(action.menu() for action in menu.actions() if action.text() == 'Restore Columns')
        next(action for action in restore.actions() if action.text() == 'Depth').trigger()
        self.assertEqual(info.models[0].frame.Depth.iloc[0], '42.125')
        owner.reference_model.edit({(1, 0): '72.250'})
        QTest.qWait(30)
        self.assertEqual(info.models[0].frame.Depth.iloc[0], '72.250')

    def test_all_tabs_share_raw_and_default_order_and_flag_edit_refreshes_both_directions(self):
        viewer, raw, sources = self.viewer()
        info = viewer.open_spectra_info()
        for model in info.models:
            self.assertEqual(model.frame['Die Seq'].tolist(), [2,1])
        viewer.set_spectra_info_source(lambda:(pd.DataFrame(), pd.DataFrame()))
        info.refresh()
        for model in info.models:
            self.assertEqual(model.frame['Die Seq'].tolist(), [1,2])
        viewer.set_test_flags({sources[0].key:1})
        info.tabs.setCurrentIndex(1)
        self.assertEqual(info.table_frame()['Test Flag'].tolist(), [1,0])
        model = info.models[1]
        self.assertTrue(model.setData(model.index(0, model.frame.columns.get_loc('Test Flag')), '0'))
        self.assertEqual(viewer.test_flags, {})
        self.assertEqual(info.table_frame()['Test Flag'].tolist(), [0,0])
