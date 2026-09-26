"""Card matching workflow tests through its public interface."""

from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from metrology_app.matching import MatchWorkbook, ParameterMapping, extrema_sample_indices


class MatchWorkbookTests(unittest.TestCase):
    def reference(self):
        return pd.DataFrame({
            "Wafer ID": ["W1", "W1", "W2"],
            "CD_Bot Reference": [12.0, 22.0, 32.0],
            "SPA Reference": [5.0, 7.0, 9.0],
        })

    def raw(self):
        return pd.DataFrame({
            "Wafer ID": ["W1", "W1", "W2"],
            "CD_Bot": [1.0, 2.0, 3.0],
            "SPA": [2.0, 3.0, 4.0],
        })

    def test_suggests_each_reference_parameter_to_its_raw_column(self):
        mappings = MatchWorkbook.suggest_mappings(self.reference(), self.raw())
        self.assertEqual(
            mappings,
            (
                ParameterMapping("CD_Bot", "CD_Bot Reference", "CD_Bot"),
                ParameterMapping("SPA", "SPA Reference", "SPA"),
            ),
        )

    def test_preview_generates_one_card_per_parameter_and_applies_it_lazily(self):
        workbook = MatchWorkbook(
            reference=self.reference(),
            raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(self.reference(), self.raw()),
            match_type="KLA",
            result_mode="preview",
        )

        result = workbook.analyze()

        self.assertEqual(result.parameter_names, ("CD_Bot", "SPA"))
        self.assertEqual(result.summary["Slope"].tolist(), [10.0, 2.0])
        self.assertEqual(result.summary["Intercept"].tolist(), [2.0, 1.0])
        self.assertEqual(result.summary["R²"].tolist(), [1.0, 1.0])
        cd = result.series("CD_Bot")
        np.testing.assert_allclose(cd["Card Value"], [12.0, 22.0, 32.0])
        np.testing.assert_allclose(cd["Evaluated Value"], [12.0, 22.0, 32.0])
        np.testing.assert_allclose(cd["Bias"], [0.0, 0.0, 0.0])

    def test_final_validates_already_carded_values_without_applying_another_card(self):
        reference = pd.DataFrame({"CD Reference": [10.0, 20.0, 30.0]})
        raw = pd.DataFrame({"CD": [11.0, 19.0, 31.0]})
        workbook = MatchWorkbook(
            reference=reference,
            raw=raw,
            mappings=(ParameterMapping("CD", "CD Reference", "CD"),),
            match_type="TEM",
            result_mode="final",
        )

        result = workbook.analyze()
        series = result.series("CD")

        np.testing.assert_allclose(series["Evaluated Value"], raw["CD"])
        np.testing.assert_allclose(series["Bias"], [1.0, -1.0, 1.0])
        self.assertNotEqual(result.summary.loc[0, "Slope"], 1.0)

    def test_percentage_bias_is_nan_when_reference_is_zero(self):
        reference = pd.DataFrame({"CD Reference": [0.0, 10.0, 20.0]})
        raw = pd.DataFrame({"CD": [1.0, 12.0, 18.0]})
        workbook = MatchWorkbook(
            reference=reference,
            raw=raw,
            mappings=(ParameterMapping("CD", "CD Reference", "CD"),),
            result_mode="final",
            bias_mode="percent",
        )

        series = workbook.analyze().series("CD")

        self.assertTrue(np.isnan(series.loc[0, "Bias %"]))
        np.testing.assert_allclose(series.loc[1:, "Selected Bias"], [20.0, -10.0])

    def test_reports_slope_and_r_squared_for_each_wafer(self):
        reference = pd.DataFrame({
            "Wafer ID": ["W1"] * 3 + ["W2"] * 3,
            "CD Reference": [3.0, 5.0, 7.0, 1.0, 4.0, 7.0],
        })
        raw = pd.DataFrame({
            "Wafer ID": ["W1"] * 3 + ["W2"] * 3,
            "CD": [1.0, 2.0, 3.0, 1.0, 2.0, 3.0],
        })
        workbook = MatchWorkbook(
            reference=reference,
            raw=raw,
            mappings=(ParameterMapping("CD", "CD Reference", "CD"),),
            match_type="NOVA",
        )

        wafers = workbook.analyze().wafer_summary("CD")

        self.assertEqual(wafers["Wafer"].tolist(), ["W1", "W2"])
        np.testing.assert_allclose(wafers["Slope"], [2.0, 3.0])
        np.testing.assert_allclose(wafers["Intercept"], [1.0, -2.0])
        np.testing.assert_allclose(wafers["R²"], [1.0, 1.0])
    def test_rejects_row_order_input_with_different_lengths(self):
        with self.assertRaisesRegex(ValueError, "same number of rows"):
            MatchWorkbook(
                reference=self.reference(),
                raw=self.raw().iloc[:2],
                mappings=(ParameterMapping("CD_Bot", "CD_Bot Reference", "CD_Bot"),),
            )

    def test_plot_sampling_keeps_local_extrema_without_changing_analysis_data(self):
        values = np.zeros(1_000)
        values[555] = -80.0
        values[777] = 120.0

        indices = extrema_sample_indices(values, limit=40)

        self.assertLessEqual(len(indices), 40)
        self.assertEqual(indices[0], 0)
        self.assertEqual(indices[-1], 999)
        self.assertIn(555, indices)
        self.assertIn(777, indices)
    def test_enforces_the_declared_row_and_parameter_capacity(self):
        too_many_rows = pd.DataFrame({"CD Reference": np.zeros(100_001)})
        too_many_raw_rows = pd.DataFrame({"CD": np.zeros(100_001)})
        with self.assertRaisesRegex(ValueError, "100,000 rows"):
            MatchWorkbook(
                too_many_rows,
                too_many_raw_rows,
                (ParameterMapping("CD", "CD Reference", "CD"),),
            )

        raw = pd.DataFrame({f"P{i}": [1.0, 2.0] for i in range(51)})
        reference = pd.DataFrame({f"P{i} Reference": [1.0, 2.0] for i in range(51)})
        mappings = tuple(
            ParameterMapping(f"P{i}", f"P{i} Reference", f"P{i}") for i in range(51)
        )
        with self.assertRaisesRegex(ValueError, "50 parameters"):
            MatchWorkbook(reference, raw, mappings)
    def test_wkb_round_trip_preserves_source_tables_and_settings(self):
        workbook = MatchWorkbook(
            reference=self.reference(),
            raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(self.reference(), self.raw()),
            match_type="NOVA",
            result_mode="preview",
            bias_mode="percent",
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "analysis.wkb"
            workbook.save(path)
            restored = MatchWorkbook.load(path)

        pd.testing.assert_frame_equal(restored.reference, workbook.reference)
        pd.testing.assert_frame_equal(restored.raw, workbook.raw)
        self.assertEqual(restored.mappings, workbook.mappings)
        self.assertEqual(restored.match_type, "NOVA")
        self.assertEqual(restored.result_mode, "preview")
        self.assertEqual(restored.bias_mode, "percent")
        self.assertEqual(restored.analyze().summary["Parameter"].tolist(), ["CD_Bot", "SPA"])


if __name__ == "__main__":
    unittest.main()