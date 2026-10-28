"""Linked sources may share immutable literals, never mutable table owners."""
import unittest

import pandas as pd
from PyQt6.QtWidgets import QApplication

from metrology_app.linked_refresh import prepare_linked_sources
from metrology_app.sheet import SheetModel
from metrology_app.table_version import LiteralTableVersion
from metrology_app.version_cells import VersionCells

APP = QApplication.instance() or QApplication([])


class LinkedTableVersionTests(unittest.TestCase):
    def frame(self):
        frame = pd.DataFrame({'Wafer ID': ['001', '001'], 'Die Seq': ['001', '001'],
                              'CD': ['1.23000000000000000001', '-0']})
        frame.attrs['source'] = {'rows': [8, 3]}
        return frame

    def prepared(self, frame, version):
        options = {'include_fit_quality': True, 'carded': False}
        result = prepare_linked_sources({'book': None, 'raw': frame, 'raw_version': version,
            'children': [(1, 'correlation', 'preview', True, False, options)],
            'generation': 4, 'inputs': None}, lambda: False)
        return result['tables'][1]

    def test_linked_load_shares_only_the_immutable_version(self):
        frame = self.frame()
        version = LiteralTableVersion.from_frame(frame)
        prepared = self.prepared(frame, version)
        self.assertIs(prepared.get('version'), version)
        self.assertIsNone(prepared.get('cells'))
        model = SheetModel()
        self.addCleanup(model.deleteLater)
        model._linked_prepared_load = prepared
        model.load(frame)
        self.assertIsInstance(model.cells, VersionCells)
        self.assertIs(model.cells.version, version)
        frame.iat[0, 2] = 'external'
        read = model.document_frame()
        read.iat[0, 2] = 'public mutation'
        read.attrs['source']['rows'][0] = 99
        self.assertEqual(model.document_frame().iat[0, 2], '1.23000000000000000001')
        self.assertEqual(model.document_frame().attrs['source']['rows'], [8, 3])
        model.edit({(1, 2): '00009.000000000000001'})
        self.assertEqual(version.cell(1, 2), '1.23000000000000000001')
        model.undo.undo()
        pd.testing.assert_frame_equal(model.document_frame(), version.to_frame())

    def test_unproved_values_rows_headers_and_attributes_keep_full_preparation(self):
        frame = self.frame()
        version = LiteralTableVersion.from_frame(frame)
        for kind in ('value', 'row', 'header', 'attributes'):
            with self.subTest(kind=kind):
                incoming = frame.copy()
                if kind == 'value':
                    incoming.iat[0, 2] = 'different'
                elif kind == 'row':
                    incoming = incoming.iloc[::-1].reset_index(drop=True)
                elif kind == 'header':
                    incoming = incoming.rename(columns={'CD': 'New'})
                else:
                    incoming.attrs['source'] = {'rows': [8, 99]}
                prepared = self.prepared(incoming, version)
                self.assertIsNone(prepared.get('version'))
                self.assertIsInstance(prepared['cells'], dict)
                pd.testing.assert_frame_equal(prepared['document'], incoming)

    def test_reentrant_child_edit_is_not_overwritten_after_source_load(self):
        frame = self.frame()
        version = LiteralTableVersion.from_frame(frame)
        model = SheetModel()
        self.addCleanup(model.deleteLater)
        observed = []
        def edit_once():
            if not observed:
                observed.append(model.document_frame())
                model.edit({(2, 2): 'nested'})
        model.changed.connect(edit_once)
        model._linked_prepared_load = self.prepared(frame, version)
        model.load(frame)
        self.assertEqual(model.document_frame().iat[1, 2], 'nested')
        self.assertEqual(model.undo.count(), 1)
        self.assertEqual(version.cell(2, 2), '-0')
