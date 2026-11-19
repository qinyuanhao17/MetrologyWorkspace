"""Editable source identities and their Wafer selectors stay independent."""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from metrology_app.correlation_window import CorrelationWindow
from metrology_app.matching_window import MatchingWindow
from metrology_app.matching import ParameterMapping

APP = QApplication.instance() or QApplication([])


class CorrelationSourceIdentityTests(unittest.TestCase):
    def test_raw_paste_gives_unequal_source_curves_nonoverlapping_wafer_spans(self):
        window = self.window
        reference = pd.DataFrame({'Wafer ID': ['W1'] * 3 + ['W2'] * 3,
                                  'Die Seq': [1, 2, 3] * 2, 'CD': range(6)})
        raw = pd.DataFrame({'Wafer ID': ['W1'] * 5 + ['W2'] * 5 + ['W3'] * 5,
                            'Die Seq': list(range(1, 6)) * 3,
                            'CD': range(15), 'Depth': range(20, 35)})
        window.set_table(raw.iloc[:10], 'Raw Data')
        window.set_reference_table(reference)
        page = window.sequence_page
        page.selector.selectAll()
        page.draw_plot()
        QApplication.clipboard().setText(raw.to_csv(sep='\t', index=False))
        window.raw_sheet.paste(replace=True)
        window.tabs.setCurrentWidget(page)
        window.check_all(window.wafer_list, True)
        page.selector.selectAll()
        page.draw_plot()

        self.assertTrue(page.ready, page.status.text())
        self.assertEqual([(group['start'], group['stop']) for group in page.axis_groups],
                         [(0, 4), (5, 9), (10, 14)])
        self.assertEqual(page.x_range, (-.5, 14.5))
        self.assertEqual([(group['start'], group['stop']) for group in page.groups
                          if group['source']['name'] == 'Reference'], [(0, 2), (5, 7)])
        correlation = window.correlation_page
        correlation.min_rsq.setValue(0)
        correlation.selector.selectAll()
        correlation.draw_plot()
        self.assertTrue(correlation.ready, correlation.status.text())
        self.assertEqual([fit.parameter_keys for fit in correlation.all_fits],
                         [(("Raw Data", "CD"), ("Raw Data", "Depth"))])
        self.assertIn("equal Ref and Raw row counts", correlation.status.text())

    def test_double_click_targets_original_correlation_row_after_missing_values(self):
        from metrology_app.match_groups import participation_source_keys
        window = self.window
        raw = pd.DataFrame({'Wafer ID': ['W1'] * 5, 'Die Seq': [5, 4, 3, 2, 1],
                            'CD': ['1', '', '3', '4', '5'], 'Depth': ['3', '5', '8', '11', '15']})
        window.set_table(raw, 'Raw Data')
        window.show()
        page = window.correlation_page
        window.tabs.setCurrentWidget(page)
        page.selector.selectAll()
        page.start_draw()
        APP.processEvents()
        plot, = page.plot_widgets
        scatter = plot.listDataItems()[0]
        self.double_click(plot, scatter, 3, 8)

        dialog = window._data_selection_dialog()
        keys = participation_source_keys(raw)
        self.assertEqual(set(keys) - dialog.model.checked, {keys[2]})
        dialog.model.set_checked_range(2, 2, Qt.CheckState.Checked)
        dialog.accept()
        window._apply_data_selection_dialog(dialog)
        self.assertEqual(window.participating_positions(raw), set(range(len(raw))))
        dialog.deleteLater()

    def test_double_click_trend_reference_point_keeps_unequal_raw_table_checked(self):
        window = self.window
        raw = pd.DataFrame({'Wafer ID': ['W1'] * 5, 'Die Seq': [5, 4, 3, 2, 1], 'CD': range(5)})
        reference = raw.iloc[:3].assign(CD=[24, 32, 45])
        window.set_table(raw, 'Raw Data')
        window.set_reference_table(reference)
        window.show()
        page = window.sequence_page
        window.tabs.setCurrentWidget(page)
        page.selector.selectAll()
        page.draw_plot()
        APP.processEvents()
        plot = page.plot_widgets[0]
        other = page.plot_widgets[1]
        other_data = other.listDataItems()[0].yData.copy()
        item, = plot.listDataItems()
        original = item.yData.copy()
        self.double_click(plot, item.scatter, item.xData[0], item.yData[0])

        self.assertEqual(window._table_participating_positions("reference", reference), {0, 1})
        self.assertEqual(window.participating_positions(raw), set(range(len(raw))))
        self.assertIs(page.stack.currentWidget(), page.interactive_scroll)
        self.assertEqual(page.plot_widgets, [plot, other])
        self.assertEqual(item.yData.tolist(), original[1:].tolist())
        self.assertEqual(other.listDataItems()[0].yData.tolist(), other_data.tolist())
        restored = CorrelationWindow()
        self.addCleanup(self.close_window, restored)
        restored.restore_workspace(window.workspace_snapshot())
        self.assertEqual(restored._table_participating_positions("reference", reference), {0, 1})

        menu = plot.getViewBox().getMenu(None)
        actions = {action.text(): action for action in menu.actions()}
        self.assertIn("View All", actions)
        actions["Undo point removal"].trigger()
        self.assertEqual(item.yData.tolist(), original.tolist())
        self.assertEqual(window._table_participating_positions("reference", reference), {0, 1, 2})
        redo = next(action for action in menu.actions() if action.text() == "Redo point removal")
        redo.trigger()
        self.assertEqual(item.yData.tolist(), original[1:].tolist())
        actions["Restore all removed points"].trigger()
        self.assertEqual(item.yData.tolist(), original.tolist())
        self.assertIs(page.stack.currentWidget(), page.interactive_scroll)

    def test_removing_points_only_repaints_clicked_correlation_charts_and_undo_restores_them(self):
        from unittest.mock import patch
        window = self.window
        raw = pd.DataFrame({'Wafer ID': ['W1'] * 5, 'Die Seq': [5, 4, 3, 2, 1],
                            'CD': range(5), 'Depth': [0, 3, 5, 8, 12], 'Etch': [2, 4, 5, 10, 13]})
        window.set_table(raw, 'Raw Data')
        window.show()
        page = window.correlation_page
        window.tabs.setCurrentWidget(page)
        page.min_rsq.setValue(0)
        page.selector.selectAll()
        page.start_draw()
        APP.processEvents()
        first, second, third = page.plot_widgets
        plots = [first, second, third]
        data = [plot.listDataItems()[0].getData() for plot in plots]

        with patch.object(page, "draw_plot", wraps=page.draw_plot) as draw:
            for plot, index in [(first, 1), (second, 3)]:
                item = plot.listDataItems()[0]
                x, y = item.getData()
                self.double_click(plot, item, x[index], y[index])
            QTest.qWait(170)
            self.assertIs(page.stack.currentWidget(), page.interactive_scroll)
            self.assertEqual(page.plot_widgets, plots)
            self.assertEqual([len(plot.listDataItems()[0].getData()[0]) for plot in plots], [4, 4, 5])
            self.assertEqual(window.participating_positions(raw), {0, 2, 4})
            menu = first.getViewBox().getMenu(None)
            undo = next(action for action in menu.actions() if action.text() == "Undo point removal")
            undo.trigger()
            self.assertEqual([len(plot.listDataItems()[0].getData()[0]) for plot in plots], [4, 5, 5])
            reset = next(action for action in menu.actions() if action.text() == "Restore all removed points")
            reset.trigger()
            self.assertEqual(window.participating_positions(raw), set(range(len(raw))))
            draw.assert_not_called()
        for plot, (x, y) in zip(plots, data):
            restored_x, restored_y = plot.listDataItems()[0].getData()
            self.assertEqual(restored_x.tolist(), x.tolist())
            self.assertEqual(restored_y.tolist(), y.tolist())

    @staticmethod
    def double_click(plot, scatter, x, y):
        position = plot.mapFromScene(scatter.mapToScene(QPointF(x, y)))
        QTest.mouseDClick(plot.viewport(), Qt.MouseButton.LeftButton, pos=position)

    @staticmethod
    def close_window(window):
        window.document.force_close = True
        window.close()
        window.deleteLater()
        APP.processEvents()

    def test_corrected_vendor_identity_uses_current_three_wafer_spans(self):
        from metrology_app.sequence_data import prepare_sequence_groups
        raw = pd.DataFrame({'Wafer ID': ['W1'] * 3 + ['W2'] * 3 + ['W3'] * 3,
                            'Lot ID': ['L'] * 9, 'Die Seq': [1, 2, 3] * 3,
                            'CD': list(range(9))})
        reference = raw.rename(columns={'Wafer ID': 'Wafer', 'Lot ID': 'Lot'}).copy()
        reference['Wafer'] = ['Vendor1'] * 3 + ['Vendor2'] * 3 + ['Vendor3'] * 3
        reference['Lot'] = ['Old1'] * 3 + ['Old2'] * 3 + ['Old3'] * 3
        window = self.window
        window.set_table(raw, 'Raw')
        window.set_reference_table(reference)
        window.reference_model.edit({(row + 1, column): str(raw.iloc[row, column])
                                     for row in range(9) for column in (0, 1)})
        window.recognize()
        selection = window.sequence_page.selection
        groups, extent = prepare_sequence_groups(window.sequence_page.frame, selection,
            selection['available_cells'], window.sequence_page.wafer_column, window.sequence_page.die_column)
        self.assertEqual(len({(g['start'], g['stop']) for g in groups}), 3)
        self.assertEqual(extent, 9)
        self.assertEqual({g['wafer'] for g in groups}, {'W1', 'W2', 'W3'})
        window.reference_model.undo.undo()
        window.recognize()
        selection = window.sequence_page.selection
        groups, _ = prepare_sequence_groups(window.sequence_page.frame, selection,
            selection['available_cells'], window.sequence_page.wafer_column, window.sequence_page.die_column)
        self.assertEqual(len({(g['start'], g['stop']) for g in groups}), 6)
        window.reference_model.undo.redo()
        window.recognize()
        selection = window.sequence_page.selection
        groups, _ = prepare_sequence_groups(window.sequence_page.frame, selection,
            selection['available_cells'], window.sequence_page.wafer_column, window.sequence_page.die_column)
        self.assertEqual(len({(g['start'], g['stop']) for g in groups}), 3)

    def test_reference_dimensions_are_visible_and_follow_actual_pasted_extent(self):
        window = self.window
        window.set_reference_table(pd.DataFrame({'Wafer ID': ['W1'] * 3, 'CD': ['1', '2', '3']}))
        window.show()
        APP.processEvents()
        self.assertTrue(window.reference_footer.isVisible())
        self.assertEqual(window.reference_footer.text(), '3 rows × 2 columns')
        window.reference_model.edit({(0, 2): 'Depth', (5, 2): '8.250000'})
        self.assertEqual(window.reference_footer.text(), '5 rows × 3 columns')
        window.reference_model.undo.undo()
        self.assertEqual(window.reference_footer.text(), '3 rows × 2 columns')

    def setUp(self):
        self.window = CorrelationWindow()
        self.raw = pd.DataFrame({
            "Wafer ID": ["RAW1"] * 3, "Lot ID": ["LOT1"] * 3,
            "Die Seq": ["001", "003", "008"], "CD": ["1.00", "2.00", "3.00"],
        })

    def tearDown(self):
        self.close_window(self.window)

    def test_ref_only_edits_refresh_wafer_recognition_and_grouping_menu(self):
        w = self.window
        w.set_reference_table(self.raw)
        w.reference_model.edit({(0, 0): "Sample", (1, 0): "REF2"})
        w.recognize()
        self.assertIn("Sample", w.reference_group_checks)
        self.assertNotIn("Wafer ID", w.reference_group_checks)
        w.reference_group_checks["Sample"].setChecked(True)
        self.assertEqual(w.reference_wafer_list.topLevelItemCount(), 2)
        self.assertTrue(w.reference_group_picker.isEnabled())

    def test_pasting_cells_into_initially_blank_ref_enables_wafer_menu(self):
        w = self.window
        w.set_reference_table(pd.DataFrame())
        w.reference_model.edit({
            (0, 0): "Wafer ID", (0, 1): "CD", (1, 0): "REF1", (1, 1): "1.000",
        })
        # Wait for the ordinary edit debounce, not a fixed delay sensitive to
        # queued rendering from other GUI tests. Never invoke recognize here.
        for _ in range(80):
            if w.reference_group_picker.isEnabled():
                break
            QTest.qWait(25)
        self.assertTrue(w.reference_group_picker.isEnabled())
        self.assertIn("Wafer ID", w.reference_group_checks)
        self.assertEqual(w.reference_wafer_list.topLevelItem(0).text(0), "REF1")

    def test_ref_only_measurements_can_draw_both_analysis_pages(self):
        w = self.window
        reference = self.raw.assign(Depth=["2.00", "4.00", "6.00"])
        w.set_reference_table(reference)
        w.recognize()
        self.assertEqual([source["name"] for source in w.selection["sources"]], ["Reference"])
        for page in (w.correlation_page, w.sequence_page):
            page.selector.selectAll()
            page.draw_plot()
            self.assertTrue(page.ready, page.status.text())
        pd.testing.assert_frame_equal(w.reference_model.document_frame(), reference)

    def test_imported_ref_identity_is_not_replaced_by_existing_or_later_raw(self):
        w = self.window
        reference = self.raw.assign(**{"Wafer ID": ["REF1"] * 3, "Die Seq": ["010", "020", "030"]})
        for ref_first in (False, True):
            with self.subTest(ref_first=ref_first):
                w.set_reference_table(pd.DataFrame())
                w.set_table(pd.DataFrame(), "Empty Raw")
                if ref_first:
                    w.set_reference_table(reference)
                    w.set_table(self.raw, "Raw")
                else:
                    w.set_table(self.raw, "Raw")
                    w.set_reference_table(reference)
                pd.testing.assert_frame_equal(w.reference_model.document_frame(), reference)
                w.set_workbook_sources(self.raw, ())
                pd.testing.assert_frame_equal(w.reference_model.document_frame(), reference)

    def test_ref_identity_edits_survive_recognition_and_wafer_check_changes(self):
        w = self.window
        w.set_sources(pd.DataFrame({"REF CD": ["2.00", "4.00", "6.00"]}), self.raw, ())
        w.reference_model.edit({(1, 0): "REF2", (1, 3): "8.12345000"})
        before = w.reference_model.document_frame().copy()
        w.recognize()
        pd.testing.assert_frame_equal(w.reference_model.document_frame(), before)
        item = w.reference_wafer_list.topLevelItem(0)
        item.setCheckState(0, Qt.CheckState.Unchecked)
        w.reference_group_checks["Lot ID"].setChecked(True)
        pd.testing.assert_frame_equal(w.reference_model.document_frame(), before)
        self.assertTrue(w.reference_model.undo.canUndo())

    def test_ref_header_and_literal_edits_can_be_undone_after_grouping_changes(self):
        w = self.window
        w.set_sources(pd.DataFrame({"REF CD": ["2.00", "4.00", "6.00"]}), self.raw, ())
        original = w.reference_model.document_frame().copy()
        w.reference_model.edit({(0, 0): "Sample", (1, 0): "REF2", (1, 3): "8.12345000"})
        edited = w.reference_model.document_frame().copy()
        w.recognize()
        w.reference_group_checks["Sample"].setChecked(True)
        w.reference_group_checks["Lot ID"].setChecked(True)
        w.reference_wafer_list.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
        w.recognize()
        pd.testing.assert_frame_equal(w.reference_model.document_frame(), edited)
        w.reference_model.undo.undo()
        w.recognize()
        pd.testing.assert_frame_equal(w.reference_model.document_frame(), original)
        w.reference_model.undo.redo()
        w.recognize()
        pd.testing.assert_frame_equal(w.reference_model.document_frame(), edited)

    def test_linked_raw_refresh_and_reopen_preserve_manual_ref_identity(self):
        parent = MatchingWindow()
        restored = None
        try:
            parent.match_type.setCurrentText("NOVA")
            parent.set_reference_frame(pd.DataFrame({"CD": ["2", "4", "6"]}))
            parent.set_raw_frame(self.raw)
            parent._populate_mappings([ParameterMapping("CD", "CD", "CD")])
            parent.run_analysis()
            child = parent.open_correlation_workspace()
            manual = self.raw.assign(**{"Wafer ID": ["REF1"] * 3})
            child.set_reference_table(manual)
            child.reference_model.edit({(1, 0): "REF2", (1, 3): "9.12345000"})
            child.recognize()
            child.reference_group_checks["Lot ID"].setChecked(True)
            child.reference_wafer_list.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
            before = child.reference_model.document_frame().copy()
            selected = child.selected(child.reference_wafer_list)
            parent.raw_model.edit({(1, 0): "RAW2", (1, 3): "1.23450000"})
            parent.run_analysis()
            pd.testing.assert_frame_equal(child.reference_model.document_frame(), before)
            self.assertTrue(child.reference_group_checks["Lot ID"].isChecked())
            self.assertEqual(child.selected(child.reference_wafer_list), selected)
            self.assertTrue(child.reference_model.undo.canUndo())
            with TemporaryDirectory() as folder:
                path = Path(folder) / "manual-ref-identity.mwkb"
                parent.save_workbook(path)
                restored = MatchingWindow()
                restored.load_workbook(path)
                reopened = restored.open_correlation_workspace()
                pd.testing.assert_frame_equal(reopened.reference_model.document_frame(), before)
        finally:
            for window in (parent, restored):
                if window is not None:
                    window.document.force_close = True
                    window.close()
                    window.deleteLater()
            APP.processEvents()

    def test_match_workbook_ref_copy_is_independent_and_follows_parent_selection(self):
        from metrology_app.match_groups import row_ids

        parent = MatchingWindow()
        self.addCleanup(self.close_window, parent)
        parent.set_reference_frame(pd.DataFrame({"Ref CD": ["1.00", "2.00", "3.00"]}))
        parent.set_raw_frame(self.raw)
        child = parent.open_correlation_workspace()
        self.assertFalse(child.copy_reference_from_wkb_action.isChecked())
        self.assertNotIn(child.reference_selection_action, child.data_menu.actions())
        self.assertFalse(child.reference_selection_action.isVisible())
        self.assertTrue(child.reference_model.document_frame().empty)

        child.copy_from_wkb_action.setChecked(False)
        child.set_table(self.raw.iloc[:1].assign(**{"Wafer ID": ["Independent"]}), "Manual Raw")
        manual_raw = child.raw_model.document_frame()
        keys = row_ids(parent.raw_frame)
        selection = {"records": [{"key": key, "id": str(i)} for i, key in enumerate(keys)],
                     "excluded": ["1"], "hide_excluded": True}
        for state in (parent.group_controls.state, parent.group_controls.state["applied"]):
            state["data_selection"] = selection
        child.copy_reference_from_wkb_action.setChecked(True)
        self.assertTrue(child.copy_reference_from_wkb_action.isChecked())
        copied = child.reference_model.document_frame()
        self.assertEqual(copied["Ref CD"].tolist(), ["1.00", "2.00", "3.00"])
        self.assertEqual(child._table_participating_positions("reference", copied), {0, 2})
        self.assertFalse(child.reference_selection_action.isVisible())
        self.assertTrue(child.workbook_selection_action.isEnabled())
        pd.testing.assert_frame_equal(child.raw_model.document_frame(), manual_raw)

        parent.set_reference_frame(pd.DataFrame({"Ref CD": ["4.00", "5.00", "6.00"]}))
        parent.sync_stage_windows()
        self.assertEqual(child.reference_model.document_frame()["Ref CD"].tolist(), ["4.00", "5.00", "6.00"])
        with TemporaryDirectory() as folder:
            path = Path(folder) / "linked-ref.mwkb"
            parent.save_workbook(path)
            restored = MatchingWindow()
            self.addCleanup(self.close_window, restored)
            restored.load_workbook(path)
            reopened = restored.open_correlation_workspace()
            self.assertTrue(reopened.copy_reference_from_wkb_action.isChecked())
            self.assertFalse(reopened.copy_from_wkb_action.isChecked())
            pd.testing.assert_frame_equal(reopened.raw_model.document_frame(), manual_raw)
            self.assertEqual(reopened.reference_model.document_frame()["Ref CD"].tolist(),
                             ["4.00", "5.00", "6.00"])
            reopened.copy_reference_from_wkb_action.setChecked(False)
            restored.set_reference_frame(pd.DataFrame({"Ref CD": ["7", "8", "9"]}))
            restored.sync_stage_windows()
            self.assertEqual(reopened.reference_model.document_frame()["Ref CD"].tolist(),
                             ["4.00", "5.00", "6.00"])

    def test_explicit_mapping_rows_survive_saved_workbook_source_replacement(self):
        parent = MatchingWindow()
        self.addCleanup(self.close_window, parent)
        parent.set_reference_frame(pd.DataFrame({"CD": ["1", "2", "3"], "Unmapped": ["7"] * 3}))
        parent.set_raw_frame(self.raw)
        self.assertEqual(parent.mapping_table.rowCount(), 0)
        with patch("metrology_app.matching_window.QInputDialog.getItem", return_value=("CD", True)):
            parent.mapping_add_button.click()
        self.assertEqual(parent.mapping_table.rowCount(), 1)
        parent.mapping_table.cellWidget(0, 3).setCurrentText("CD")
        parent.mapping_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        original = parent._mapping_state()
        with TemporaryDirectory() as folder:
            path = Path(folder) / "manual-mapping.mwkb"
            parent.save_workbook(path)
            restored = MatchingWindow()
            self.addCleanup(self.close_window, restored)
            restored.load_workbook(path)
            self.assertEqual(restored._mapping_state(), original)
            restored.set_reference_frame(pd.DataFrame({"New Reference": ["10"] * 3}))
            restored.set_raw_frame(self.raw.rename(columns={"CD": "New Raw"}))
            self.assertEqual(restored._mapping_state(), original)
            self.assertFalse(restored.analyze_button.isEnabled())
            restored.set_reference_frame(pd.DataFrame({"CD": ["11"] * 3, "New Reference": ["10"] * 3}))
            restored.set_raw_frame(self.raw)
            self.assertEqual(restored._mapping_state(), original)
            self.assertTrue(restored.analyze_button.isEnabled())

    def test_ref_and_raw_grouping_menus_remain_open_after_repeated_check_changes(self):
        w = self.window
        w.set_sources(pd.DataFrame({"REF CD": ["2.00", "4.00", "6.00"]}), self.raw, ())
        w.show()
        APP.processEvents()
        for page, picker, menu, checks in (
            (w.reference_page, w.reference_group_picker, w.reference_group_menu, w.reference_group_checks),
            (w.tabs.widget(1), w.group_picker, w.group_menu, w.group_checks),
        ):
            with self.subTest(source=page):
                w.tabs.setCurrentWidget(page)
                menu.popup(picker.mapToGlobal(QPoint(0, picker.height())))
                APP.processEvents()
                self.assertTrue(menu.isVisible())
                action = checks["Lot ID"]
                initial = action.isChecked()
                for expected in (not initial, initial):
                    QTest.mouseClick(menu, Qt.MouseButton.LeftButton,
                                     pos=menu.actionGeometry(action).center())
                    APP.processEvents()
                    self.assertEqual(action.isChecked(), expected)
                    self.assertTrue(menu.isVisible())
                menu.close()

    def test_raw_identity_edits_survive_recognition_and_wafer_check_changes(self):
        w = self.window
        w.set_sources(pd.DataFrame({"REF CD": ["2.00", "4.00", "6.00"]}), self.raw, ())
        w.raw_model.edit({(1, 0): "RAW2", (1, 3): "9.12345000"})
        before = w.raw_model.document_frame().copy()
        w.recognize()
        w.wafer_list.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
        w.group_checks["Lot ID"].setChecked(True)
        pd.testing.assert_frame_equal(w.raw_model.document_frame(), before)
        self.assertTrue(w.raw_model.undo.canUndo())
