"""Spectra Group classification is copied by four-field identity and stays local."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from metrology_app.match_groups import group_state, row_ids
from metrology_app.sme_spectra import LoadResult
from tests.test_spectra_viewer import make_spectrum, APP


class SpectraGroupTests(unittest.TestCase):
    def test_invalid_group_drafts_are_rejected_before_replacing_spectra(self):
        from copy import deepcopy
        from metrology_app.spectra_viewer import SpectraViewerWindow
        viewer = SpectraViewerWindow()
        viewer.document.force_close = True
        self.addCleanup(viewer.close)
        sources = (make_spectrum(1),)
        viewer.apply_load_result(LoadResult(sources,()),replace=True)
        viewer.group_options.assign_mark({sources[0].key},'POR+')
        draft = viewer.workspace_snapshot()
        for change in ('definition','mark','flag'):
            bad = deepcopy(draft)
            settings = bad.states['ui']['groups']
            if change == 'definition':
                settings['definition'] = []
            else:
                settings['records'][sources[0].key][change] = [] if change == 'mark' else '1.5'
            with self.assertRaises(ValueError):
                viewer.restore_workspace(bad)
            self.assertEqual(viewer.catalog.spectra,sources)
            self.assertEqual(viewer.group_options.labels()[sources[0].key]['mark'],'POR+')

    def test_local_group_settings_apply_and_master_toggle_preserve_participation(self):
        from metrology_app.spectra_viewer import SpectraViewerWindow
        viewer = SpectraViewerWindow()
        viewer.document.force_close = True
        self.addCleanup(viewer.close)
        self.addCleanup(viewer.deleteLater)
        sources = (make_spectrum(1),make_spectrum(2))
        viewer.apply_load_result(LoadResult(sources,()),replace=True)
        viewer.set_spectrum_checks({sources[0].key:True})
        dialog = viewer.group_options.open_settings()
        controls = viewer.group_options.controls
        controls.enabled.setChecked(True)
        controls.mark_enabled.setChecked(True)
        controls.order_model.load(pd.DataFrame({'TestFlag':['1','-1']}))
        controls.apply_button.click()
        labels = viewer.group_options.labels()
        self.assertEqual({value['mark'] for value in labels.values()},{'POR'})
        self.assertNotEqual(labels[sources[0].key]['group'],labels[sources[1].key]['group'])
        self.assertEqual(viewer.checked_spectra(),(sources[0],))
        self.assertEqual(viewer.test_flags,{sources[0].key:1,sources[1].key:-1})
        self.assertEqual(viewer.tree.topLevelItem(0).text(0),'W1 | POR')
        viewer.group_options.enabled_action.setChecked(False)
        self.assertEqual(viewer.tree.topLevelItem(0).text(0),'W1')
        self.assertEqual(viewer.group_options.labels(),{})
        viewer.group_options.enabled_action.setChecked(True)
        self.assertEqual(viewer.tree.topLevelItem(0).text(0),'W1 | POR')
        dialog.close()

    def test_wkb_group_copy_is_one_time_local_and_persists_with_draggable_legend(self):
        from metrology_app.matching_window import MatchingWindow
        from metrology_app.spectra_viewer import SpectraViewerWindow
        from tests import test_spectra_info as fixtures
        owner = MatchingWindow()
        owner.document.force_close = True
        self.addCleanup(owner.close)
        raw,sources = fixtures.SpectraInfoTests().sources()
        owner.set_reference_frame(pd.DataFrame({'Depth':['8','9']}))
        owner.set_raw_frame(raw)
        state = group_state({'enabled':True,'mark_enabled':True,
                             'head_names':{'0':'GRR','1':'Accuracy','-1':'Offset'}})
        state['mark_rows'] = {'New':[row_ids(raw)[0]]}
        owner.group_controls.restore(state,pd.DataFrame({'TestFlag':[1,0]}))
        owner.group_controls.accept_changes()
        viewer = owner.open_spectra_workspace()
        viewer.apply_load_result(LoadResult(sources,()),replace=True)
        viewer.check_all_spectra()
        self.assertTrue(viewer.group_options.copy_action.isEnabled())
        viewer.group_options.copy_action.trigger()
        labels = viewer.group_options.labels()
        self.assertEqual(labels[sources[1].key]['group'],'New Accuracy')
        self.assertEqual(labels[sources[0].key]['group'],'Old GRR')
        self.assertEqual(viewer.test_flags,{sources[1].key:1})
        self.assertEqual(viewer.checked_spectra(),sources)
        owner.group_controls.state['applied']['mark_values'][1]['name'] = 'Changed in WKB'
        self.assertEqual(viewer.group_options.labels()[sources[1].key]['mark'],'New')
        viewer.resize(1200,800)
        viewer.show()
        APP.processEvents()
        viewer.legend_plot_splitter.setSizes([180,400])
        self.assertGreater(viewer.legends['Mueller'].height(),100)
        self.assertNotEqual(viewer.legend_plot_splitter.sizes()[0], viewer.legend_plot_splitter.sizes()[1])
        with TemporaryDirectory() as directory:
            saved = viewer.save_spec(Path(directory)/'groups.spec')
            restored = SpectraViewerWindow()
            restored.document.force_close = True
            self.addCleanup(restored.close)
            self.addCleanup(restored.deleteLater)
            restored.load_workspace(saved)
            self.assertEqual(restored.group_options.snapshot(),viewer.group_options.snapshot())
            self.assertIn('Old, New',restored.tree.topLevelItem(0).text(0))

    def test_tree_mark_legend_prefix_map_group_and_undo_do_not_rebuild_curves(self):
        from metrology_app.spectra_viewer import SpectraViewerWindow
        viewer = SpectraViewerWindow()
        viewer.document.force_close = True
        self.addCleanup(viewer.close)
        self.addCleanup(viewer.deleteLater)
        sources = (make_spectrum(1),make_spectrum(2),make_spectrum(1,wafer='W2'))
        viewer.apply_load_result(LoadResult(sources,()),replace=True)
        viewer.check_all_spectra()
        viewer.select_spectrum_keys({sources[0].key,sources[1].key})
        panel = viewer.plot_panels['S']
        items = tuple(panel._curve_items)
        ranges = panel.plot.getViewBox().viewRange()
        colors = [group.color.rgba() for group in panel.groups]
        menu = viewer.build_tree_menu()
        marks = next(action.menu() for action in menu.actions() if action.text()=='Set Mark')
        next(action for action in marks.actions() if action.text()=='POR+').trigger()
        self.assertEqual(viewer.tree.topLevelItem(0).text(0),'W1 | POR+')
        legend = viewer.legends['Mueller']
        self.assertTrue(legend.item(0).text().startswith('POR+ | W1'))
        self.assertEqual(tuple(panel._curve_items),items)
        self.assertEqual(panel.plot.getViewBox().viewRange(),ranges)
        self.assertEqual([group.color.rgba() for group in panel.groups],colors)
        self.assertEqual(viewer.checked_spectra(),sources)
        maps = viewer.open_wafer_map()
        QTest.qWait(80)
        plot = maps.wafer_plots[('W1','L1','P1')]
        self.assertIn('Group: POR+',plot.title_label.text())
        viewer.undo_action.trigger()
        self.assertEqual(viewer.tree.topLevelItem(0).text(0),'W1')
        self.assertNotIn('Group:',plot.title_label.text())
        viewer.redo_action.trigger()
        self.assertIn('Group: POR+',plot.title_label.text())

    def test_copy_groups_matches_business_identity_and_rejects_conflicting_duplicates(self):
        from metrology_app.spectra_groups import copied_groups, display_groups
        spectra = (make_spectrum(1), make_spectrum(2), make_spectrum(1, wafer='W2'))
        raw = pd.DataFrame({'Wafer ID':['W1','W1'], 'Lot ID':['L1','L1'], 'PAD Name':['P1','P1'],
                            'Die Seq':['2.0','1'], 'Cur SME File Path':['renamed/b.sme','elsewhere/a.sme']})
        state = group_state({'enabled':True,'mark_enabled':True,
                             'head_names':{'0':'GRR','1':'Accuracy','-1':'Offset'}})
        state['mark_rows'] = {'New':[row_ids(raw)[0]]}
        saved, report = copied_groups(raw, pd.DataFrame({'TestFlag':[1,0]}), state, spectra)
        labels = display_groups(spectra, saved)
        self.assertEqual(labels[spectra[0].key], {'mark':'Old','group':'Old GRR'})
        self.assertEqual(labels[spectra[1].key], {'mark':'New','group':'New Accuracy'})
        self.assertNotIn(spectra[2].key, labels)
        self.assertEqual(report, {'matched':2,'unmatched':1})
        self.assertEqual(state['mark_rows'], {'New':[row_ids(raw)[0]]})
        duplicate = pd.concat([raw, raw.iloc[[0]]],ignore_index=True)
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            copied_groups(duplicate, pd.DataFrame({'TestFlag':[1,0,-1]}), state, spectra)
