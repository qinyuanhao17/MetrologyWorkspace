"""Independent and Workbook-owned Group/Plot Label options use the same rules."""
from copy import deepcopy
import unittest
import pandas as pd
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

from metrology_app.correlation_window import CorrelationWindow

APP = QApplication.instance() or QApplication([])


class CorrelationGroupOptionsTests(unittest.TestCase):
    def setUp(self):
        self.window = CorrelationWindow()
        self.window.document.force_close = True
        self.addCleanup(self.window.close)
        self.raw = pd.DataFrame({'Wafer ID':['W1']*4,'Lot ID':['L1']*4,'PAD Name':['P1']*4,
            'Die Seq':[4,3,2,1],'CD':['10.00','20.00','11.00','21.00']})
        self.reference = pd.DataFrame({'CD Reference':[1,2,3,4]})
        from metrology_app.matching import ParameterMapping
        self.window.set_sources(self.reference,self.raw,[ParameterMapping('CD','CD Reference','CD')])

    def draw(self):
        page = self.window.sequence_page
        self.window.tabs.setCurrentWidget(page)
        page.selector.selectAll(); page.draw_plot(); APP.processEvents()
        self.assertTrue(page.ready,page.status.text())
        return page

    def test_local_heads_apply_and_master_switch_restores_normal_order_without_changing_sources(self):
        self.window.group_settings_action.trigger()
        controls = self.window.group_controls
        controls.restore({'enabled':True,'head_names':{'1':'Head A','2':'Head B'},'trend_order':'groups'},
                         pd.DataFrame({'TestFlag':[1,2,1,2]}))
        controls.apply_button.click()
        page = self.draw()
        self.assertTrue(self.window._group_plan.enabled)
        self.assertEqual([label for _,_,label in page.plot_widgets[0]._wafer_axis.spans],['Head A','Head B'])
        self.assertIn([11,10,21,20],[p.listDataItems()[0].yData.tolist() for p in page.plot_widgets])
        included = self.window._group_plan.included_rows
        self.window.groups_enabled_action.setChecked(False)
        page = self.draw()
        self.assertFalse(page.selection.get('show_group_labels',False))
        self.assertEqual(self.window._group_plan.included_rows,included)
        self.assertIn([21,11,20,10],[p.listDataItems()[0].yData.tolist() for p in page.plot_widgets])
        self.window.groups_enabled_action.setChecked(True)
        self.draw()
        self.assertTrue(page.selection['show_group_labels'])
        pd.testing.assert_frame_equal(self.window.raw_model.frame(),self.raw.astype(str))

    def test_plot_labels_change_in_place_and_restore_with_the_independent_workspace(self):
        page = self.draw()
        plot = page.plot_widgets[0]
        curves = tuple(plot.listDataItems())
        plot.setXRange(.5,2.5,padding=0)
        before = plot.getViewBox().viewRange()
        self.window.plot_label_checks['pad'].setChecked(False)
        self.assertTrue(all('PAD:' not in text for _,_,text in plot._wafer_axis.spans))
        self.assertTrue(any('LOT:' in text for _,_,text in plot._wafer_axis.spans))
        self.assertEqual(tuple(plot.listDataItems()),curves)
        self.assertEqual(plot.getViewBox().viewRange(),before)
        self.window.plot_labels_enabled_action.setChecked(False)
        self.assertTrue(all('LOT:' not in text for _,_,text in plot._wafer_axis.spans))
        saved = self.window.workspace_snapshot()
        restored = CorrelationWindow(); restored.document.force_close = True
        self.addCleanup(restored.close)
        restored.restore_workspace(deepcopy(saved))
        self.assertFalse(restored.plot_labels_enabled_action.isChecked())
        self.assertFalse(restored.plot_label_checks['pad'].isChecked())
        restored.plot_labels_enabled_action.setChecked(True)
        self.assertEqual(restored.sequence_page.identity_labels,{'pad':False,'lot':True})

    def test_workbook_child_can_detach_groups_and_labels_without_changing_its_parent(self):
        from metrology_app.matching_window import MatchingWindow
        owner = MatchingWindow(); owner.document.force_close = True
        self.addCleanup(owner.close)
        owner.set_reference_frame(self.reference)
        owner.set_raw_frame(self.raw)
        owner.group_controls.restore({'enabled':True,'head_names':{'1':'Parent A','2':'Parent B'},'trend_order':'groups'},
                                    pd.DataFrame({'TestFlag':[1,2,1,2]}))
        owner.run_analysis()
        child = owner.open_correlation_workspace()
        child.set_reference_table(self.reference)
        self.assertTrue(child.follow_workbook_groups_action.isChecked())
        self.assertEqual(child._group_plan.head('1'),'Parent A')
        parent_before = deepcopy(owner.group_controls.state)
        child.follow_workbook_groups_action.setChecked(False)
        child.group_settings_action.trigger()
        child.group_controls.state['head_names']['1'] = 'Child A'
        child.group_controls.apply_button.click()
        self.assertEqual(child._group_plan.head('1'),'Child A')
        self.assertEqual(owner.group_controls.state,parent_before)
        child.plot_label_checks['pad'].setChecked(False)
        owner.set_plot_labels({'trend':{'pad':True,'lot':False}})
        self.assertEqual(child.sequence_page.identity_labels,{'pad':False,'lot':True})
        child.follow_workbook_labels_action.setChecked(True)
        self.assertEqual(child.sequence_page.identity_labels,{'pad':True,'lot':False})
        child.follow_workbook_groups_action.setChecked(True)
        self.assertEqual(child._group_plan.head('1'),'Parent A')
        child.follow_workbook_groups_action.setChecked(False)
        child.groups_enabled_action.setChecked(False)
        child.plot_labels_enabled_action.setChecked(False)
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            path = Path(folder)/'child-options.mwkb'
            owner.save_workbook(path)
            owner.load_workbook(path)
            child = owner.open_correlation_workspace()
            self.assertFalse(child.groups_enabled_action.isChecked())
            self.assertFalse(child.follow_workbook_groups_action.isChecked())
            self.assertFalse(child.plot_labels_enabled_action.isChecked())
            self.assertEqual(child._group_plan.head('1'),'Child A')

    def test_groups_and_flags_survive_standalone_round_trip_with_the_master_disabled(self):
        self.window.group_settings_action.trigger()
        controls = self.window.group_controls
        controls.restore({'enabled':True,'head_names':{'1':'A','2':'B'},'trend_order':'groups'},
                         pd.DataFrame({'TestFlag':[1,2,1,2]}))
        controls.apply_button.click()
        self.window.groups_enabled_action.setChecked(False)
        saved = self.window.workspace_snapshot()
        restored = CorrelationWindow(); restored.document.force_close = True
        self.addCleanup(restored.close)
        restored.restore_workspace(deepcopy(saved))
        self.assertFalse(restored.groups_enabled_action.isChecked())
        self.assertEqual(restored._group_plan.flags,('1','2','1','2'))
        restored.groups_enabled_action.setChecked(True)
        self.assertEqual(restored._group_plan.head('1'),'A')

    def test_opening_settings_without_edits_is_view_only_and_replacement_does_not_reuse_flags_by_count(self):
        before = self.window.workspace_snapshot().states['correlation_display']
        self.window.group_settings_action.trigger()
        self.assertEqual(self.window.workspace_snapshot().states['correlation_display'],before)
        controls = self.window.group_controls
        controls.restore({'enabled':True,'head_names':{'1':'A','2':'B'},'trend_order':'groups'},
                         pd.DataFrame({'TestFlag':[1,2,1,2]}))
        controls.apply_button.click()
        changed = self.raw.copy(); changed['Wafer ID'] = 'Different wafer'
        self.window.set_table(changed,'Replacement')
        self.window.recognize()
        self.assertIsNone(self.window._group_plan)
        self.assertIn('source identities changed',controls.status.text())

