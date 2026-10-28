"""Dense clipboard edits retain the ordinary transaction's observable contract."""
import unittest
from unittest.mock import patch

import pandas as pd
from PyQt6.QtWidgets import QApplication

from metrology_app.sheet import SheetModel, SheetView

APP = QApplication.instance() or QApplication([])


class SheetBatchTransactionTests(unittest.TestCase):
    def setUp(self):
        self.model = SheetModel()
        self.view = SheetView(self.model)
        self.addCleanup(self.view.deleteLater)
        self.addCleanup(self.model.deleteLater)
        self.original = pd.DataFrame({
            'Wafer ID': ['W001'] * 180,
            'Die Seq': [f'{row:04}' for row in range(180)],
            **{f'P{column}': [f'{row}.{column:012}' for row in range(180)]
               for column in range(50)},
        })
        self.model.load(self.original)
        self.model.frame()
        self.edited = self.original.copy()
        for name in self.original.columns[2:]:
            self.edited[name] = [f'000{row}.{int(name[1:]) + 51:012}' for row in range(180)]

    def paste(self, frame):
        self.view.setCurrentIndex(self.model.index(0, 0))
        text = frame.to_csv(sep='\t', index=False, lineterminator='\n')
        with patch.object(APP.clipboard(), 'text', return_value=text):
            self.view.paste()

    def assert_frame(self, expected):
        pd.testing.assert_frame_equal(self.model.document_frame(), expected)
        pd.testing.assert_frame_equal(self.model.frame(), expected)

    def test_dense_paste_undo_redo_literals_snapshots_and_receipt(self):
        self.original.attrs['source'] = {'row_order': ['original']}
        self.model.load(self.original)
        self.model.frame()
        self.edited.attrs = {'source': {'row_order': ['original']}}
        snapshot = self.model.document_frame()
        self.paste(self.edited)
        self.assert_frame(self.edited)
        self.assertEqual(self.model.undo.count(), 1)
        report = self.model.paste_report
        self.assertEqual(len(report.changes), 9000)
        self.assertEqual(report.changes[(17, 2)],
                         (self.original.iat[16, 2], self.edited.iat[16, 2]))
        self.assertIn('180 data rows', report.summary)
        self.assertEqual(report.columns[0], (2, 'P0', 180))
        command = self.model.undo.command(0)
        for mapping in (report.changes, command.before, command.after):
            with self.assertRaises(TypeError):
                mapping[(17, 2)] = 'corrupt'
        pd.testing.assert_frame_equal(snapshot, self.original)
        snapshot.attrs['source']['row_order'][0] = 'external mutation'
        self.assertEqual(self.model.document_frame().attrs['source']['row_order'], ['original'])
        self.model.undo.undo()
        self.assert_frame(self.original)
        self.assertIsNone(self.model.paste_report)
        self.model.undo.redo()
        self.assert_frame(self.edited)
        self.assertEqual(report.changes[(17, 2)][1], self.edited.iat[16, 2])

    def test_callbacks_observe_the_complete_edit_and_detached_change_context(self):
        observed, contexts = [], []
        def observe(*_):
            observed.append((self.model.document_frame().iat[0, 2],
                             self.model.frame().iat[-1, -1],
                             self.model.cells[(180, 51)]))
            contexts.append(self.model.changed_cells)
        self.model.dataChanged.connect(observe)
        self.model.changed.connect(observe)
        self.paste(self.edited)
        self.model.undo.undo()
        self.model.undo.redo()
        expected = []
        for frame in (self.edited, self.original, self.edited):
            expected += [(frame.iat[0, 2], frame.iat[-1, -1], frame.iat[-1, -1])] * 2
        self.assertEqual(observed, expected)
        self.assertIsNone(self.model.changed_cells)
        self.assertEqual(contexts[0][(1, 2)], self.edited.iat[0, 2])
        self.assertEqual(contexts[2][(1, 2)], self.original.iat[0, 2])

    def test_sparse_changes_noop_paste_and_interleaved_ordinary_edit(self):
        edited = self.original.copy()
        edited.iat[3, 4] = '0003.12345678901234567890'
        edited.iat[172, 49] = '1e-19'
        self.paste(edited)
        self.assert_frame(edited)
        self.assertEqual(len(self.model.paste_report.changes), 2)
        self.assertIn('2 data rows', self.model.paste_report.summary)
        self.model.edit({(11, 7): '9.00000000000000000001'})
        self.model.undo.undo()
        self.assert_frame(edited)
        self.model.undo.undo()
        self.assert_frame(self.original)
        self.model.undo.redo()
        self.assert_frame(edited)
        count, revision = self.model.undo.count(), self.model.revision
        self.paste(edited)
        self.assertEqual((self.model.undo.count(), self.model.revision), (count, revision))
        self.assertEqual(self.model.paste_report.changes, {})

    def test_reentrant_apply_and_unknown_notification_invalidate_exactly(self):
        nested = []
        def observe(*_):
            if not nested:
                nested.append(True)
                self.model.apply({(4, 8): '7.00000000000001'})
        self.model.dataChanged.connect(observe)
        self.paste(self.edited)
        expected = self.edited.copy()
        expected.iat[3, 8] = '7.00000000000001'
        self.assert_frame(expected)
        self.model.cells[(5, 9)] = '8.00000000000009'
        self.model.changed.emit()
        expected.iat[4, 9] = '8.00000000000009'
        self.assert_frame(expected)
        self.model.undo.undo()
        # The batch owns its changed cells, just like CellEdit.
        self.assert_frame(self.original)

    def test_blank_header_identity_and_size_changes_use_general_behavior(self):
        for change in ('blank', 'header', 'identity', 'growth'):
            with self.subTest(change=change):
                self.model.load(self.original)
                edited = self.edited.copy()
                if change == 'blank':
                    edited.iat[4, 6] = ' '
                elif change == 'header':
                    edited = edited.rename(columns={'P0': 'Renamed'})
                elif change == 'identity':
                    edited.iat[0, 1] = 'NEW01'
                else:
                    edited.loc[len(edited)] = edited.iloc[-1].tolist()
                self.paste(edited)
                self.assert_frame(edited)
                self.model.undo.undo()
                self.assert_frame(self.original)

    def test_metadata_lock_and_subclass_hooks_are_not_bypassed(self):
        self.model.set_clipboard_locks({'Wafer ID', 'Die Seq', 'P0'})
        self.paste(self.edited)
        expected = self.edited.copy()
        expected['P0'] = self.original['P0']
        self.assert_frame(expected)
        self.model.undo.undo()
        self.assert_frame(self.original)
        class CustomSheet(SheetModel):
            def apply(self, changes):
                self.applied = True
                super().apply(changes)
        custom = CustomSheet()
        self.addCleanup(custom.deleteLater)
        custom.load(self.original)
        self.view.setModel(custom)
        self.paste(self.edited)
        self.assertTrue(custom.applied)
        pd.testing.assert_frame_equal(custom.document_frame(), self.edited)
