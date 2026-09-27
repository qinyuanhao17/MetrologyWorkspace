"""Card matching workflow tests through its public interface."""

from contextlib import closing
from pathlib import Path
import sqlite3
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

    def test_preview_stage_applies_the_match_card_to_separate_fullmap_rows(self):
        preview_raw = pd.DataFrame({
            "Wafer ID": ["FULL-01", "FULL-01", "FULL-02", "FULL-02"],
            "X": [-10.0, 10.0, -10.0, 10.0],
            "Y": [0.0, 0.0, 5.0, 5.0],
            "CD_Bot": [4.0, 5.0, 6.0, 7.0],
            "SPA": [5.0, 6.0, 7.0, 8.0],
        })
        workbook = MatchWorkbook(
            reference=self.reference(),
            raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(self.reference(), self.raw()),
            match_type="TEM",
            preview_raw=preview_raw,
        )

        stage = workbook.stage_frame("preview")

        self.assertEqual(stage["Wafer ID"].tolist(), preview_raw["Wafer ID"].tolist())
        self.assertEqual(stage["X"].tolist(), preview_raw["X"].tolist())
        self.assertEqual(stage["Y"].tolist(), preview_raw["Y"].tolist())
        np.testing.assert_allclose(stage["CD_Bot"], [42.0, 52.0, 62.0, 72.0])
        np.testing.assert_allclose(stage["SPA"], [11.0, 13.0, 15.0, 17.0])

    def test_final_stage_uses_separate_already_carded_fullmap_without_reapplying_card(self):
        final_raw = pd.DataFrame({
            "Wafer ID": ["FINAL-01", "FINAL-01"],
            "X": [-2.0, 2.0],
            "Y": [0.0, 0.0],
            "CD_Bot": [101.5, 102.5],
            "SPA": [8.25, 8.75],
        })
        workbook = MatchWorkbook(
            reference=self.reference(),
            raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(self.reference(), self.raw()),
            final_raw=final_raw,
        )

        stage = workbook.stage_frame("final")

        pd.testing.assert_frame_equal(stage, final_raw)

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

    def test_wafer_summary_uses_raw_data_measurement_identity(self):
        reference = pd.DataFrame({
            "CD Reference": [12.0, 22.0, 32.0, 42.0],
        })
        raw = pd.DataFrame({
            "Wafer ID": ["W1", "W1", "W1", "W1"],
            "Lot ID": ["L1", "L1", "L2", "L2"],
            "PAD Name": ["P1", "P1", "P2", "P2"],
            "Die Seq": [1, 2, 1, 2],
            "CD": [1.0, 2.0, 3.0, 4.0],
        })
        workbook = MatchWorkbook(
            reference,
            raw,
            [ParameterMapping("CD", "CD Reference", "CD")],
        )

        wafers = workbook.analyze().wafer_summary("CD")

        self.assertEqual(
            wafers["Wafer"].tolist(),
            ["W1\nPAD: P1\nLot: L1", "W1\nPAD: P2\nLot: L2"],
        )
        self.assertEqual(wafers["Valid pairs"].tolist(), [2, 2])
        self.assertEqual(
            workbook.analyze().measurement_ticks(),
            (
                (1.5, "W1\nPAD: P1\nLot: L1"),
                (3.5, "W1\nPAD: P2\nLot: L2"),
            ),
        )

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
        preview_raw = pd.DataFrame({
            "Wafer ID": ["P1", "P1"],
            "CD_Bot": [4.0, 5.0],
            "SPA": [5.0, 6.0],
        })
        final_raw = pd.DataFrame({
            "Wafer ID": ["F1", "F1"],
            "CD_Bot": [41.0, 51.0],
            "SPA": [11.0, 13.0],
        })
        workbook = MatchWorkbook(
            reference=self.reference(),
            raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(self.reference(), self.raw()),
            match_type="NOVA",
            result_mode="preview",
            bias_mode="percent",
            bias_views=("absolute", "percent"),
            preview_raw=preview_raw,
            final_raw=final_raw,
            setup_splitter_sizes=(320, 480, 1600),
            parameter_order=("SPA", "CD_Bot"),
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "analysis.wkb"
            workbook.save(path)
            restored = MatchWorkbook.load(path)

        pd.testing.assert_frame_equal(restored.reference, workbook.reference)
        pd.testing.assert_frame_equal(restored.raw, workbook.raw)
        pd.testing.assert_frame_equal(restored.preview_raw, preview_raw)
        pd.testing.assert_frame_equal(restored.final_raw, final_raw)
        self.assertEqual(restored.mappings, workbook.mappings)
        self.assertEqual(restored.match_type, "NOVA")
        self.assertEqual(restored.result_mode, "preview")
        self.assertEqual(restored.bias_mode, "percent")
        self.assertEqual(restored.bias_views, ("absolute", "percent"))
        self.assertEqual(restored.setup_splitter_sizes, (320, 480, 1600))
        self.assertEqual(restored.parameter_order, ("SPA", "CD_Bot"))
        self.assertEqual(restored.analyze().summary["Parameter"].tolist(), ["CD_Bot", "SPA"])

    def test_schema_one_wkb_still_opens_without_fullmap_stage_tables(self):
        workbook = MatchWorkbook(
            reference=self.reference(),
            raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(self.reference(), self.raw()),
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.wkb"
            workbook.save(path)
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("UPDATE metadata SET schema_version = 1")
                connection.execute(
                    """CREATE TABLE legacy_metadata AS
                       SELECT schema_version, match_type, result_mode, bias_mode,
                              bias_views, saved_utc
                       FROM metadata"""
                )
                connection.execute("DROP TABLE metadata")
                connection.execute("ALTER TABLE legacy_metadata RENAME TO metadata")
            restored = MatchWorkbook.load(path)

        pd.testing.assert_frame_equal(restored.reference, workbook.reference)
        pd.testing.assert_frame_equal(restored.raw, workbook.raw)
        self.assertIsNone(restored.preview_raw)
        self.assertIsNone(restored.final_raw)
        self.assertIsNone(restored.setup_splitter_sizes)
        self.assertEqual(restored.parameter_order, ("CD_Bot", "SPA"))


if __name__ == "__main__":
    unittest.main()
