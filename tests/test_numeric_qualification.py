"""Parameter qualification is existential, with the same full-column result."""
import unittest
import numpy as np
import pandas as pd
from metrology_app.data import inspect_table, number


class NumericQualificationTests(unittest.TestCase):
    def test_numeric_values_at_any_position_and_nonfinite_columns_keep_classification(self):
        frame = pd.DataFrame({
            "Wafer ID": ["001"] * 257,
            "First": ["1.000"] + ["text"] * 256,
            "Middle": [""] * 128 + ["-2.5000"] + ["NaN"] * 128,
            "Last": ["text"] * 256 + ["3e2"],
            "Nonfinite": ["inf", "-inf", "NaN", ""] * 64 + [np.nan],
            "Metadata": ["晶圆"] * 257,
        })
        expected = [column for column in frame if column != "Wafer ID"
                    and number(frame[column]).notna().any()]
        before = frame.copy(deep=True)
        self.assertEqual(inspect_table(frame)[2], expected)
        pd.testing.assert_frame_equal(frame, before)
