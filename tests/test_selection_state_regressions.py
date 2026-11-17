"""Selection survives stage entry; incomplete fits remain savable drafts."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import pandas as pd
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from metrology_app.matching_window import MatchingWindow
from metrology_app.matching import ParameterMapping
from metrology_app.match_groups import GroupPlan, participation_rows
from metrology_app.data_selection import DataSelectionDialog
from metrology_app.workspace_store import json_text, load_workspace
from metrology_app.correlation_window import CorrelationWindow

APP = QApplication.instance() or QApplication([])

class SelectionStateRegressionTests(unittest.TestCase):
    @staticmethod
    def wait_for_recognition(w):
        for _ in range(80):
            if not w.refresh_timer.isActive():
                return
            QTest.qWait(25)
        raise AssertionError('Table edits did not finish ordinary recognition')

    def window(self):
        w = MatchingWindow()
        self.addCleanup(self.close, w)
        return w

    @staticmethod
    def close(w):
        for child in tuple(getattr(w, '_stage_windows', ())):
            child.document.force_close = True
            child.close()
        w.document.force_close = True
        w.close()
        w.deleteLater()
        APP.processEvents()

    def sources(self):
        raw = pd.DataFrame({'Wafer ID':['W1']*6, 'Die Seq':[1,2,3]*2,
            'Cycle':[1]*3+[2]*3, 'X(mm)':[1,2,3]*2, 'Y(mm)':[0]*6,
            'CD':['1.000','2.000','3.000','1.100','2.100','3.100']})
        return pd.DataFrame({'Ref':['1.0','2.0','3.0','1.1','2.1','3.1']}), raw

    def select(self, w, rows):
        plan = GroupPlan(w._active_raw_frame(), w.group_controls.flags_frame(), w.group_controls.state, w.reference_frame)
        d = DataSelectionDialog(plan)
        d.model.checked = {d.model.ids[i] for i in rows}
        d.hide_excluded.setChecked(True)
        d.accept()
        for state in (w.group_controls.state, w.group_controls.state['applied']):
            state['data_selection'] = deepcopy(d.selection)
        d.deleteLater()

    def test_first_keyboard_paste_into_other_stage_keeps_selection_both_directions(self):
        for origin, target in [('Preview','Final'), ('Final','Preview')]:
            with self.subTest(origin=origin):
                w = self.window()
                ref, raw = self.sources()
                w.set_reference_frame(ref)
                w.result_mode.setCurrentText(origin)
                w.set_raw_frame(raw)
                self.select(w, [1,4])
                saved = deepcopy(w.group_controls.state['data_selection'])
                w.result_mode.setCurrentText(target)
                model = w.final_raw_model if target == 'Final' else w.raw_model
                APP.clipboard().setText(raw.to_csv(sep='\t', index=False))
                w.raw_view.paste()
                for state in (w.group_controls.state, w.group_controls.state['applied']):
                    self.assertEqual(participation_rows(w._active_raw_frame(), state['data_selection']), (1,4))
                    self.assertEqual(state['data_selection'], saved)

    def test_one_selected_pair_opens_and_saves_map_and_dynamic_without_invalid_card(self):
        w = self.window()
        ref, raw = self.sources()
        w.set_reference_frame(ref)
        w.set_raw_frame(raw)
        w._populate_mappings([ParameterMapping('CD','Ref','CD')])
        w.run_analysis()
        self.select(w, [0])
        w.run_analysis(apply_groups=False)
        w.preview_dynamic_frame = raw.copy()
        for child in (w.open_dynamic_workspace('preview'), w.open_stage_workspace('preview')):
            json_text(child.workspace_snapshot().states)
            self.assertFalse(child.parameter_cards)
            self.assertFalse(child.card_check.isEnabled())
            with TemporaryDirectory() as folder:
                path = child.document.export_copy(Path(folder) / ('selection' + ('.wdyn' if child.workspace_type == 'dynamic' else '.wmap')))
                saved = load_workspace(path)
                self.assertFalse(saved.states['ui']['cards'])
                self.assertEqual(len(saved.frames['input_data']), 6)
                self.assertIsInstance(saved.states['workbook_participation'], dict)
                child.restore_workspace(saved)
                self.assertEqual(child._participation_excluded, set(saved.states['workbook_participation']['excluded']))
                json_text(child.workspace_snapshot().states)

    def test_script_formats_reject_other_tools_without_changing_selection(self):
        from metrology_app.selection_script import export_script, import_script
        from metrology_app.group_script import export_group_script, import_group_script
        from metrology_app.die_map_selection import import_selected_dies
        w = self.window()
        ref, raw = self.sources()
        raw = raw.iloc[:3]
        w.set_reference_frame(ref.iloc[:3])
        w.set_raw_frame(raw)
        self.select(w, [1])
        current = deepcopy(w.group_controls.state)
        selection = export_script(raw, {'checked':[1]})
        groups = export_group_script(raw, w.group_controls.flags_frame(), current)
        with self.assertRaises(ValueError):
            import_script(raw, groups)
        with self.assertRaises(ValueError):
            import_group_script(selection, raw, current)
        for script in (groups, selection):
            with self.assertRaises(ValueError):
                import_selected_dies((), script)
        updated, _ = import_group_script(groups, raw, current)
        self.assertEqual(updated['data_selection'], current['data_selection'])
        self.assertEqual(w.group_controls.state, current)

    def test_nonfinite_cards_are_unavailable_but_valid_cards_still_round_trip(self):
        from metrology_app.window import MainWindow
        w = MainWindow()
        self.addCleanup(self.close, w)
        w.set_parameter_cards({'bad':(float('nan'), 1), 'overflow':(1,float('inf')), 'CD':(1.1,2.3)})
        self.assertEqual(w.parameter_cards, {'CD':(1.1,2.3)})
        self.assertTrue(w.card_check.isEnabled())
        with TemporaryDirectory() as folder:
            path = w.document.save(Path(folder) / 'cards.wmap')
            saved = load_workspace(path)
            w.restore_workspace(saved)
            self.assertEqual(w.parameter_cards, {'CD':(1.1,2.3)})

    def test_reference_count_correction_rebuilds_current_source_rows(self):
        w = CorrelationWindow()
        self.addCleanup(self.close, w)
        ref, raw = self.sources()
        w.set_table(raw, 'Raw')
        w.set_reference_table(ref.iloc[:2], 'Ref')
        w.reference_model.replace_matrix([list(ref.columns)] + ref.values.tolist())
        QTest.qWait(400)
        self.assertEqual(len(w._analysis_frame), len(ref)+len(raw))
        self.assertEqual(len(w.reference_model.document_frame()), len(ref))

    def test_value_only_ref_count_correction_by_clipboard_recognizes_current_wafers(self):
        ref, raw = self.sources()
        for wrong_count in (2, 7):
            with self.subTest(wrong_count=wrong_count):
                w = CorrelationWindow()
                self.addCleanup(self.close, w)
                w.set_table(raw, 'Raw')
                wrong = (ref.iloc[:wrong_count] if wrong_count < len(ref)
                         else pd.concat([ref, ref.iloc[:1]], ignore_index=True))
                w.set_reference_table(wrong, 'Ref')
                APP.clipboard().setText(ref.to_csv(sep='\t', index=False))
                w.reference_sheet.paste(replace=True)
                self.wait_for_recognition(w)
                self.assertEqual({m.wafer for m in w.reference_measurements}, {'W1'})
                self.assertEqual(sum(len(m.rows) for m in w.reference_measurements), len(ref))
                self.assertIn('Reference', {s['name'] for s in w.selection['sources']})
                pd.testing.assert_frame_equal(w.reference_model.document_frame(), ref)
                self.assertTrue(w.reference_model.undo.canUndo())
                w.reference_model.undo.undo()
                self.wait_for_recognition(w)
                self.assertFalse(w.reference_measurements)
                w.reference_model.undo.redo()
                self.wait_for_recognition(w)
                self.assertEqual(sum(len(m.rows) for m in w.reference_measurements), len(ref))

    def test_raw_count_correction_by_clipboard_rebuilds_value_only_ref_without_changing_it(self):
        ref, raw = self.sources()
        w = CorrelationWindow()
        self.addCleanup(self.close, w)
        w.set_reference_table(ref, 'Ref')
        APP.clipboard().setText(raw.iloc[:2].to_csv(sep='\t', index=False))
        w.sheet.paste(replace=True)
        self.wait_for_recognition(w)
        APP.clipboard().setText(raw.to_csv(sep='\t', index=False))
        w.sheet.paste(replace=True)
        self.wait_for_recognition(w)
        self.assertEqual({m.wafer for m in w.reference_measurements}, {'W1'})
        self.assertEqual(sum(len(m.rows) for m in w.reference_measurements), len(ref))
        self.assertIn('Reference', {s['name'] for s in w.selection['sources']})
        pd.testing.assert_frame_equal(w.reference_model.document_frame(), ref)
        self.assertTrue(w.raw_model.undo.canUndo())
        w.raw_model.undo.undo()
        self.wait_for_recognition(w)
        self.assertFalse(w.reference_measurements)
        w.raw_model.undo.redo()
        self.wait_for_recognition(w)
        self.assertEqual(sum(len(m.rows) for m in w.reference_measurements), len(ref))
        pd.testing.assert_frame_equal(w.reference_model.document_frame(), ref)

    def test_reference_grid_append_and_clear_refresh_current_row_alignment(self):
        from PyQt6.QtCore import Qt
        w = CorrelationWindow()
        self.addCleanup(self.close, w)
        ref, raw = self.sources()
        w.set_table(raw, 'Raw')
        w.set_reference_table(ref.iloc[:2], 'Ref')
        w.reference_sheet.setCurrentIndex(w.reference_model.index(3,0))
        APP.clipboard().setText(ref.iloc[2:].to_csv(sep='\t', index=False, header=False))
        w.reference_sheet.paste()
        self.wait_for_recognition(w)
        self.assertEqual(sum(len(m.rows) for m in w.reference_measurements), len(ref))
        w.reference_model.edit({(7,0):'9.000'})
        self.wait_for_recognition(w)
        self.assertFalse(w.reference_measurements)
        w.reference_sheet.setCurrentIndex(w.reference_model.index(7,0))
        QTest.keyClick(w.reference_sheet, Qt.Key.Key_Delete)
        self.wait_for_recognition(w)
        self.assertEqual(sum(len(m.rows) for m in w.reference_measurements), len(ref))
        pd.testing.assert_frame_equal(w.reference_model.frame(), ref)
        self.assertEqual(w.reference_model.document_frame().iloc[6,0], '')
        w.reference_model.undo.undo()
        self.wait_for_recognition(w)
        self.assertFalse(w.reference_measurements)
        w.reference_model.undo.redo()
        self.wait_for_recognition(w)
        self.assertEqual(sum(len(m.rows) for m in w.reference_measurements), len(ref))

        page = w.sequence_page
        page.selector.selectAll()
        page.draw_plot()
        self.assertTrue(page.ready, page.status.text())
        reference_groups = [g for g in page.groups if g['key'][0] == 'Reference']
        self.assertEqual(sum(len(g['positions']) for g in reference_groups), len(ref))

    def test_match_reference_count_correction_refreshes_after_selection(self):
        w = self.window()
        ref, raw = self.sources()
        w.set_reference_frame(ref)
        w.set_raw_frame(raw)
        w._populate_mappings([ParameterMapping('CD','Ref','CD')])
        w.run_analysis()
        self.select(w, [0,1,2])
        w.run_analysis(apply_groups=False)
        extra = pd.concat([ref, ref.iloc[:1]], ignore_index=True)
        w.reference_model.replace_matrix([list(extra.columns)] + extra.values.tolist())
        QTest.qWait(150)
        self.assertFalse(w.analyze_button.isEnabled())
        w.reference_model.replace_matrix([list(ref.columns)] + ref.values.tolist())
        QTest.qWait(300)
        self.assertTrue(w.analyze_button.isEnabled())
        self.assertTrue(w._analysis_current)
        self.assertEqual(w.result.source_rows, (0,1,2))

    def test_map_font_can_be_smaller_and_round_trips(self):
        from metrology_app.window import MainWindow
        w = MainWindow()
        self.addCleanup(self.close, w)
        w.plot_page.font_size.setCurrentText('5')
        self.assertEqual(w.plot_page.font_size.currentText(), '5')
        with TemporaryDirectory() as folder:
            path = w.document.save(Path(folder) / 'font.wmap')
            saved = load_workspace(path)
            self.assertEqual(saved.states['ui']['pages']['plot_page']['controls']['font_size'], '5')

    def test_dense_map_small_font_matches_native_and_export_point_labels(self):
        import numpy as np
        from metrology_app.array_plot import ArrayOptions, prepare_array
        from tests.test_wafer_static import finish_graphics
        xy = [(x, y) for x in np.linspace(-100,100,13) for y in np.linspace(-100,100,13)]
        frame = pd.DataFrame({'Wafer ID':['W1']*len(xy),
            'X mm':[p[0] for p in xy], 'Y mm':[p[1] for p in xy],
            'CD':np.linspace(1,2,len(xy))})
        original = frame.copy(deep=True)
        result = prepare_array(frame, {'wafer_column':'Wafer ID', 'wafers':['W1'], 'metrics':['CD']},
                               ArrayOptions('X mm','Y mm', labels=True))
        from metrology_app.plot_page import PlotPage
        page = PlotPage()
        self.addCleanup(page.deleteLater)
        self.addCleanup(page.close)
        self.addCleanup(page.stop)
        page.font_size.setCurrentText('5')
        page.render_result(result)
        finish_graphics(page)
        exported = page.artists[0][0]
        self.assertGreater(len(exported.value_labels.values), 100)
        self.assertLess(exported.value_labels.fontsize, 4.5)
        page.figure.canvas.draw()
        panel = page.map_grid.panels[0]
        np.testing.assert_array_equal(panel.positions, exported.value_labels.positions)
        self.assertEqual(panel.drawn_indices, exported.value_labels.drawn_indices)
        pd.testing.assert_frame_equal(frame, original)
