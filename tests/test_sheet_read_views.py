"""Borrowed internal reads stay stable; public reads remain independent edits."""
import unittest

import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QApplication

from metrology_app.sheet import SheetModel

APP = QApplication.instance() or QApplication([])


class SheetReadViewTests(unittest.TestCase):
    def setUp(self):
        self.original = pd.DataFrame({'Wafer ID': ['001'] * 180,
            **{f'P{i}': [f'{j}.{i:012}' for j in range(180)] for i in range(50)}})
        self.original.attrs = {'source': {'rows': [8, 3, 8]}}
        self.edited = self.original.copy()
        for name in self.edited.columns[1:]:
            self.edited[name] = [f'000{j}.12345678901234567890' for j in range(180)]
        self.model = SheetModel()
        self.addCleanup(self.model.deleteLater)
        self.model.load(self.original)
        self.paste(self.edited)
        self.assertIsNotNone(self.model.literal_version)

    def paste(self, frame):
        self.assertTrue(self.model._paste_value_matrix([list(frame.columns), *frame.to_numpy().tolist()], 0, 0))

    def test_internal_reads_share_readonly_data_and_own_their_metadata(self):
        for kind, reader in (('document', self.model._document_view), ('analysis', self.model._analysis_view)):
            with self.subTest(kind=kind):
                view = reader()
                self.assertTrue(np.shares_memory(view.to_numpy(), self.model._frames[kind].to_numpy()))
                self.assertFalse(view.to_numpy().flags.writeable)
                with self.assertRaises(ValueError):
                    view.iat[0, 1] = 'cannot alter the borrowed source'
                with self.assertRaises(ValueError):
                    view.to_numpy().flags.writeable = True
                view.attrs['source']['rows'][0] = 999
                view.index.name = 'borrower index'
                view.columns.name = 'borrower columns'
                public = self.model.document_frame() if kind == 'document' else self.model.frame()
                pd.testing.assert_frame_equal(public, self.edited)
                self.assertEqual(public.attrs['source']['rows'], [8, 3, 8])
                public.iat[0, 1] = 'public independent edit'
                self.assertEqual(reader().iat[0, 1], self.edited.iat[0, 1])

    def test_old_reads_stay_stable_across_batch_undo_redo_and_general_edit(self):
        document, analysis = self.model._document_view(), self.model._analysis_view()
        next_frame = self.edited.copy()
        next_frame['P0'] = ['1e-19'] * len(next_frame)
        self.paste(next_frame)
        self.model.undo.undo()
        self.model.undo.redo()
        self.model.edit({(2, 3): 'ordinary edit'})
        self.model.undo.undo()
        for view in (document, analysis):
            pd.testing.assert_frame_equal(view, self.edited)
        pd.testing.assert_frame_equal(self.model.document_frame(), next_frame)

    def test_unknown_writes_load_and_clear_never_change_previous_reads(self):
        view = self.model._document_view()
        self.model.cells[(2, 3)] = 'unknown direct write'
        self.assertEqual(self.model.document_frame().iat[1, 3], 'unknown direct write')
        pd.testing.assert_frame_equal(view, self.edited)
        self.model.load(pd.DataFrame({'ID': ['new'], 'Value': ['0001.230000']}))
        pd.testing.assert_frame_equal(view, self.edited)
        self.model.cells.clear()
        self.assertTrue(self.model.document_frame().empty)
        pd.testing.assert_frame_equal(view, self.edited)

    def test_reset_observers_read_the_new_source_and_old_borrow_remains_old(self):
        before, after = [], []
        reader = self.model._document_view
        self.model.modelAboutToBeReset.connect(lambda: before.append(reader()))
        self.model.modelReset.connect(lambda: after.append(reader()))
        incoming = pd.DataFrame({'ID': ['new'], 'Value': ['0001.230000']})
        self.model.load(incoming)
        pd.testing.assert_frame_equal(before[0], self.edited)
        pd.testing.assert_frame_equal(after[0], incoming)

    def test_nonversion_model_keeps_detached_writable_read_fallback(self):
        model = SheetModel()
        self.addCleanup(model.deleteLater)
        original = pd.DataFrame({'ID': ['001', '002'], 'Value': ['1.23000000000000001', '']})
        model.load(original)
        self.assertIsNone(model.literal_version)
        view = model._document_view()
        view.iat[0, 1] = 'borrower owns this fallback copy'
        pd.testing.assert_frame_equal(model.document_frame(), original)

    def test_copy_on_write_options_keep_old_borrows_and_public_edits_independent(self):
        for enabled in (False, True):
            with self.subTest(copy_on_write=enabled), pd.option_context('mode.copy_on_write', enabled):
                model = SheetModel()
                self.addCleanup(model.deleteLater)
                model.load(self.edited)
                self.assertIsNotNone(model._column_version())
                document, analysis = model._document_view(), model._analysis_view()
                model.edit({(2, 3): 'current ordinary edit'})
                public = model.document_frame()
                public.iat[0, 1] = 'public copy'
                self.assertEqual(model.document_frame().iat[1, 3], 'current ordinary edit')
                self.assertEqual(model.document_frame().iat[0, 1], self.edited.iat[0, 1])
                pd.testing.assert_frame_equal(document, self.edited)
                pd.testing.assert_frame_equal(analysis, self.edited)
                model.undo.undo()
                pd.testing.assert_frame_equal(model.document_frame(), self.edited)

    def test_frozen_recovery_copy_is_independent_of_later_model_changes(self):
        from metrology_app.recovery import freeze_snapshot
        from metrology_app.workspace_store import WorkspaceSnapshot
        view = self.model._document_view()
        frozen = freeze_snapshot(WorkspaceSnapshot('correlation_trend', {'raw_data': view}, {'ui': {}}))
        self.model.edit({(2, 3): 'new current value'})
        pd.testing.assert_frame_equal(view, self.edited)
        pd.testing.assert_frame_equal(frozen.frames['raw_data'], self.edited)
        frozen.frames['raw_data'].iat[0, 1] = 'snapshot only'
        self.assertEqual(self.model.document_frame().iat[0, 1], self.edited.iat[0, 1])
