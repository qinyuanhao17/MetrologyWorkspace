"""Copyable grouping recipes shared by analytical windows and Spectra."""
import unittest
import json

import pandas as pd
from PyQt6.QtWidgets import QApplication

from metrology_app.match_group_ui import GroupControls
from metrology_app.match_groups import row_ids

APP = QApplication.instance() or QApplication([])


class GroupScriptTests(unittest.TestCase):
    def test_flag_only_script_is_pending_until_group_apply(self):
        raw = pd.DataFrame({'Wafer ID':['W1'],'Die Seq':['1']})
        target = self.controls(raw)
        target.apply_group_script(target.group_script())
        target.accept_changes()
        script = json.loads(target.group_script())
        script['records'][0]['flag'] = '1'
        target.apply_group_script(json.dumps(script))
        self.assertEqual(list(target.plan.flags),['1'])
        self.assertTrue(target.pending)

    def test_invalid_or_unmatched_recipes_leave_the_group_draft_unchanged(self):
        from copy import deepcopy
        raw = pd.DataFrame({'Wafer ID':['W1'],'Die Seq':['1']})
        controls = self.controls(raw)
        script = json.loads(controls.group_script())
        before = deepcopy(controls.state)
        for text in ('invalid', json.dumps({**script,'records':[]}),
                     json.dumps({**script,'records':script['records'] + [
                         {**script['records'][0],'flag':'1'}]}),
                     json.dumps({**script,'records':[{**script['records'][0],'flag':'1.5'}]})):
            with self.subTest(text=text), self.assertRaises(ValueError):
                controls.apply_group_script(text)
            self.assertEqual(controls.state,before)
            self.assertEqual(list(controls.plan.flags),['0'])

    def test_script_replaces_existing_mark_definitions_without_changing_live_spectra_until_apply(self):
        from tests.test_spectra_group_interactions import SpectraGroupInteractionTests
        from metrology_app.sme_spectra import file_metadata_dataframe
        fixture = SpectraGroupInteractionTests()
        viewer, sources = fixture.viewer()
        self.addCleanup(fixture.doCleanups)
        options = viewer.group_options
        options.assign_mark({sources[0].key},'POR+')
        raw = file_metadata_dataframe(sources)
        source = self.controls(raw)
        source.restore({'enabled':True,'mark_enabled':True,
                        'mark_rows':{'New':[row_ids(raw)[0]]}},pd.DataFrame({'TestFlag':[1,-1]}))
        options.open_settings()
        checked = viewer.checked_spectra()
        options.controls.apply_group_script(source.group_script())
        self.assertEqual(options.labels()[sources[0].key]['mark'],'POR+')
        options.controls.apply_button.click()
        self.assertEqual(options.labels()[sources[0].key]['mark'],'New')
        self.assertEqual(viewer.test_flags,{sources[0].key:1,sources[1].key:-1})
        self.assertEqual(viewer.checked_spectra(),checked)
        viewer.undo_action.trigger()
        self.assertEqual(options.labels()[sources[0].key]['mark'],'POR+')
        self.assertEqual(viewer.test_flags,{})

    def controls(self, raw):
        controls = GroupControls()
        self.addCleanup(controls.deleteLater)
        controls.set_sources(pd.DataFrame(), raw)
        return controls

    def test_clipboard_recipe_maps_classification_by_identity_and_keeps_selection(self):
        raw = pd.DataFrame({'Wafer ID':['W1','W1'], 'Lot ID':['L1','L1'],
                            'PAD Name':['P1','P1'], 'Die Seq':['01','02'], 'CD':['1.00','2.00']})
        source = self.controls(raw)
        source.restore({'enabled':True,'mark_enabled':True,
                        'head_names':{'1':'Accuracy'}, 'mark_rows':{'New':[row_ids(raw)[0]]},
                        'combined_groups':[{'id':'combined:both','name':'Both','members':['New:1','Old:-1']}],
                        'show_wafer_groups':['combined:both']},
                       pd.DataFrame({'TestFlag':['1','-1']}))
        source.script_button.click()
        source.script_dialog.copy_button.click()
        target_raw = raw.iloc[::-1].reset_index(drop=True)
        target = self.controls(target_raw)
        selection = target.state['data_selection'].copy()
        target.script_button.click()
        target.script_dialog.paste_button.click()
        target.script_dialog.apply_button.click()
        self.assertEqual(list(target.plan.flags), ['-1','1'])
        self.assertEqual(list(target.plan.labels), ['Old Unknown','New Accuracy'])
        self.assertEqual(list(target.plan.rows('combined:both')),[0,1])
        self.assertEqual(target.state['show_wafer_groups'],['combined:both'])
        self.assertEqual(target.state['data_selection'], selection)
        self.assertTrue(target.pending)
        self.assertEqual(raw['CD'].tolist(), ['1.00','2.00'])


if __name__ == '__main__':
    unittest.main()
