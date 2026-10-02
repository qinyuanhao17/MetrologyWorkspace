import unittest

import numpy as np
import pandas as pd

from metrology_app.trend import overlay_series, overlay_spec, parse_unit


class TrendLogicTests(unittest.TestCase):
    def test_same_unit_parameters_share_one_axis(self):
        spec = overlay_spec("DP [nm]", "EW [nm]", [1, 2], [2, 3])
        self.assertEqual(spec["kind"], "shared")

    def test_unnamed_parameters_share_the_nanometre_axis(self):
        spec = overlay_spec("DP", "EW", [1, 2], [2, 3])
        self.assertEqual(spec["kind"], "shared")
        self.assertEqual((spec["unit"], spec["secondary_unit"]), ("nm", "nm"))

    def test_unit_suffix_is_parsed_from_brackets_and_parentheses(self):
        self.assertEqual(parse_unit("DP [ nm ]"), "nm")
        self.assertEqual(parse_unit("EW (V)"), "V")
        self.assertEqual(parse_unit("TG"), "nm")

    def test_ocd_names_carry_their_industry_units(self):
        self.assertEqual(parse_unit("Si_SWA1"), "degree")
        self.assertEqual(parse_unit("SWA"), "degree")
        self.assertEqual(parse_unit("ASi_Top_HTRatio"), "1")
        self.assertEqual(parse_unit("M1_ratio"), "1")
        self.assertEqual(parse_unit("ASi_BCD"), "nm")
        self.assertEqual(parse_unit("MCD_TOP"), "nm")
        self.assertEqual(parse_unit("TEOX_THK"), "nm")

    def test_explicit_suffix_wins_over_the_name_rule(self):
        self.assertEqual(parse_unit("Si_SWA [rad]"), "rad")
        self.assertEqual(parse_unit("EW (V)"), "V")

    def test_angles_and_lengths_use_a_second_axis(self):
        spec = overlay_spec("Si_SWA1", "ASi_BCD", [80, 85], [1, 2])
        self.assertEqual(spec["kind"], "second-axis")
        self.assertEqual((spec["unit"], spec["secondary_unit"]), ("degree", "nm"))

    def test_ratios_are_dimensionless(self):
        spec = overlay_spec("M1_ratio", "ASi_BCD", [.001, .002], [1, 2])
        self.assertEqual(spec["kind"], "second-axis")
        self.assertEqual((spec["unit"], spec["secondary_unit"]), ("1", "nm"))

    def test_different_units_use_a_second_axis_regardless_of_scale(self):
        spec = overlay_spec("DP [nm]", "EW [V]", [1, 2], [100, 200])
        self.assertEqual(spec["kind"], "second-axis")

    def test_same_unit_parameters_with_a_large_gap_split_the_axes(self):
        spec = overlay_spec("ASi_BCD", "MCD_TOP", [1000, 1200], [0.5, 0.6])
        self.assertEqual(spec["kind"], "second-axis")
        self.assertEqual((spec["unit"], spec["secondary_unit"]), ("nm", "nm"))

    def test_same_unit_parameters_with_comparable_values_share_one_axis(self):
        spec = overlay_spec("ASi_BCD", "MCD_TOP", [100, 120], [95, 110])
        self.assertEqual(spec["kind"], "shared")

    def test_decimal_ratio_threshold_changes_automatic_split(self):
        primary, secondary = [80, 88], [10, 11]
        self.assertEqual(
            overlay_spec("ASi_BCD", "MCD_TOP", primary, secondary,
                         ratio_limit=8.5)["kind"],
            "shared",
        )
        self.assertEqual(
            overlay_spec(
                "ASi_BCD", "MCD_TOP", primary, secondary,
                ratio_limit=7.5
            )["kind"],
            "second-axis",
        )

    def test_always_two_axes_overrides_matching_units(self):
        spec = overlay_spec("DP", "EW", [1, 2], [2, 3], axis_mode="dual")
        self.assertEqual(spec["kind"], "second-axis")

    def test_always_one_axis_overrides_different_units_and_marks_them(self):
        spec = overlay_spec("DP [nm]", "SWA [degree]", [1, 2], [30, 40],
                            axis_mode="single")
        self.assertEqual(spec["kind"], "shared")
        self.assertTrue(spec["mixed_units"])

    def test_overlay_series_preserves_nan_without_interpolation(self):
        frame = pd.DataFrame({"DP": [1.0, np.nan, 3.0, 4.0]})
        series = overlay_series(frame, {"W1": (0, 1, 2), "W2": (3,)}, "DP", ("W1", "W2"))
        self.assertEqual([item["key"] for item in series], ["W1", "W2"])
        np.testing.assert_array_equal(series[0]["x"], np.asarray([0.0, 1.0, 2.0]))
        self.assertTrue(np.isnan(series[0]["y"][1]))
        self.assertEqual(series[1]["y"].tolist(), [4.0])


if __name__ == "__main__":
    unittest.main()
