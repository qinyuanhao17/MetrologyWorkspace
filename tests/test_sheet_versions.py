"""Version swaps preserve the existing public edit and ownership contract."""
import unittest
from unittest.mock import patch

import pandas as pd
from PyQt6.QtWidgets import QApplication

from metrology_app.sheet import SheetModel, SheetView
from metrology_app.version_cells import TrackedCells, VersionCells

APP = QApplication.instance() or QApplication([])


class SheetVersionTests(unittest.TestCase):
    def setUp(self):
        self.original = pd.DataFrame({'Wafer ID': ['001'] * 180,
            **{f'P{column}': [f'{row}.{column:012}' for row in range(180)]
               for column in range(50)}})
        self.model = SheetModel()
        self.view = SheetView(self.model)
        self.addCleanup(self.view.deleteLater)
        self.addCleanup(self.model.deleteLater)
        self.model.load(self.original)
        self.edited = self.original.copy()
        for name in self.original.columns[1:]:
            self.edited[name] = [f'000{row}.12345678901234567890' for row in range(180)]

    def paste(self):
        with patch.object(APP.clipboard(), 'text', return_value=self.edited.to_csv(sep='\t', index=False)):
            self.view.paste()

    def test_batch_and_undo_swap_immutable_versions_before_notifying(self):
        seen = []
        self.model.changed.connect(lambda: seen.append(self.model.document_frame()))
        self.paste()
        self.assertIsInstance(self.model.cells, VersionCells)
        after = self.model.cells.version
        snapshot = self.model.snapshot()
        self.model.undo.undo()
        before = self.model.cells.version
        self.assertIsNot(after, before)
        self.assertIs(after.columns[0], before.columns[0])
        self.model.undo.redo()
        self.assertIs(self.model.cells.version, after)
        for observed, expected in zip(seen, (self.edited, self.original, self.edited)):
            pd.testing.assert_frame_equal(observed, expected)
        self.assertEqual(snapshot[0][(1, 1)], self.edited.iat[0, 1])
        self.assertEqual(before.cell(1, 1), self.original.iat[0, 1])
        self.assertFalse(any(isinstance(item, pd.DataFrame) for item in (before.columns, after.columns)))

    def test_direct_mutation_invalidates_without_requiring_changed_signal(self):
        for versioned in (False, True):
            with self.subTest(versioned=versioned):
                self.model.load(self.original)
                if versioned:
                    self.paste()
                self.model.document_frame()
                self.model.frame()
                self.model.cells[(2, 2)] = '1e-000019'
                self.assertEqual(self.model.document_frame().iat[1, 2], '1e-000019')
                self.assertEqual(self.model.frame().iat[1, 2], '1e-000019')
                if versioned:
                    self.assertIsNone(self.model.cells.version)

    def test_interleaved_structure_ordinary_edits_and_external_cells_use_fallback(self):
        self.paste()
        self.model.edit({(2, 2): 'another literal'})
        self.model.undo.undo()
        pd.testing.assert_frame_equal(self.model.document_frame(), self.edited)
        self.model.undo.undo()
        pd.testing.assert_frame_equal(self.model.document_frame(), self.original)
        self.model.undo.redo()
        pd.testing.assert_frame_equal(self.model.document_frame(), self.edited)
        self.model.cells[(2, 0)] = 'external identity'
        self.model.undo.undo()
        expected = self.original.copy()
        expected.iat[1, 0] = 'external identity'
        pd.testing.assert_frame_equal(self.model.document_frame(), expected)
        self.assertIsInstance(self.model.cells, TrackedCells)

    def test_cell_mapping_mutators_and_copies_match_dictionary(self):
        self.paste()
        saved = self.model.cells.copy()
        self.assertEqual(dict(self.model.cells), saved)
        self.model.cells.update({(1, 2): 'new value'})
        self.assertEqual(self.model.document_frame().iat[0, 2], 'new value')
        self.assertNotEqual(saved[(1, 2)], 'new value')
        self.model.cells.pop((180, 49))
        self.assertEqual(self.model.document_frame().iat[-1, 49], '')
        self.model.cells.clear()
        self.assertTrue(self.model.document_frame().empty)

    def test_unrepresented_external_cells_cannot_be_discarded_by_version_adoption(self):
        self.model.cells[(-1, 0)] = 'external source extension'
        self.model.document_frame()
        self.assertIsNone(self.model._column_version())
        self.paste()
        self.assertEqual(self.model.snapshot()[0][(-1, 0)], 'external source extension')
        self.model.undo.undo()
        self.assertEqual(self.model.snapshot()[0][(-1, 0)], 'external source extension')
