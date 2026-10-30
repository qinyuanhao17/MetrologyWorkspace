"""Public export and analysis-selection regressions from the v4.3.2 audit."""
from pathlib import Path
import tempfile
import unittest
from time import monotonic
from xml.etree import ElementTree as ET
from unittest.mock import patch

import pandas as pd
from openpyxl import load_workbook
from PyQt6.QtCore import QTimer
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication, QLineEdit, QPushButton

from metrology_app.matching_window import MatchingWindow
from tests import test_workbook_copy_data as copy_fixtures

APP = QApplication.instance() or QApplication([])


class FinalAuditTests(unittest.TestCase):
    def parent(self):
        parent = MatchingWindow()
        self.addCleanup(copy_fixtures.WorkbookCopyDataTests.close_window, parent)
        reference, raw, _ = copy_fixtures.WorkbookCopyDataTests.sources()
        parent.match_type.setCurrentText('NOVA')
        parent.set_reference_frame(reference)
        parent.set_raw_frame(raw)
        parent.run_analysis()
        return parent

    def exclude(self, window, query='002'):
        errors = []
        def choose():
            dialog = APP.activeModalWidget()
            try:
                dialog.findChild(QLineEdit, 'dataSelectionSearch').setText(query)
                next(button for button in dialog.findChildren(QPushButton)
                     if button.text() == 'Uncheck Visible').click()
                dialog.accept()
            except Exception as error:
                errors.append(error)
                dialog.reject()
        QTimer.singleShot(0, choose)
        window.data_selection_action.trigger()
        self.assertEqual(errors, [])

    def test_parent_selection_updates_existing_children_without_recopy(self):
        parent = self.parent()
        children = [parent.open_stage_workspace('preview'), parent.open_correlation_workspace()]
        originals = [child.model.document_frame().copy(deep=True) for child in children]
        self.exclude(parent)
        self.assertEqual(parent.result.source_rows, (1, 2, 3))
        for child, original in zip(children, originals):
            self.assertTrue(child.copy_from_wkb_action.isChecked())
            self.assertEqual(child.participating_positions(child.model.document_frame()), {1, 2, 3})
            pd.testing.assert_frame_equal(child.model.document_frame(), original)

    def test_child_local_selection_updates_immediately_without_recopy(self):
        parent = self.parent()
        for child in (parent.open_stage_workspace('preview'), parent.open_correlation_workspace()):
            with self.subTest(child=child.workspace_type):
                original = child.model.document_frame().copy(deep=True)
                self.exclude(child)
                self.assertTrue(child.copy_from_wkb_action.isChecked())
                self.assertEqual(child.participating_positions(child.model.document_frame()), {1, 2, 3})
                groups = child.selection['groups']
                self.assertTrue(groups)
                if child.workspace_type == 'correlation_trend':
                    self.assertTrue(all(0 not in rows and 4 not in rows for rows in groups.values()))
                else:
                    self.assertTrue(all(0 not in rows for rows in groups.values()))
                pd.testing.assert_frame_equal(child.model.document_frame(), original)

    def test_dynamic_data_menu_has_only_local_selection_scope(self):
        parent = self.parent()
        child = parent.open_dynamic_workspace('preview')
        actions = child.data_menu.actions()
        self.assertIn(child.data_selection_action, actions)
        self.assertNotIn(child.workbook_selection_action, actions)
        self.assertNotIn(child.full_data_action, actions)

    def test_linked_refresh_draws_trend_once_even_if_correlation_processes_events(self):
        parent = self.parent()
        reference, _raw, _ = copy_fixtures.WorkbookCopyDataTests.sources()
        child = parent.open_correlation_workspace()
        child.set_reference_table(reference)
        for tree in (child.wafer_list, child.parameter_list,
                     child.reference_wafer_list, child.reference_parameter_list):
            child.check_all(tree, True)
        for page in (child.correlation_page, child.sequence_page):
            page.selector.selectAll()
            page.draw_plot()
            self.assertTrue(page.ready)
        QTest.qWait(250)
        correlation, trend = child.correlation_page, child.sequence_page
        restore = correlation.restore_draw_state
        def yielding_restore(state):
            # Large fit pages pump Qt events while rendering. Make that boundary
            # deterministic without changing the fit data or shortening a timer.
            QTest.qWait(250)
            restore(state)
        column = parent.raw_model.document_frame().columns.get_loc('CD')
        automatic = QSignalSpy(trend.input_refresh_timer.timeout)
        with patch.object(correlation, 'restore_draw_state', side_effect=yielding_restore), \
                patch.object(correlation, 'draw_plot', wraps=correlation.draw_plot) as fits, \
                patch.object(trend, 'draw_plot', wraps=trend.draw_plot) as curves:
            parent.raw_model.edit({(1, column): '1.100000'})
            parent.run_analysis()
            QTest.qWait(250)
            self.assertEqual(fits.call_count, 1)
            self.assertEqual(curves.call_count, 1, 'The automatic Trend timer drew superseded choices')
            self.assertEqual(len(automatic), 0, 'Trend redrew from its already-connected Qt timer')
        self.assertTrue(correlation.ready)
        self.assertTrue(trend.ready)
        self.assertEqual(child.raw_model.document_frame().iloc[0]['CD'], '1.100000')
        self.assertEqual(len(child.raw_model.document_frame()), 4)
        from metrology_app.analysis_export import capture_window
        plots = capture_window(child)['plots']
        rendered = [float(value) for plot in plots if plot['sheet'] == 'Trend'
                    for series in plot['series'] for value in series['data']['Y']]
        self.assertIn(1.1, rendered, 'Final drawn Trend still contains stale source values')

    def test_source_and_membership_change_restores_map_choices_only_once(self):
        parent = self.parent()
        child = parent.open_stage_workspace('preview')
        child.check_all(child.wafer_list, True)
        child._set_checked_values(child.parameter_list, ['CD'])
        child.update_plan()
        for page in (child.plot_page, child.radius_page):
            page.selector.selectAll()
        child.plot_page.draw_maps()
        child.radius_page.draw_plot()
        deadline = monotonic()+8
        while child.plot_page.background_render_pending and monotonic()<deadline:
            QTest.qWait(20)
        self.assertIsNotNone(child.plot_page.result)
        column = parent.raw_model.document_frame().columns.get_loc('Wafer ID')
        with patch.object(child.plot_page, 'restore_draw_state', wraps=child.plot_page.restore_draw_state) as maps, \
                patch.object(child.radius_page, 'restore_draw_state', wraps=child.radius_page.restore_draw_state) as radius:
            parent.raw_model.edit({(1, column): '002'})
            parent.run_analysis()
            self.assertEqual(maps.call_count, 1)
            self.assertEqual(radius.call_count, 1)

    def test_parent_selection_redraws_existing_maps_when_a_whole_wafer_is_excluded(self):
        self.check_map_selection_refresh()

    def test_parent_selection_does_not_draw_pending_box_changes(self):
        self.check_map_selection_refresh(pending=True)

    def test_parent_selection_does_not_replace_an_excluded_draw_with_another_wafer(self):
        self.check_map_selection_refresh(only_removed=True)

    def test_parent_selection_redraws_restored_grouped_map_without_recopy(self):
        self.check_map_selection_refresh(restored=True)

    def check_map_selection_refresh(self, *, pending=False, only_removed=False, restored=False):
        parent = self.parent()
        reference, raw, _ = copy_fixtures.WorkbookCopyDataTests.sources()
        parent.set_reference_frame(pd.concat([reference, reference], ignore_index=True))
        parent.set_raw_frame(pd.concat([raw.assign(**{'Wafer ID': 'W1'}),
                                        raw.assign(**{'Wafer ID': 'W2'})], ignore_index=True))
        if restored:
            parent.group_controls.restore({'enabled': True,
                'head_names': {'0': 'Old MM1', '1': 'New MM2'}},
                pd.DataFrame({'TestFlag': [0]*4+[1]*4}))
        parent.run_analysis()
        child = parent.open_stage_workspace('preview')
        child.check_all(child.wafer_list, True)
        child._set_checked_values(child.parameter_list, ['CD', 'Depth'])
        child.update_plan()
        for page in (child.plot_page, child.radius_page):
            if only_removed:
                page.selector.set_selected_cells({(page.selection['wafers'][1], 'CD')})
            else:
                page.selector.selectAll()
        child.plot_page.draw_maps()
        child.radius_page.draw_plot()
        def settled():
            deadline = monotonic() + 8
            while monotonic() < deadline:
                QTest.qWait(20)
                if not child.plot_page.background_render_pending \
                        and not child.radius_page.input_refresh_timer.isActive():
                    break
        settled()
        self.assertEqual(len(child.plot_page.result['scenes']), 1 if only_removed else 4)
        self.assertTrue(child.radius_page.ready)
        if restored:
            directory = tempfile.TemporaryDirectory()
            self.addCleanup(directory.cleanup)
            path = Path(directory.name)/'grouped.mwkb'
            parent.save_workbook(path)
            parent.document.force_close = True
            parent.close()
            parent = MatchingWindow()
            self.addCleanup(copy_fixtures.WorkbookCopyDataTests.close_window, parent)
            parent.load_workbook(path)
            child = parent.open_stage_workspace('preview')
            settled()
            self.assertEqual(len(child.plot_page.result['scenes']), 4)
        if pending:
            for page in (child.plot_page, child.radius_page):
                page.selector.set_selected_cells({(page.selection['wafers'][0], 'CD')})
        self.exclude(parent, 'W2')
        settled()
        self.assertTrue(child.copy_from_wkb_action.isChecked())
        if pending or only_removed:
            self.assertIsNone(child.plot_page.result)
            self.assertFalse(child.radius_page.ready)
            if pending:
                self.assertTrue(child.plot_page.selector.pending_draw)
                self.assertTrue(child.radius_page.selector.pending_draw)
        else:
            self.assertEqual(len(child.plot_page.result['scenes']), 2)
            self.assertTrue(child.radius_page.ready)
            self.assertEqual(len(child.radius_page.plot_sources), 2)
        self.assertEqual(len(child.model.document_frame()), 8)

    def test_ordinary_export_axes_survive_workbook_styling(self):
        parent = self.parent()
        parent.group_controls.restore({'enabled': True,
            'head_names': {'0': 'Old MM1', '1': 'New MM2'}},
            pd.DataFrame({'TestFlag': [0, 0, 1, 1]}))
        parent.run_analysis()
        child = parent.open_dynamic_workspace('preview')
        child.set_table(pd.DataFrame({'Wafer ID': ['W1']*6, 'Die Seq': ['001', '002']*3,
            'Cycle': [1, 1, 2, 2, 3, 3], 'CD': ['1.001', '2.002', '1.003', '2.004', '1.005', '2.006']}), 'audit')
        child.check_all(child.wafer_list, True)
        child.check_all(child.parameter_list, True)
        child.tabs.setCurrentWidget(child.dynamic_page)
        APP.processEvents()
        with tempfile.TemporaryDirectory() as directory:
            paths = [parent.export_excel(Path(directory)/'match.xlsx'), child.export_excel(Path(directory)/'dynamic.xlsx')]
            found = set()
            for path in paths:
                book = load_workbook(path)
                try:
                    for sheet in book:
                        if not sheet.title.startswith(('RSQ', 'All Trend', 'Dynamic')):
                            continue
                        for chart in sheet._charts:
                            found.add(sheet.title.split(' (')[0])
                            with self.subTest(sheet=sheet.title):
                                self.assertFalse(chart.x_axis.delete)
                                self.assertEqual(chart.x_axis.tickLblPos, 'low')
                                self.assertEqual(chart.x_axis.tickMarkSkip, chart.x_axis.tickLblSkip)
                finally:
                    book.close()
            self.assertTrue(any(name.startswith('RSQ') for name in found), found)
            self.assertTrue(any(name.startswith('Dynamic') for name in found), found)

    def test_native_last_die_tick_does_not_overlap_prior_label(self):
        from metrology_app.native_chart_labels import D, _axis_tick_labels
        root = ET.Element(f'{{{D}}}userShapes')
        labels = [{'level': 0, 'text': 'W1'}]
        ticks = [(0., '001', 'A1'), (.85, 'LONG-DIE-0002', 'A2'), (1., 'LONG-DIE-0003', 'A3')]
        _axis_tick_labels(root, labels, (.1, .8), 500, 1, ticks, (0, 1))
        boxes = []
        for anchor in root:
            name = anchor.find(f'.//{{{D}}}cNvPr').get('name')
            if name.startswith('Die Seq tick '):
                boxes.append((float(anchor.find(f'{{{D}}}from/{{{D}}}x').text),
                              float(anchor.find(f'{{{D}}}to/{{{D}}}x').text)))
        self.assertGreaterEqual(len(boxes), 2)
        self.assertTrue(all(left[1] < right[0] for left, right in zip(boxes, boxes[1:])), boxes)
