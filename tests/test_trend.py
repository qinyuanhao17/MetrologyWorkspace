import unittest

import numpy as np
import pandas as pd

from metrology_app.trend import overlay_series, overlay_spec, parse_unit


class TrendLogicTests(unittest.TestCase):
    def test_same_unit_parameters_share_one_axis(self):
        spec = overlay_spec("DP [nm]", "EW [nm]", [1, 2], [20, 30])
        self.assertEqual(spec["kind"], "shared")
        self.assertFalse(spec["magnitude_warning"])

    def test_unknown_units_use_a_second_axis(self):
        spec = overlay_spec("DP", "EW", [1, 2], [2, 3])
        self.assertEqual(spec["kind"], "second-axis")
        self.assertIsNone(spec["unit"])
        self.assertIsNone(spec["secondary_unit"])

    def test_unit_suffix_is_parsed_from_brackets_and_parentheses(self):
        self.assertEqual(parse_unit("DP [ nm ]"), "nm")
        self.assertEqual(parse_unit("EW (V)"), "V")
        self.assertIsNone(parse_unit("TG"))

    def test_large_magnitude_gap_sets_warning_without_changing_axis_choice(self):
        spec = overlay_spec("DP [nm]", "EW [V]", [1, 2], [100, 200])
        self.assertEqual(spec["kind"], "second-axis")
        self.assertTrue(spec["magnitude_warning"])

    def test_overlay_series_preserves_nan_without_interpolation(self):
        frame = pd.DataFrame({"DP": [1.0, np.nan, 3.0, 4.0]})
        series = overlay_series(frame, {"W1": (0, 1, 2), "W2": (3,)}, "DP", ("W1", "W2"))
        self.assertEqual([item["key"] for item in series], ["W1", "W2"])
        np.testing.assert_array_equal(series[0]["x"], np.asarray([0.0, 1.0, 2.0]))
        self.assertTrue(np.isnan(series[0]["y"][1]))
        self.assertEqual(series[1]["y"].tolist(), [4.0])


if __name__ == "__main__":
    unittest.main()
