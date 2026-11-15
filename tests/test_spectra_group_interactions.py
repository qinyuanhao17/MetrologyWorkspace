"""Group identity, shared flags and plot-local spectrum actions."""
import unittest

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from metrology_app.sme_spectra import LoadResult
from tests.test_spectra_viewer import APP, make_spectrum


class SpectraGroupInteractionTests(unittest.TestCase):
    def test_click_point_then_enter_multi_digit_flag_and_reject_invalid_prefix(self):
        from PyQt6.QtCore import QPointF
        viewer, sources = self.viewer()
        viewer.apply_load_result(LoadResult(sources[:1],()),replace=True)
        viewer.test_flag_values = [0,1,-1,12,-12]
        window = viewer.open_wafer_map()
        APP.processEvents()
        plot = next(iter(window.wafer_plots.values())).plot
        scene = plot.getViewBox().mapViewToScene(QPointF(sources[0].x_mm,sources[0].y_mm))
        QTest.mouseClick(plot.viewport(),Qt.MouseButton.LeftButton,pos=plot.mapFromScene(scene))
        self.assertEqual(viewer._selected_keys,{sources[0].key})
        QTest.keyClicks(plot,'12')
        QTest.keyClick(plot,Qt.Key.Key_Return)
        self.assertEqual(viewer.test_flags,{sources[0].key:12})
        QTest.keyClicks(plot,'191')
        QTest.keyClick(plot,Qt.Key.Key_Return)
        self.assertEqual(viewer.test_flags,{sources[0].key:12})
        QTest.keyClicks(plot,'-12')
        QTest.keyClick(plot,Qt.Key.Key_Return)
        self.assertEqual(viewer.test_flags,{sources[0].key:-12})
        QTest.keyClicks(plot,'0')
        QTest.qWait(750)
        self.assertEqual(viewer.test_flags,{})
        QTest.keyClicks(plot,'1')
        viewer.select_spectrum_keys(set())
        QTest.qWait(750)
        self.assertEqual(viewer.test_flags,{})
        self.assertEqual(viewer.test_flag_values,[0,1,-1,12,-12])

    def test_color_by_folder_and_flag_groups_sources_and_survives_save_restore(self):
        from dataclasses import replace
        from pathlib import Path
        import numpy as np
        viewer, _ = self.viewer()
        sources = (make_spectrum(1), make_spectrum(2,wafer='W2'),
                   replace(make_spectrum(3),path=Path('C:/other/fixtures/W1.sme'),key='other'))
        viewer.apply_load_result(LoadResult(sources,()),replace=True)
        viewer.check_all_spectra()
        self.assertGreaterEqual(viewer.color_by_combo.findData('folder'),0)
        self.assertGreaterEqual(viewer.color_by_combo.findData('testflag'),0)
        viewer.set_color_mode('folder')
        panel = viewer.plot_panels['S']
        self.assertEqual(sorted(len(g.segments) for g in panel.groups),[1,2])
        self.assertTrue(all('Folder:' in g.key.legend_label for g in panel.groups))
        viewer.set_test_flags({sources[0].key:1,sources[1].key:1})
        viewer.set_color_mode('testflag')
        self.assertEqual(sorted(len(g.segments) for g in panel.groups),[1,2])
        self.assertTrue(any('TestFlag: 0' in g.key.legend_label for g in panel.groups))
        window = viewer.open_plot_window(panel)
        viewer.set_test_flags({sources[1].key:-1})
        self.assertEqual(len(panel.groups),3)
        self.assertEqual(len(window.panel.groups),3)
        for group in panel.groups:
            for segment in group.segments:
                np.testing.assert_array_equal(segment.y,[.7,.8,.9])
        viewer.undo_action.trigger()
        self.assertEqual(len(panel.groups),2)
        draft = viewer.workspace_snapshot()
        viewer.set_color_mode('wafer')
        viewer.restore_workspace(draft)
        self.assertEqual(viewer.color_mode,'testflag')
        self.assertEqual(len(panel.groups),2)
        viewer.set_analysis_mode('3sigma')
        self.assertEqual(viewer.color_mode,'wafer')
        viewer.set_analysis_mode('original')
        self.assertEqual(viewer.color_mode,'testflag')

    def test_tree_and_map_share_actions_and_flag_entry_obeys_configured_values(self):
        viewer, sources = self.viewer()
        viewer.select_spectrum_keys({sources[0].key})
        window = viewer.open_wafer_map()
        APP.processEvents()
        tree = viewer.build_tree_menu()
        menu = window.build_selection_menu(('W1','L1','P1'))
        labels = lambda m:{a.text() for a in m.actions() if not a.isSeparator()}
        self.assertEqual(labels(tree), labels(menu))
        self.assertTrue({'Set Test Flag','Set Mark','Highlight','Set as BSL',
                         'Check Unselected','Apply Flag to Similar Wafer'} <= labels(menu))
        next(a for a in menu.actions() if a.text() == 'Highlight').trigger()
        self.assertEqual(viewer.highlighted_keys, {sources[0].key})
        plot = next(iter(window.wafer_plots.values())).plot
        QTest.keyClicks(plot, '1')
        QTest.keyClick(plot, Qt.Key.Key_Return)
        self.assertEqual(viewer.test_flags, {sources[0].key:1})
        QTest.keyClicks(plot, '9')
        QTest.keyClick(plot, Qt.Key.Key_Return)
        self.assertEqual(viewer.test_flags, {sources[0].key:1})
        QTest.keyClicks(plot, '-1')
        QTest.keyClick(plot, Qt.Key.Key_Return)
        self.assertEqual(viewer.test_flags, {sources[0].key:-1})
        viewer.undo_action.trigger()
        self.assertEqual(viewer.test_flags, {sources[0].key:1})
        QTest.keyClicks(window.page_size_spin, '2')
        self.assertEqual(viewer.test_flags, {sources[0].key:1})

    def viewer(self):
        from metrology_app.spectra_viewer import SpectraViewerWindow
        viewer = SpectraViewerWindow()
        viewer.document.force_close = True
        self.addCleanup(viewer.deleteLater)
        self.addCleanup(viewer.close)
        sources = (make_spectrum(1), make_spectrum(2))
        viewer.apply_load_result(LoadResult(sources, ()), replace=True)
        viewer.check_all_spectra()
        return viewer, sources

    def test_default_marks_append_replace_and_undo(self):
        viewer, sources = self.viewer()
        options = viewer.group_options
        self.assertEqual([s['name'] for s in options.saved['definition']['mark_values']],
                         ['POR', 'POR+', 'POR-'])
        keys = {sources[0].key}
        options.add_named_mark(keys, 'Old', append=False)
        options.add_named_mark(keys, 'POR', append=True)
        self.assertEqual(options.labels()[sources[0].key]['mark'], 'Old/POR')
        self.assertIn('Old/POR', [s['name'] for s in options.saved['definition']['mark_values']])
        viewer.undo_action.trigger()
        self.assertEqual(options.labels()[sources[0].key]['mark'], 'Old')
        viewer.redo_action.trigger()
        options.add_named_mark(keys, 'POR', append=False)
        self.assertEqual(options.labels()[sources[0].key]['mark'], 'POR')
        self.assertEqual(options.labels()[sources[1].key]['mark'], 'POR')

    def test_group_details_flags_are_shared_with_info_and_undo(self):
        viewer, sources = self.viewer()
        options = viewer.group_options
        viewer.set_test_flags({sources[0].key: 1})
        options.open_settings()
        model = options.details_model
        self.assertEqual(model.data(model.index(0, 0)), 'W1')
        self.assertEqual(model.data(model.index(0, 4)), '1')
        self.assertTrue(model.setData(model.index(1, 4), '-1', Qt.ItemDataRole.EditRole))
        options.controls.apply_button.click()
        self.assertEqual(viewer.test_flags, {sources[0].key: 1, sources[1].key: -1})
        viewer.set_test_flags({sources[0].key: -1})
        self.assertEqual(model.data(model.index(0, 4)), '-1')
        viewer.undo_action.trigger()
        self.assertEqual(model.data(model.index(0, 4)), '1')

    def test_highlight_survives_selection_clear_and_restore_without_curve_rebuild(self):
        viewer, sources = self.viewer()
        panel = viewer.plot_panels['S']
        items = tuple(panel._curve_items)
        bounds = panel.plot.getViewBox().viewRange()
        viewer.select_spectrum_keys({sources[0].key})
        action = next(a for a in viewer.build_tree_menu().actions() if a.text() == 'Highlight')
        action.trigger()
        viewer.select_spectrum_keys(set())
        self.assertEqual(viewer.highlighted_keys, {sources[0].key})
        self.assertTrue(panel._emphasis_items)
        self.assertEqual(panel._emphasis_items[0].opts['pen'].color().name(), '#ee3377')
        self.assertEqual(tuple(panel._curve_items), items)
        self.assertEqual(panel.plot.getViewBox().viewRange(), bounds)
        draft = viewer.workspace_snapshot()
        viewer.restore_workspace(draft)
        self.assertEqual(viewer.highlighted_keys, {sources[0].key})
        viewer.apply_load_result(LoadResult(sources,()),replace=True)
        viewer.check_all_spectra()
        self.assertFalse(viewer.highlighted_keys)
        self.assertFalse(panel._emphasis_items)

    def test_highlight_hidden_channels_and_batched_sme_colours_preserve_samples(self):
        viewer, sources = self.viewer()
        from metrology_app.spectra_plots import CurveGroup, CurveSegment
        from PyQt6.QtGui import QColor
        import numpy as np
        panel = viewer.plot_panels['psi_delta']
        groups = [CurveGroup(i,QColor('#0077bb'),(CurveSegment(str(i),np.arange(4.),np.arange(4.)+i),))
                  for i in range(40)]
        panel.set_curves(groups,secondary=groups)
        originals = tuple(panel._curve_items)
        panel.set_emphasized_keys({'2'})
        self.assertEqual(len(panel._emphasis_items),2)
        panel.set_hidden_keys({2})
        self.assertFalse(panel._emphasis_items)
        panel.set_hidden_keys(set())
        self.assertEqual(tuple(panel._curve_items),originals)
        self.assertEqual(len(panel._emphasis_items),2)
        panel.set_emphasized_keys(set())
        self.assertFalse(panel._emphasis_items)

    def test_u_unchecks_selected_curve_in_main_and_floating_plot(self):
        viewer, sources = self.viewer()
        viewer.resize(1000, 700)
        viewer.show()
        panel = viewer.plot_panels['S']
        viewer.select_spectrum_keys({sources[0].key})
        panel.plot.setFocus()
        QTest.keyClick(panel.plot, Qt.Key.Key_U)
        self.assertNotIn(sources[0], viewer.checked_spectra())
        viewer.check_all_spectra()
        window = viewer.open_plot_window(panel)
        viewer.select_spectrum_keys({sources[1].key})
        QTest.keyClick(window.panel.plot, Qt.Key.Key_U)
        self.assertNotIn(sources[1], viewer.checked_spectra())
        viewer.check_all_spectra()
        from PyQt6.QtWidgets import QLineEdit
        editor = QLineEdit(viewer)
        QTest.keyClick(editor,Qt.Key.Key_U)
        self.assertEqual(editor.text(),'u')
        self.assertEqual(viewer.checked_spectra(),sources)


if __name__ == '__main__':
    unittest.main()
