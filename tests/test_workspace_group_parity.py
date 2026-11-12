"""Grouping and input protection shared by analytical workspaces."""
from copy import deepcopy
import unittest

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from metrology_app.correlation_window import CorrelationWindow

APP = QApplication.instance() or QApplication([])


class WorkspaceGroupParityTests(unittest.TestCase):
    def window(self, cls=CorrelationWindow):
        window = cls()
        window.document.force_close = True
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        return window

    def test_correlation_ref_and_raw_offer_persistent_metadata_locks(self):
        window = self.window()
        raw = pd.DataFrame({'Wafer ID':['W1','W1'],'Die Seq':['01','02'],'CD':['1.00','2.00']})
        window.set_table(raw,'Raw')
        window.set_reference_table(raw)
        for model,view in ((window.raw_model,window.raw_sheet),(window.reference_model,window.reference_sheet)):
            self.assertTrue(view.metadata_locks_enabled)
            view.toggle_column_lock(model.index(0,0))
            self.assertEqual(model.clipboard_locks,{'Wafer ID'})
            model.paste_cells({(1,0):'Changed',(1,2):'9.00'})
            self.assertEqual(model.document_frame().iloc[0].tolist(),['W1','01','9.00'])
            model.undo.undo()
            self.assertEqual(model.document_frame().iloc[0].tolist(),['W1','01','1.00'])
        restored = self.window()
        restored.restore_workspace(deepcopy(window.workspace_snapshot()))
        self.assertEqual(restored.raw_model.clipboard_locks,{'Wafer ID'})
        self.assertEqual(restored.reference_model.clipboard_locks,{'Wafer ID'})

    def test_linked_correlation_raw_refresh_retains_locked_metadata(self):
        from metrology_app.matching import ParameterMapping
        window = self.window()
        raw = pd.DataFrame({'Wafer ID':['W1','W1'],'Die Seq':['01','02'],'X':['1.000','2.000'],'CD':['4.00','5.00']})
        reference = pd.DataFrame({'Reference CD':['4.00','5.00']})
        mappings = [ParameterMapping('CD','Reference CD','CD')]
        window.set_sources(reference,raw,mappings)
        window.raw_sheet.toggle_column_lock(window.raw_model.index(0,2))
        updated = raw.copy()
        updated['X'] = ['8.000','9.000']
        updated['CD'] = ['6.00','7.00']
        window.set_workbook_sources(updated,mappings)
        self.assertEqual(window.raw_model.frame()['X'].tolist(),['1.000','2.000'])
        self.assertEqual(window.raw_model.frame()['CD'].tolist(),['6.00','7.00'])

    def test_all_parameters_are_paginated_within_the_map_budget(self):
        from metrology_app.plot_page import PlotPage
        page = PlotPage()
        self.addCleanup(page.deleteLater)
        page.page_size.setValue(12)
        wafers = [str(i) for i in range(90)]
        page.selection = {'metrics':[f'Parameter {i}' for i in range(24)]}
        first,index,pages = page.paginate_wafers(wafers)
        self.assertEqual(first,wafers[:5])
        self.assertEqual(pages,18)
        page.page_index = pages-1
        last,_,_ = page.paginate_wafers(wafers)
        self.assertEqual(last,wafers[-5:])

    def test_wafer_groups_are_captions_and_persist_without_splitting_rows(self):
        from metrology_app.window import MainWindow
        window = self.window(MainWindow)
        raw = pd.DataFrame({'Wafer ID':['W1']*4,'Lot ID':['L1']*4,'PAD Name':['P1']*4,
                            'Die Seq':['1','2','3','4'],'X':[0,1,0,1],'Y':[0,0,1,1],'CD':[1,2,3,4]})
        window.set_table(raw,'Raw')
        before = {k:tuple(v) for k,v in window.selection['groups'].items()}
        window.group_settings_action.trigger()
        controls = window.group_controls
        self.assertEqual([s['name'] for s in controls.state['mark_values']],['POR','POR+','POR-'])
        controls.mark_enabled.setChecked(True)
        controls.apply_button.click()
        self.assertEqual(window.selection['groups'],before)
        self.assertEqual(list(window.selection['labels'].values()),['POR · W1 · L1 · P1'])
        restored = self.window(MainWindow)
        restored.restore_workspace(deepcopy(window.workspace_snapshot()))
        self.assertEqual(list(restored.selection['labels'].values()),['POR · W1 · L1 · P1'])
        restored.groups_enabled_action.setChecked(False)
        self.assertEqual(list(restored.selection['labels'].values()),['W1 · L1 · P1'])

    def test_correlation_default_marks_and_compact_identity_table(self):
        window = self.window()
        raw = pd.DataFrame({'Wafer ID':['W1'],'Lot ID':['L1'],'PAD Name':['P1'],'Die Seq':[1],'CD':[2]})
        window.set_table(raw,'Raw')
        dialog = window.display_options.open_groups()
        self.assertEqual([s['name'] for s in window.group_controls.state['mark_values']],['POR','POR+','POR-'])
        self.assertEqual(dialog.table.model().data(dialog.table.model().index(0,0)),'W1')

    def test_marks_dialog_append_creates_a_real_composite_group(self):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QComboBox,QPushButton,QTreeWidget
        window = self.window()
        raw = pd.DataFrame({'Wafer ID':['W1'],'Lot ID':['L1'],'PAD Name':['P1'],'Die Seq':[1],'CD':[2]})
        window.set_table(raw,'Raw')
        controls = window.group_controls
        controls.restore({'mark_enabled':True,'mark_values':[{'id':'Old','name':'Old'},{'id':'POR','name':'POR'}]})
        controls.set_sources(pd.DataFrame(),raw)
        errors = []
        def edit():
            dialog = APP.activeModalWidget()
            try:
                dialog.findChild(QComboBox,'markVisible').setCurrentText('POR')
                dialog.findChild(QComboBox,'markAssignmentMode').setCurrentText('Append')
                dialog.findChild(QPushButton,'assignVisibleMark').click()
                assignments = dialog.findChild(QTreeWidget,'markAssignments')
                self.assertEqual(assignments.itemWidget(assignments.topLevelItem(0),1).currentText(),'Old/POR')
                dialog.accept()
            except Exception as error:
                errors.append(error)
                dialog.reject()
        QTimer.singleShot(0,edit)
        controls.mark_new()
        self.assertEqual(errors,[])
        self.assertIn('Old/POR',[s['name'] for s in controls.state['mark_values']])
        controls.apply_button.click()
        self.assertEqual(window._group_plan.labels,('Old/POR',))

    def test_group_caption_repaint_retains_prepared_maps_and_adds_measured_sigma(self):
        from metrology_app.plot_page import PlotPage
        from metrology_app.array_plot import ArrayOptions,prepare_array
        from tests.test_wafer_static import finish_graphics
        frame = pd.DataFrame({'W':['W1']*4,'X':[0,1,0,1],'Y':[0,0,1,1],'CD':[1,2,3,4]})
        selection = {'wafer_column':'W','wafers':['W1'],'metrics':['CD'],'labels':{'W1':'W1'}}
        page = PlotPage()
        self.addCleanup(page.deleteLater)
        self.addCleanup(page.stop)
        page.set_input(frame,selection)
        page.render_result(prepare_array(frame,selection,ArrayOptions('X','Y')))
        finish_graphics(page)
        panels = tuple(page.map_grid.panels)
        surface = page.result['scenes'][0]['surface']
        page.set_input(frame,{**selection,'labels':{'W1':'POR · W1 · L1 · P1'}})
        self.assertEqual(tuple(page.map_grid.panels),panels)
        self.assertIs(page.result['scenes'][0]['surface'],surface)
        self.assertEqual(panels[0].source['label'],'POR · W1 · L1 · P1')
        page._ensure_export()
        details = page._figure.axes[0]._wafer_title_details
        self.assertEqual(details[0].get_text(),'POR · W1 · L1 · P1')
        self.assertIn('Sigma 1.118',details[1].get_text())

    def test_wafer_workbook_groups_can_be_copied_once_and_restored_independently(self):
        from metrology_app.matching_window import MatchingWindow
        from metrology_app.window import MainWindow
        owner = self.window(MatchingWindow)
        raw = pd.DataFrame({'Wafer ID':['W1']*4,'Lot ID':['L1']*4,'PAD Name':['P1']*4,
                            'Die Seq':[1,2,3,4],'X':[0,1,0,1],'Y':[0,0,1,1],'CD':[1,2,3,4]})
        owner.set_reference_frame(pd.DataFrame({'CD':[1,2,3,4]}))
        owner.set_raw_frame(raw)
        owner.mapping_table.cellWidget(0,3).setCurrentText('CD')
        owner.mapping_table.item(0,0).setCheckState(Qt.CheckState.Checked)
        owner.group_controls.restore({'mark_enabled':True},pd.DataFrame({'TestFlag':[0]*4}))
        owner.group_controls.accept_changes()
        owner.run_analysis()
        child = owner.open_stage_workspace('preview')
        self.assertTrue(child.display_options.copy_groups())
        self.assertFalse(child.follow_workbook_groups_action.isChecked())
        self.assertTrue(all(c.startswith('Old · ') for c in child.selection['labels'].values()))
        state = deepcopy(owner.group_controls.state)
        state['applied']['mark_values'][0]['name'] = 'Parent changed'
        owner.group_controls.restore(state,pd.DataFrame({'TestFlag':[0]*4}))
        owner.run_analysis()
        self.assertTrue(all(c.startswith('Old · ') for c in child.selection['labels'].values()))
        restored = self.window(MainWindow)
        restored.restore_workspace(deepcopy(child.workspace_snapshot()))
        self.assertEqual(restored.selection['labels'],child.selection['labels'])


if __name__ == '__main__':
    unittest.main()
