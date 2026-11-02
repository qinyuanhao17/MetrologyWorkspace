"""Linked value commits preserve drafts and refresh plots even on a Data tab."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication

from benchmarks.benchmark_memory_storage import fixture, settle
from metrology_app.linked_refresh import prepare_linked_values
from metrology_app.matching_window import MatchingWindow
from metrology_app.sheet import SheetModel

APP = QApplication.instance() or QApplication([])


class PreparedLinkedValueTests(unittest.TestCase):
    def setUp(self):
        self.frame = fixture(200, 56).raw.copy()
        self.model = SheetModel()
        self.addCleanup(self.model.deleteLater)
        self.model.load(self.frame)
        self.baseline = {'document': self.model.document_frame(), 'analysis': self.model.frame(),
                         'revision': self.model.revision, 'context': (),
                         'numeric_columns': tuple(f'P{i}' for i in range(50)),
                         'identity_columns': tuple(self.frame.columns[:6])}

    def changed(self):
        return self.frame.assign(P0=[f'{float(value) + .25:.14f}' for value in self.frame.P0])

    def test_no_reset_current_frames_and_no_shared_mutable_state(self):
        incoming = self.changed()
        prepared = prepare_linked_values(incoming, self.baseline)
        self.assertIsNotNone(prepared)
        resets = QSignalSpy(self.model.modelReset)
        old = self.model.document_frame()
        observations = []
        self.model.changed.connect(lambda: observations.append(self.model.frame()))
        self.assertTrue(self.model.apply_linked_values(prepared, incoming))
        self.assertEqual(len(resets), 0)
        pd.testing.assert_frame_equal(observations[0], incoming)
        pd.testing.assert_frame_equal(self.model.document_frame(), incoming)
        pd.testing.assert_frame_equal(old, self.frame)
        self.assertEqual(self.model.undo.count(), 0)
        self.assertTrue(self.model.undo.isClean())
        prepared['document'].iat[0, 6] = 'corrupt external result'
        prepared['analysis'].iat[0, 6] = 'corrupt external result'
        pd.testing.assert_frame_equal(self.model.frame(), incoming)

    def test_changed_live_child_is_rejected_without_touching_its_draft(self):
        incoming = self.changed()
        prepared = prepare_linked_values(incoming, self.baseline)
        self.model.edit({(1, 7): '123.45678900000000001'})
        draft = self.model.document_frame()
        self.assertFalse(self.model.apply_linked_values(prepared, incoming))
        pd.testing.assert_frame_equal(self.model.document_frame(), draft)
        self.assertEqual(self.model.undo.count(), 1)

    def test_metadata_nonfinite_schema_and_row_changes_reject_qualification(self):
        for column, value in [('Wafer ID', 'W999'), ('Die Seq', 'NEW01'),
                              ('P0', ''), ('P0', 'bad'), ('P0', 'inf')]:
            with self.subTest(column=column, value=value):
                incoming = self.changed()
                incoming.loc[0, column] = value
                self.assertIsNone(prepare_linked_values(incoming, self.baseline))
        self.assertIsNone(prepare_linked_values(self.changed().iloc[:-1], self.baseline))
        self.assertIsNone(prepare_linked_values(self.changed().rename(columns={'P0': 'Other'}), self.baseline))
        incoming = self.changed()
        incoming.attrs['source_rows'] = tuple(reversed(range(len(incoming))))
        self.assertIsNone(prepare_linked_values(incoming, self.baseline))
        self.baseline['identity_columns'] += ('P0',)
        self.assertIsNone(prepare_linked_values(self.changed(), self.baseline))

    def test_cancelled_preparation_does_not_publish_a_partial_table(self):
        with self.assertRaises(InterruptedError):
            prepare_linked_values(self.changed(), self.baseline, cancelled=lambda: True)
        pd.testing.assert_frame_equal(self.model.document_frame(), self.frame)


class LinkedCorrelationValueTests(unittest.TestCase):
    def setUp(self):
        book = fixture(200, 56)
        self.parent = MatchingWindow()
        self.addCleanup(self.close_window, self.parent)
        self.parent.match_type.setCurrentText('NOVA')
        self.parent.set_reference_frame(book.reference)
        self.parent.set_raw_frame(book.raw)
        self.parent._populate_mappings(book.mappings)
        self.parent.run_analysis()
        self.child = self.parent.open_correlation_workspace()
        self.addCleanup(self.close_window, self.child)
        self.child.set_reference_table(pd.DataFrame())
        settle(APP, [self.parent, self.child])
        for i in range(self.child.parameter_list.topLevelItemCount()):
            item = self.child.parameter_list.topLevelItem(i)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(0, Qt.CheckState.Checked if item.text(0) in ('P0', 'P1')
                                   else Qt.CheckState.Unchecked)
        for page in (self.child.correlation_page, self.child.sequence_page):
            page.selector.selectAll()
            page.draw_plot()
            self.assertTrue(page.ready, page.status.text())
        self.child.tabs.setCurrentWidget(self.child.reference_page)
        self.column = self.parent.raw_model.document_frame().columns.get_loc('P0')

    @staticmethod
    def close_window(window):
        window.document.force_close = True
        window.close()
        window.deleteLater()
        APP.processEvents()

    def assert_current(self):
        settle(APP, [self.parent, self.child])
        expected = self.parent.raw_model.document_frame()
        pd.testing.assert_frame_equal(self.child.raw_model.document_frame(), expected)
        self.assertIs(self.child.tabs.currentWidget(), self.child.reference_page)
        self.assertTrue(self.child.correlation_page.ready)
        self.assertTrue(self.child.sequence_page.ready)
        values = self.child.correlation_page.all_fits[0].sources[0].fit
        np.testing.assert_array_equal(values.x, expected[values.x_name].astype(float))
        np.testing.assert_array_equal(values.y, expected[values.y_name].astype(float))
        pd.testing.assert_frame_equal(self.child.sequence_page.frame, self.child._analysis_frame)

    def test_parent_edit_undo_redo_refreshes_both_pages_without_focus_or_raw_reset(self):
        resets = QSignalSpy(self.child.raw_model.modelReset)
        first_item = self.child.parameter_list.topLevelItem(0)
        grid = self.child.correlation_page.plot_host
        applied = []
        original = self.child._set_workbook_values
        def record(*args, **kwargs):
            result = original(*args, **kwargs)
            applied.append(result)
            return result
        with patch.object(self.child, '_set_workbook_values', side_effect=record):
            for operation in (lambda: self.parent.raw_model.edit({(4, self.column): '10.75000000000001'}),
                              self.parent.raw_model.undo.undo, self.parent.raw_model.undo.redo):
                operation()
                self.assert_current()
        self.assertEqual(applied, [True, True, True])
        self.assertEqual(len(resets), 0)
        self.assertIs(self.child.parameter_list.topLevelItem(0), first_item)
        self.assertIs(self.child.correlation_page.plot_host, grid,
                      'A value-only refresh must not rebuild the identical plot layout')

    def test_local_draft_is_not_overwritten_by_parent_numeric_update(self):
        self.child.raw_model.edit({(2, self.column): '123.00000000000000001'})
        expected = self.child.raw_model.document_frame()
        self.parent.raw_model.edit({(4, self.column): '10.75000000000001'})
        settle(APP, [self.parent, self.child])
        pd.testing.assert_frame_equal(self.child.raw_model.document_frame(), expected)
        self.assertFalse(self.child.copy_from_wkb_action.isChecked())

    def test_parent_cut_preserves_selection_then_large_replacement_resumes_link(self):
        original = self.parent.raw_model.document_frame()
        selection = self.child.selection_state()
        self.parent.raw_view.selectAll()
        QTest.keyClick(self.parent.raw_view, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
        settle(APP, [self.parent, self.child])
        self.assertTrue(self.parent.raw_model.document_frame().empty)
        pd.testing.assert_frame_equal(self.child.raw_model.document_frame(), original)
        self.assertEqual(self.child.selection_state(), selection)
        self.assertTrue(self.child.copy_from_wkb_action.isChecked())
        self.assertTrue(self.child.correlation_page.ready)
        self.assertTrue(self.child.sequence_page.ready)

        incoming = original.copy()
        incoming.loc[0, 'P0'] = '10.23456789000001'
        APP.clipboard().setText(incoming.to_csv(sep='\t', index=False))
        self.parent.raw_view.setCurrentIndex(self.parent.raw_view.model().index(0, 0))
        QTest.keyClick(self.parent.raw_view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        self.assert_current()
        pd.testing.assert_frame_equal(self.child.raw_model.document_frame(), incoming)
        self.assertEqual(self.child.selection_state(), selection)
        self.assertTrue(self.child.copy_from_wkb_action.isChecked())

    def test_dense_paste_borrowed_snapshots_and_both_draws_stay_current_on_data_tab(self):
        original = self.parent.raw_model.document_frame()
        incoming = original.copy()
        for name in original.columns[6:]:
            incoming[name] = [f'{float(value) + .375:.14f}' for value in original[name]]
        incoming.loc[16, 'P0'] = 'NA'
        matrix = [list(incoming.columns), *incoming.to_numpy().tolist()]
        snapshots = []
        for operation, expected in ((lambda: self.parent.raw_model._paste_value_matrix(matrix, 0, 0), incoming),
                                    (self.parent.raw_model.undo.undo, original),
                                    (self.parent.raw_model.undo.redo, incoming)):
            operation()
            settle(APP, [self.parent, self.child])
            pd.testing.assert_frame_equal(self.child.raw_model.document_frame(), expected)
            self.assertIs(self.child.raw_model.literal_version, self.parent.raw_model.literal_version)
            snapshot = self.child.workspace_snapshot(readonly=True)
            self.assertFalse(snapshot.frames['raw_data'].to_numpy().flags.writeable)
            snapshots.append(snapshot)
            self.assertIs(self.child.tabs.currentWidget(), self.child.reference_page)
            self.assertTrue(self.child.correlation_page.ready)
            self.assertTrue(self.child.sequence_page.ready)
            values = self.child.correlation_page.all_fits[0].sources[0].fit
            x, y = (pd.to_numeric(expected[name], errors='coerce').to_numpy(float)
                    for name in (values.x_name, values.y_name))
            valid = np.isfinite(x) & np.isfinite(y)
            np.testing.assert_array_equal(values.x, x[valid])
            np.testing.assert_array_equal(values.y, y[valid])
        for snapshot, expected in zip(snapshots, (incoming, original, incoming)):
            pd.testing.assert_frame_equal(snapshot.frames['raw_data'], expected)

    def test_rapid_parent_edit_undo_redo_undo_keeps_the_last_source(self):
        self.parent.raw_model.edit({(4, self.column): '10.75000000000001'})
        APP.processEvents()
        self.parent.raw_model.undo.undo()
        self.parent.raw_model.undo.redo()
        self.parent.raw_model.undo.undo()
        self.assert_current()

    def test_explicit_disabled_draw_clears_both_pages_and_stays_disabled_on_edit(self):
        state = self.child.selection_state()
        state['correlation_draw']['enabled'] = False
        state['trend_draw']['enabled'] = False
        self.child.restore_selection(state)
        self.parent.raw_model.edit({(4, self.column): '10.75000000000001'})
        settle(APP, [self.parent, self.child])
        for page in (self.child.correlation_page, self.child.sequence_page):
            self.assertFalse(page.has_drawn_once)
            self.assertFalse(page.ready)
            self.assertEqual(page.plot_widgets, [])
            self.assertFalse(page.input_refresh_timer.isActive())
        pd.testing.assert_frame_equal(self.child.raw_model.document_frame(),
                                      self.parent.raw_model.document_frame())
