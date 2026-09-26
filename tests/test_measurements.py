"""Automatic measurement identity and conservative Die Seq inference."""
import unittest

import numpy as np
import pandas as pd

from metrology_app.array_plot import ArrayOptions, prepare_array
from metrology_app.measurements import default_identity_columns, detect_measurements, sequence_runs


class MeasurementTests(unittest.TestCase):
    def test_default_identity_keeps_pad_only_when_it_varies(self):
        constant_pad = pd.DataFrame({"Wafer ID": ["W1", "W1", "W2", "W2"],
                                     "Lot ID": ["L1", "L1", "L2", "L2"],
                                     "PAD Name": ["CELL"] * 4,
                                     "Die Seq": [1, 2, 1, 2]})
        self.assertEqual(default_identity_columns(constant_pad, "Wafer ID", "Lot ID", "PAD Name"),
                         ["Wafer ID", "Lot ID"])
        varying_pad = constant_pad.assign(**{"PAD Name": ["A", "B", "A", "B"]})
        self.assertEqual(default_identity_columns(varying_pad, "Wafer ID", "Lot ID", "PAD Name"),
                         ["Wafer ID", "Lot ID", "PAD Name"])
        single_wafer = pd.DataFrame({"Wafer ID": ["w"] * 3, "Lot ID": ["L"] * 3,
                                     "PAD Name": ["T"] * 3, "Die Seq": [1, 3, 7]})
        self.assertEqual(default_identity_columns(single_wafer, "Wafer ID", "Lot ID", "PAD Name"),
                         ["Wafer ID"])

    def test_lot_and_pad_are_part_of_identity(self):
        frame = pd.DataFrame({'Wafer ID': ['001'] * 4, 'Lot ID': ['L1', 'L1', 'L2', 'L2'],
                              'PAD Name': ['P1', 'P2', 'P1', 'P2'], 'Die Seq': [1] * 4})
        groups = detect_measurements(frame, 'Wafer ID')
        self.assertEqual(len(groups), 4)
        self.assertEqual(len({g.key for g in groups}), 4)
        self.assertTrue(all('Lot:' in g.label and 'PAD:' in g.label for g in groups))
        self.assertEqual([g.rows for g in groups], [(0,), (1,), (2,), (3,)])

    def test_aliases_blanks_and_text_ids(self):
        frame = pd.DataFrame({'Sample': ['001', '001', '001', '002', ''],
                              'LOT_ID': ['L'] * 5, 'PadName': ['P', '', None, 'P', 'P']})
        groups = detect_measurements(frame, 'Sample')
        self.assertEqual([g.rows for g in groups], [(0,), (1, 2), (3,)])
        self.assertEqual(groups[0].wafer, '001')
        self.assertIn('(blank)', groups[1].label)
        self.assertEqual(detect_measurements(frame, 'Missing'), [])

    def test_die_seq_restarts_create_runs_not_one_map_per_die(self):
        frame = pd.DataFrame({'Wafer': ['W'] * 9, 'Die Seq': [1, 2, 3] * 3})
        groups = detect_measurements(frame, 'Wafer')
        self.assertEqual([g.rows for g in groups], [(0, 1, 2), (3, 4, 5), (6, 7, 8)])
        self.assertIn('Run 2', groups[1].label)
        self.assertIn('inferred', groups[1].detail)
        frame['PAD Name'] = ['A'] * 3 + ['B'] * 3 + ['C'] * 3
        groups = detect_measurements(frame, 'Wafer')
        self.assertEqual(len(groups), 3)
        self.assertTrue(all('Run ' not in g.label for g in groups))

    def test_missing_die_numbers_and_missing_run_start(self):
        frame = pd.DataFrame({'Wafer': ['W'] * 6, 'Die Seq': [2, 5, 9, 3, 6, 10]})
        groups = detect_measurements(frame, 'Wafer')
        self.assertEqual([g.rows for g in groups], [(0, 1, 2), (3, 4, 5)])
        self.assertEqual(len(sequence_runs(pd.Series([1, 3, 5, 8, 10, 12]))), 1)

    def test_explicit_grouping_columns(self):
        frame = pd.DataFrame({'Wafer ID': ['W'] * 4, 'Lot ID': ['L'] * 4,
                              'PAD Name': ['P1', 'P1', 'P2', 'P2']})
        self.assertEqual(len(detect_measurements(frame, 'Wafer ID')), 2)
        groups = detect_measurements(frame, 'Wafer ID', ['Wafer ID'])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].rows, (0, 1, 2, 3))
        frame['Die Seq'] = [2, 4, 3, 5]
        self.assertEqual(len(detect_measurements(frame, 'Wafer ID', ['Wafer ID'], use_die_seq=False)), 1)

    def test_shuffled_or_ambiguous_sequences_are_not_split(self):
        for values in ([3, 2, 1, 6, 5, 4], [1, 1, 2, 2, 3, 3], [1, 3, 2, 1, 2, 3],
                       [1, 2, 4, 3, 5, 6],
                       [1, 2, 3, 1, 2, np.nan], [1] * 6, [1, 2, 3, 4, 5, 6]):
            self.assertEqual(len(sequence_runs(pd.Series(values))), 1, values)

    def test_nondefault_index_and_interleaved_rows(self):
        frame = pd.DataFrame({'W': ['A', 'B', 'A', 'B'], 'PAD Name': ['P'] * 4}, index=[9, 7, 5, 3])
        groups = detect_measurements(frame, 'W')
        self.assertEqual([g.rows for g in groups], [(0, 2), (1, 3)])
        self.assertEqual(groups[0].key, detect_measurements(frame.iloc[[0, 2, 1, 3]], 'W')[0].key)

    def test_identity_keys_do_not_collide_on_separators(self):
        frame = pd.DataFrame({'W': ['A|B', 'A'], 'Lot': ['C', 'B|C']})
        self.assertEqual(len({g.key for g in detect_measurements(frame, 'W')}), 2)

    def test_group_rows_reach_the_correct_maps(self):
        frame = pd.DataFrame({'W': ['W'] * 6, 'PAD Name': ['A'] * 3 + ['B'] * 3,
                              'Die Seq': [1, 2, 3] * 2, 'X': [0, 1, 0] * 2,
                              'Y': [0, 0, 1] * 2, 'V': [1, 2, 3, 10, 20, 30]}, index=[20, 21, 22, 30, 31, 32])
        groups = detect_measurements(frame, 'W')
        selection = {'wafers': [g.key for g in groups], 'wafer_column': 'W', 'metrics': ['V'],
                     'groups': {g.key: g.rows for g in groups}, 'labels': {g.key: g.label for g in groups}}
        result = prepare_array(frame, selection, ArrayOptions('X', 'Y'))
        self.assertEqual(result['shape'], (2, 1))
        self.assertEqual(result['scenes'][0]['layer'].value.tolist(), [1, 2, 3])
        self.assertEqual(result['scenes'][1]['layer'].value.tolist(), [10, 20, 30])
        self.assertIn('PAD: B', result['scenes'][1]['label'])


if __name__ == '__main__':
    unittest.main()
