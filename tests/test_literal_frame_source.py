"""Only a current model's immutable readonly region can prove source identity."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QApplication

from benchmarks.benchmark_memory_storage import fixture
from metrology_app.sheet import SheetModel, prepare_sheet_version
from metrology_app.linked_refresh import prepare_linked_sources
from metrology_app.matching_window import MatchingWindow
from metrology_app.table_version import LiteralTableVersion


APP = QApplication.instance() or QApplication([])


class LiteralFrameSourceTests(unittest.TestCase):
    def model(self, frame):
        model = SheetModel()
        self.addCleanup(model.deleteLater)
        model._load_prepared_frame(prepare_sheet_version(
            frame, LiteralTableVersion.from_frame(frame)))
        return model

    def test_proved_source_retains_all_literals_without_rescanning_values(self):
        frame = pd.DataFrame({'Die Seq': ['001', '001', '03'],
                              'CD': ['1.0000000000000001', 'NA', '-0']})
        frame.attrs['source_rows'] = [8, 3, 3]
        model = self.model(frame)
        source = model._literal_source()
        self.assertIs(source.version, model.literal_version)
        with patch.object(LiteralTableVersion, 'matches_frame',
                          side_effect=AssertionError('Already proved source was rescanned')):
            prepared = prepare_sheet_version(source.frame, source.version, source=source)
        self.assertIs(prepared['version'], model.literal_version)
        pd.testing.assert_frame_equal(prepared['document'], frame)
        with self.assertRaises(ValueError):
            prepared['document'].iloc[0, 1] = 'cannot edit immutable preparation'
        detached = model.document_frame()
        detached.iloc[0, 1] = 'detached edit'
        self.assertEqual(detached.iloc[0, 1], 'detached edit')
        pd.testing.assert_frame_equal(prepared['document'], frame)
        pd.testing.assert_frame_equal(model.document_frame(), frame)
        pd.testing.assert_frame_equal(source.frame, frame)
        values = source.frame.to_numpy(copy=False)
        self.assertFalse(values.flags.writeable)
        with self.assertRaises(ValueError):
            values.flags.writeable = True

    def test_detached_equal_or_mutated_sources_keep_full_value_validation(self):
        frame = pd.DataFrame({'Die Seq': ['01', '02'], 'CD': ['1.0000', '2']})
        model = self.model(frame)
        source = model._literal_source()
        self.assertIsNone(model._literal_source(frame))
        original = LiteralTableVersion.matches_frame
        calls = []
        def record(version, incoming):
            calls.append(incoming)
            return original(version, incoming)
        with patch.object(LiteralTableVersion, 'matches_frame', record):
            equal = prepare_sheet_version(frame.copy(), source.version, source=source)
            changed = frame.copy()
            changed.iloc[0, 1] = '9.99999999999999'
            self.assertIsNone(prepare_sheet_version(changed, source.version, source=source))
        self.assertIsNotNone(equal)
        self.assertEqual(len(calls), 2)
        other = source.version.replace_cells({(1, 1): 'different version'})
        self.assertFalse(source.matches(source.frame, other))
        self.assertIsNone(prepare_sheet_version(source.frame, other, source=source))

    def test_metadata_row_order_and_array_region_changes_reject_the_proof(self):
        frame = pd.DataFrame({'Die Seq': ['01', '02', '03'], 'CD': ['1', '2', '3']})
        model = self.model(frame)
        source = model._literal_source()
        candidates = [source.frame.iloc[::-1], source.frame.iloc[1:],
                      source.frame.rename(columns={'CD': 'Other'})]
        metadata = source.frame.copy(deep=False)
        metadata.attrs['source_rows'] = [8, 3, 1]
        candidates.append(metadata)
        index = source.frame.copy(deep=False)
        index.index = pd.Index([2, 0, 1])
        candidates.append(index)
        for candidate in candidates:
            with self.subTest(columns=tuple(candidate.columns), index=tuple(candidate.index)):
                self.assertFalse(source.matches(candidate, source.version))
                self.assertIsNone(model._literal_source(candidate))

    def test_unknown_cell_write_drops_current_proof_but_not_old_readonly_source(self):
        frame = pd.DataFrame({'Die Seq': ['01', '02'], 'CD': ['1.0000', '2']})
        model = self.model(frame)
        source = model._literal_source()
        model.cells[(1, 1)] = '7.00000000000001'
        self.assertIsNone(model._literal_source())
        self.assertIsNone(model._literal_source(source.frame))
        pd.testing.assert_frame_equal(source.frame, frame)
        self.assertEqual(model.document_frame().iloc[0, 1], '7.00000000000001')

    def test_dense_paste_undo_redo_keeps_versions_and_old_sources_isolated(self):
        frame = fixture(200, 56).raw.copy()
        model = self.model(frame)
        old = model._literal_source()
        incoming = frame.iloc[:, 6:].map(lambda value: f'{float(value) + .125:.15f}')
        self.assertTrue(model._paste_value_matrix(incoming.values.tolist(), 1, 6))
        changed = model._literal_source()
        self.assertIsNot(changed.version, old.version)
        for action, expected in ((model.undo.undo, frame),
                                 (model.undo.redo, frame.assign(**incoming.to_dict('list')))):
            action()
            current = model._literal_source()
            self.assertTrue(current.matches(current.frame, current.version))
            pd.testing.assert_frame_equal(current.frame, expected)
            pd.testing.assert_frame_equal(old.frame, frame)
        np.testing.assert_array_equal(changed.frame['P0'], incoming['P0'])

    def test_ordinary_nonversioned_models_keep_existing_preparation(self):
        model = SheetModel()
        self.addCleanup(model.deleteLater)
        model.load(pd.DataFrame({'CD': ['1.0000', '']}))
        self.assertIsNone(model._literal_source())

    def test_worker_proof_keeps_child_editor_and_parent_values_independent(self):
        frame = pd.DataFrame({'Wafer ID': ['001', '001'], 'Die Seq': ['01', '02'],
                              'CD': ['1.23000000000000001', '2.0000']})
        parent = self.model(frame)
        source = parent._literal_source()
        request = {'book': None, 'raw': source.frame, 'raw_version': source.version,
                   'raw_source': source, 'generation': 7, 'inputs': None,
                   'children': [(1, 'correlation', 'preview', True, False,
                                 {'include_fit_quality': True, 'carded': False})]}
        with patch.object(LiteralTableVersion, 'matches_frame',
                          side_effect=AssertionError('Worker rescanned a proved source')):
            result = prepare_linked_sources(request, lambda: False)
        prepared = result['tables'][1]
        child = SheetModel()
        self.addCleanup(child.deleteLater)
        child._load_prepared_frame(prepared)
        child.edit({(1, 2): 'independent child edit'})
        pd.testing.assert_frame_equal(parent.document_frame(), frame)
        pd.testing.assert_frame_equal(source.frame, frame)
        self.assertEqual(child.document_frame().iloc[0, 2], 'independent child edit')

    def test_unchanged_normalization_keeps_proved_region_but_general_cases_fall_back(self):
        cases = [
            (pd.DataFrame({'Die Seq': ['01', '02'], 'CD': ['1.0000', '2']}), False, True),
            (pd.DataFrame({'Die Seq': ['01', '  '], 'CD': ['1.0000', '  ']}), False, False),
            (pd.DataFrame({'Die Seq': ['01', '  '], 'CD': ['1.0000', '  ']}), True, True),
            (pd.DataFrame({'Die Seq': ['01', '02'], 'CD': ['  ', '  ']}), True, False),
            (pd.DataFrame({'Die Seq': ['01', '02'], ' CD ': ['1.0000', '2']}), True, False),
        ]
        for frame, preserve, shares_region in cases:
            with self.subTest(columns=tuple(frame.columns), preserve_rows=preserve):
                model = self.model(frame)
                source = model._literal_source()
                headers = model.headers()
                expected = MatchingWindow._analysis_input_frame(
                    frame, headers=headers, preserve_rows=preserve)
                actual = MatchingWindow._analysis_input_frame(
                    source.frame, headers=headers, preserve_rows=preserve, source=source)
                pd.testing.assert_frame_equal(actual, expected)
                self.assertEqual(np.shares_memory(actual.to_numpy(copy=False),
                                                 source.frame.to_numpy(copy=False)), shares_region)
                pd.testing.assert_frame_equal(source.frame, frame)

    def test_unknown_cached_metadata_does_not_raise_or_issue_a_proof(self):
        model = self.model(pd.DataFrame({'CD': ['1.0000', '2.0000']}))
        model._frames['document'].attrs['unexpected'] = object()
        self.assertIsNone(model._literal_source())

    def test_both_pandas_copy_modes_preserve_old_source_through_value_and_ordinary_edits(self):
        for enabled in (False, True):
            with self.subTest(copy_on_write=enabled), pd.option_context('mode.copy_on_write', enabled):
                frame = fixture(200, 56).raw.copy()
                model = self.model(frame)
                source = model._literal_source()
                normalized = MatchingWindow._analysis_input_frame(
                    source.frame, headers=model.headers(), source=source)
                changed = frame.iloc[:, 6:].map(lambda value: f'{float(value) + .125:.15f}')
                self.assertTrue(model._paste_value_matrix(changed.values.tolist(), 1, 6))
                model.undo.undo()
                model.undo.redo()
                model.edit({(2, 7): 'ordinary edit'})
                pd.testing.assert_frame_equal(normalized, frame)
                pd.testing.assert_frame_equal(source.frame, frame)
                public = model.document_frame()
                public.iloc[0, 6] = 'public edit'
                self.assertNotEqual(model.document_frame().iloc[0, 6], 'public edit')
