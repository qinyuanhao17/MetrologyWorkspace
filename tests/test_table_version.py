"""Immutable literal table versions are independent of Qt and persistence."""
import unittest

import pandas as pd

from metrology_app.table_version import LiteralTableVersion


class LiteralTableVersionTests(unittest.TestCase):
    def frame(self):
        frame = pd.DataFrame([['001', '1.23000000000000000001', ''],
                              ['001', '-0', '1e-19'], ['', ' ', 'NA']],
                             columns=['Wafer ID', 'Value', 'Value'])
        frame.attrs = {'source': {'rows': [8, 3, 8], 'names': ('RAW', 'REF')}}
        return frame

    def test_exact_literals_duplicate_headers_blank_rows_and_attributes_round_trip(self):
        frame = self.frame()
        version = LiteralTableVersion.from_frame(frame)
        restored = version.to_frame()
        pd.testing.assert_frame_equal(restored, frame)
        self.assertEqual(restored.attrs, frame.attrs)
        self.assertEqual(version.row_count, 3)
        self.assertEqual(version.headers, ('Wafer ID', 'Value', 'Value'))
        self.assertEqual(version.cell(1, 1), '1.23000000000000000001')
        self.assertEqual(version.cell(2, 1), '-0')

    def test_input_and_public_read_mutations_do_not_change_any_version(self):
        frame = self.frame()
        version = LiteralTableVersion.from_frame(frame)
        frame.iat[0, 1] = 'external'
        frame.attrs['source']['rows'].append(99)
        read = version.to_frame()
        read.iat[0, 1] = 'another external mutation'
        read.attrs['source']['rows'][0] = -1
        self.assertEqual(version.cell(1, 1), '1.23000000000000000001')
        self.assertEqual(version.to_frame().attrs['source']['rows'], [8, 3, 8])
        with self.assertRaises((AttributeError, TypeError)):
            version.headers = ('corrupt',)
        with self.assertRaises(TypeError):
            version.columns[0][0] = 'corrupt'

    def test_new_versions_share_only_unchanged_immutable_columns(self):
        original = LiteralTableVersion.from_frame(self.frame())
        edited = original.replace_cells({(2, 1): '0002.34000000000000009'})
        self.assertIs(original.columns[0], edited.columns[0])
        self.assertIs(original.columns[2], edited.columns[2])
        self.assertIsNot(original.columns[1], edited.columns[1])
        self.assertEqual(original.cell(2, 1), '-0')
        self.assertEqual(edited.cell(2, 1), '0002.34000000000000009')
        replacement = ['x', 'y', 'z']
        next_version = edited.replace_columns({2: replacement})
        replacement[0] = 'mutated after commit'
        self.assertEqual(next_version.cell(1, 2), 'x')
        self.assertEqual(edited.cell(1, 2), '')

    def test_snapshot_cells_keep_original_empty_tail_marker(self):
        frame = pd.DataFrame([['001', '1'], ['', '']], columns=['ID', 'Value'])
        version = LiteralTableVersion.from_frame(frame)
        self.assertEqual(version.to_cells(), {(0, 0): 'ID', (0, 1): 'Value',
                                              (1, 0): '001', (1, 1): '1', (2, 0): ''})

    def test_unrepresentable_values_and_schema_changes_are_explicit(self):
        with self.assertRaises(TypeError):
            LiteralTableVersion.from_frame(pd.DataFrame({'Value': [1.25]}))
        frame = self.frame()
        frame.attrs['opaque'] = object()
        with self.assertRaises(TypeError):
            LiteralTableVersion.from_frame(frame)
        version = LiteralTableVersion.from_frame(self.frame())
        for changes in ({(0, 1): 'New header'}, {(4, 1): 'grow'}, {(1, 9): 'grow'}):
            with self.subTest(changes=changes), self.assertRaises((KeyError, ValueError)):
                version.replace_cells(changes)
        with self.assertRaises(ValueError):
            version.replace_columns({1: ['wrong extent']})

    def test_empty_and_header_only_versions_preserve_their_shapes(self):
        for frame in (pd.DataFrame(), pd.DataFrame(columns=['ID', 'Value'])):
            with self.subTest(columns=list(frame)):
                version = LiteralTableVersion.from_frame(frame)
                pd.testing.assert_frame_equal(version.to_frame(), frame)
