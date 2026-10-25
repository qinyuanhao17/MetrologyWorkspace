"""Input presence follows the original full string mask, without changing values."""
import random
from time import perf_counter
import unittest

import numpy as np
import pandas as pd

from metrology_app.matching_window import MatchingWindow


def original_mask(frame, headers, preserve_rows):
    text = frame.fillna('').astype(str)
    populated = text.apply(lambda column: column.str.strip().ne(''))
    keep = populated.any(axis=0).to_numpy()
    result = frame.iloc[:, keep].copy()
    result.columns = [name for name, used in zip(headers, keep) if used]
    if not preserve_rows:
        result = result.loc[populated.any(axis=1)]
    return result.reset_index(drop=True)


class AnalysisInputPresenceTests(unittest.TestCase):
    def test_high_precision_strings_whitespace_and_internal_blank_rows(self):
        frame = pd.DataFrame({'Wafer ID': [' W1 ', '', '\t', 'W2', ''],
                              'CD': ['1.123456789000000', '', ' ', '0', ''],
                              'Unnamed': ['', '', '', '', '2.000000000000001'],
                              'Empty': ['', ' ', '\t', '', '']})
        expected = frame.iloc[[0, 3, 4], :3].reset_index(drop=True)
        result = MatchingWindow._analysis_input_frame(frame, preserve_rows=False)
        pd.testing.assert_frame_equal(result, expected)
        self.assertEqual(result.CD.iloc[0], '1.123456789000000')
        self.assertEqual(result['Wafer ID'].iloc[0], ' W1 ')

    def test_random_literal_and_scalar_frames_match_original_mask_exactly(self):
        rng = random.Random(20261024)
        for values in (['', ' ', '\t', '\u2003', '0', 'nan', '测量', '1.234567890000'],
                       ['', None, np.nan, pd.NA, False, 0, 1.25, ' 1.000 ']):
            for _ in range(40):
                frame = pd.DataFrame([[rng.choice(values) for _ in range(7)] for _ in range(11)])
                names = ['Wafer', 'CD', 'Depth', 'A', 'B', 'C', 'D']
                before = frame.copy(deep=True)
                for preserve in (True, False):
                    actual = MatchingWindow._analysis_input_frame(frame, headers=names, preserve_rows=preserve)
                    pd.testing.assert_frame_equal(actual, original_mask(frame, names, preserve))
                pd.testing.assert_frame_equal(frame, before)

    def test_dense_100k_by_33_presence_check_is_prompt_on_first_call(self):
        frame = pd.DataFrame({f'C{i}': ['1.123456789000000']*100000 for i in range(33)})
        start = perf_counter()
        actual = MatchingWindow._analysis_input_frame(frame, preserve_rows=False)
        elapsed = perf_counter()-start
        self.assertLess(elapsed, .35, f'First input presence scan blocked for {elapsed:.3f}s')
        pd.testing.assert_frame_equal(actual, frame)
