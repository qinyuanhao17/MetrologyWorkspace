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
    def test_linked_workbook_copy_detaches_records_and_preserves_shared_references(self):
        from metrology_app.linked_refresh import copy_linked_workbook
        from metrology_app.matching import MatchWorkbook, ParameterMapping
        from metrology_app.match_groups import participation_source_keys
        raw = self.frame()
        records = [{'id': str(i), 'key': key} for i, key in enumerate(participation_source_keys(raw))]
        book = MatchWorkbook(pd.DataFrame({'Ref': ['2', '4']}), raw,
                             [ParameterMapping('CD', 'Ref', 'CD')],
                             grouping_state={'data_selection': {'records': records, 'excluded': []}})
        records = book.grouping_state['data_selection']['records']
        book.record_alias = records
        copied = copy_linked_workbook(book)
        self.assertIs(copied.record_alias, copied.grouping_state['data_selection']['records'])
        copied.record_alias[0]['id'] = 'external'
        copied.raw.iat[0, 2] = 'caller edit'
        copied.raw.attrs['source']['rows'][0] = 99
        self.assertEqual(records[0]['id'], '0')
        self.assertEqual(book.raw.iat[0, 2], '1.23000000000000000001')
        self.assertEqual(book.raw.attrs['source']['rows'], [8, 3])

    def test_prepared_map_keeps_the_exact_stage_source_and_header_provenance(self):
        from metrology_app.matching import MatchWorkbook, ParameterMapping
        raw = pd.DataFrame({'Wafer ID': ['001', '001'], 'Die Seq': ['001', '002'],
                            'CD': ['1.23000000000000001', '2.000']})
        book = MatchWorkbook(pd.DataFrame({'Ref': ['2', '4']}), raw,
                             [ParameterMapping('CD', 'Ref', 'CD')], match_type='NOVA')
        request = {'book': book, 'raw': raw, 'children': [
            (1, 'map', 'preview', True, False, {'include_fit_quality': True, 'carded': False})],
            'generation': 1, 'inputs': None}
        expected = book.stage_frame('preview', apply_card=False, apply_selection=False, use_snapshot=False)
        prepared = prepare_linked_sources(request, lambda: False)['tables'][1]
        pd.testing.assert_frame_equal(prepared['source_frame'], expected)
        self.assertEqual(prepared['source_frame'].attrs, expected.attrs)
        self.assertIsInstance(prepared.get('version'), LiteralTableVersion)
        model = SheetModel()
        self.addCleanup(model.deleteLater)
        model._linked_prepared_load = prepared
        model.load(expected)
        prepared['source_frame'].iat[0, 2] = 'external edit'
        pd.testing.assert_frame_equal(model.document_frame(), expected)

    def test_worker_prepares_detached_participation_for_duplicate_source_identities(self):
        from copy import deepcopy
        from metrology_app.matching import MatchWorkbook, ParameterMapping
        from metrology_app.match_groups import participation_source_keys
        raw = self.frame()
        keys = participation_source_keys(raw)
        selection = {'records': [{'id': 'first', 'key': keys[0]}, {'id': 'second', 'key': keys[1]}],
                     'excluded': ['second'], 'hide_excluded': True}
        book = MatchWorkbook(pd.DataFrame({'Ref': ['2', '4']}), raw,
                             [ParameterMapping('CD', 'Ref', 'CD')],
                             grouping_state={'data_selection': selection})
        options = {'include_fit_quality': True, 'carded': False, 'applies': True,
                   'reference': pd.DataFrame(), 'trend_groups': {}}
        request = {'book': book, 'raw': raw, 'children': [
            (1, 'correlation', 'preview', True, False, options)], 'generation': 1, 'inputs': None}
        result = prepare_linked_sources(request, lambda: False)
        participation = result['participation']
        self.assertEqual(participation['excluded'], frozenset([keys[1]]))
        self.assertTrue(participation['hide_excluded'])
        next_book = deepcopy(book)
        next_book.grouping_state['data_selection']['excluded'].clear()
        request['book'] = next_book
        self.assertEqual(prepare_linked_sources(request, lambda: False)['participation']['excluded'], frozenset())
        self.assertEqual(participation['excluded'], frozenset([keys[1]]))

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

    def test_prepared_version_is_readonly_while_loaded_sheet_and_public_reads_are_editable(self):
        frame = self.frame()
        version = LiteralTableVersion.from_frame(frame)
        prepared = self.prepared(frame, version)
        for name in ('document', 'analysis'):
            with self.assertRaises(ValueError):
                prepared[name].iat[0, 2] = 'concurrent payload edit'
        model = SheetModel()
        self.addCleanup(model.deleteLater)
        model._linked_prepared_load = prepared
        model.load(frame)
        prepared['document'].attrs['source']['rows'][0] = 99
        public = model.document_frame()
        public.iat[0, 2] = 'public read edit'
        model.edit({(1, 2): '00009.000000000000001'})
        self.assertEqual(model.document_frame().iat[0, 2], '00009.000000000000001')
        self.assertEqual(model.document_frame().attrs['source']['rows'], [8, 3])
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
