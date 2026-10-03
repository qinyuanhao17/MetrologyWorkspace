"""Card matching workflow tests through its public interface."""

from contextlib import closing
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest

import numpy as np
import pandas as pd

from metrology_app.matching import MatchWorkbook, ParameterMapping, extrema_sample_indices
from tests.legacy_wkb import save_legacy


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

    def test_tem_map_does_not_fall_back_to_matching_raw_data(self):
        workbook = MatchWorkbook(
            reference=self.reference(),
            raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(self.reference(), self.raw()),
            match_type="TEM",
            final_match_raw=self.raw().assign(CD_Bot=[11.0, 19.0, 31.0]),
        )

        self.assertTrue(workbook.stage_frame("preview").empty)
        self.assertTrue(workbook.stage_frame("final").empty)

    def test_kla_and_nova_maps_default_to_matching_data(self):
        for match_type in ("KLA", "NOVA"):
            with self.subTest(match_type=match_type):
                workbook = MatchWorkbook(
                    reference=self.reference(),
                    raw=self.raw(),
                    mappings=MatchWorkbook.suggest_mappings(
                        self.reference(), self.raw()
                    ),
                    match_type=match_type,
                )

                stage = workbook.stage_frame("preview")
                self.assertEqual(
                    stage["CD_Bot"].tolist(), [12.0, 22.0, 32.0]
                )

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
        final_match_raw = self.raw().assign(CD_Bot=[11.0, 19.0, 31.0])
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
            final_match_raw=final_match_raw,
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
        pd.testing.assert_frame_equal(restored.final_match_raw, final_match_raw)
        self.assertEqual(restored.mappings, workbook.mappings)
        self.assertEqual(restored.match_type, "NOVA")
        self.assertEqual(restored.result_mode, "preview")
        self.assertEqual(restored.bias_mode, "percent")
        self.assertEqual(restored.bias_views, ("absolute", "percent"))
        self.assertEqual(restored.setup_splitter_sizes, (320, 480, 1600))
        self.assertEqual(restored.parameter_order, ("SPA", "CD_Bot"))
        self.assertEqual(restored.analyze().summary["Parameter"].tolist(), ["CD_Bot", "SPA"])

    def test_wkb_round_trip_preserves_exact_map_tables(self):
        preview_map = pd.DataFrame({
            "Wafer ID": ["MAP-1", "MAP-1"],
            "FIELD X": [-1, 1],
            "FIELD Y": [0, 0],
            "CD_Bot": [101.5, 102.5],
        })
        final_map = pd.DataFrame()
        workbook = MatchWorkbook(
            reference=self.reference(),
            raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(self.reference(), self.raw()),
            preview_map=preview_map,
            final_map=final_map,
        )

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "map-snapshot.wkb"
            workbook.save(path)
            restored = MatchWorkbook.load(path)

        pd.testing.assert_frame_equal(restored.preview_map, preview_map)
        self.assertTrue(restored.final_map.empty)
        self.assertEqual(list(restored.final_map.columns), [])
        pd.testing.assert_frame_equal(restored.stage_frame("preview"), preview_map)
        self.assertTrue(restored.stage_frame("final").empty)

    def test_wkb_round_trip_preserves_independent_dynamic_tables(self):
        preview_dynamic = pd.DataFrame({
            "Wafer ID": ["P1", "P1"],
            "Die Seq": [1, 2],
            "Cycle": [1, 1],
            "CD_Bot": [12.1, 12.2],
        })
        final_dynamic = pd.DataFrame({
            "Wafer ID": ["F1", "F1"],
            "Die Seq": [1, 2],
            "Cycle": [1, 1],
            "CD_Bot": [11.8, 11.9],
        })
        workbook = MatchWorkbook(
            reference=self.reference(),
            raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(self.reference(), self.raw()),
            preview_dynamic=preview_dynamic,
            final_dynamic=final_dynamic,
        )

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "dynamic-snapshots.wkb"
            workbook.save(path)
            restored = MatchWorkbook.load(path)

        pd.testing.assert_frame_equal(restored.preview_dynamic, preview_dynamic)
        pd.testing.assert_frame_equal(restored.final_dynamic, final_dynamic)
        pd.testing.assert_frame_equal(
            restored.dynamic_frame("preview"), preview_dynamic
        )
        pd.testing.assert_frame_equal(
            restored.dynamic_frame("final"), final_dynamic
        )

    def test_wkb_round_trip_preserves_workspace_selections(self):
        workspace_selections = {
            "map": {
                "preview": {
                    "wafers": ("Preview wafer",),
                    "metrics": ("CD_Bot",),
                    "map_draw": {
                        "enabled": True,
                        "cells": (("Preview wafer", "CD_Bot"),),
                    },
                    "radius_draw": {
                        "enabled": True,
                        "cells": (("Preview wafer", "CD_Bot"),),
                    },
                },
                "final": {
                    "wafers": ("Final wafer",),
                    "metrics": ("SPA",),
                },
            },
            "dynamic": {
                "preview": {
                    "wafers": ("Dynamic wafer",),
                    "metrics": ("CD_Bot", "SPA"),
                },
                "final": None,
            },
        }
        workbook = MatchWorkbook(
            reference=self.reference(),
            raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(
                self.reference(), self.raw()
            ),
            workspace_selections=workspace_selections,
        )

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "workspace-selections.wkb"
            workbook.save(path)
            restored = MatchWorkbook.load(path)

        self.assertEqual(restored.workspace_selections, workspace_selections)

    def test_wkb_round_trip_preserves_correlation_selections(self):
        correlation_selections = {
            "preview": {
                "reference": {
                    "wafers": ("reference-wafer",),
                    "metrics": ("CD_Bot", "SPA"),
                },
                "raw": {
                    "wafers": ("raw-wafer",),
                    "metrics": ("CD_Bot",),
                },
                "correlation_draw": {
                    "enabled": True,
                    "cells": (
                        ("Reference", "reference-wafer", "CD_Bot"),
                        ("Reference", "reference-wafer", "SPA"),
                    ),
                },
                "trend_draw": {
                    "enabled": True,
                    "cells": (("Raw Data", "raw-wafer", "CD_Bot"),),
                },
            },
            "final": None,
        }
        workbook = MatchWorkbook(
            reference=self.reference(),
            raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(
                self.reference(), self.raw()
            ),
            correlation_selections=correlation_selections,
            trend_axis_settings={"ratio": 2.75, "mode": "single"},
        )

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "correlation-selections.wkb"
            workbook.save(path)
            restored = MatchWorkbook.load(path)

        self.assertEqual(
            restored.correlation_selections, correlation_selections
        )
        self.assertEqual(
            restored.trend_axis_settings, {"ratio": 2.75, "mode": "single"}
        )

    def test_legacy_axis_ratio_without_mode_remains_loadable(self):
        workbook = MatchWorkbook(
            reference=self.reference(), raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(self.reference(), self.raw()),
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy-axis-ratio.wkb"
            save_legacy(workbook, path)
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute(
                    "UPDATE metadata SET correlation_selections = ?",
                    (json.dumps({
                        "preview": {"trend_axis_ratio": 2.75},
                        "final": None,
                    }),),
                )
                connection.execute(
                    """CREATE TABLE legacy_metadata AS
                       SELECT schema_version, match_type, result_mode, bias_mode,
                              bias_views, setup_splitter_sizes, parameter_order,
                              workspace_selections, correlation_selections,
                              saved_utc
                       FROM metadata"""
                )
                connection.execute("DROP TABLE metadata")
                connection.execute("ALTER TABLE legacy_metadata RENAME TO metadata")
            restored = MatchWorkbook.load(path)
        self.assertEqual(
            restored.trend_axis_settings, {"ratio": 2.75, "mode": "auto"}
        )
        state = restored.correlation_selections["preview"]
        self.assertNotIn("trend_axis_ratio", state)
        self.assertNotIn("trend_axis_mode", state)

    def test_legacy_axis_policy_uses_the_saved_active_stage(self):
        selections = {
            "preview": {"trend_axis_ratio": 2.75, "trend_axis_mode": "dual"},
            "final": {"trend_axis_ratio": 7.125, "trend_axis_mode": "single"},
        }
        for stage, expected in (
            ("preview", {"ratio": 2.75, "mode": "dual"}),
            ("final", {"ratio": 7.125, "mode": "single"}),
        ):
            with self.subTest(stage=stage):
                workbook = MatchWorkbook(
                    reference=self.reference(), raw=self.raw(),
                    mappings=MatchWorkbook.suggest_mappings(
                        self.reference(), self.raw()
                    ),
                    result_mode=stage,
                    correlation_selections=selections,
                )
                self.assertEqual(workbook.trend_axis_settings, expected)
                for state in workbook.correlation_selections.values():
                    self.assertNotIn("trend_axis_ratio", state)
                    self.assertNotIn("trend_axis_mode", state)

    def test_legacy_axis_policy_falls_back_to_the_other_stage(self):
        workbook = MatchWorkbook(
            reference=self.reference(), raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(self.reference(), self.raw()),
            result_mode="final",
            correlation_selections={
                "preview": {"trend_axis_ratio": 3.625, "trend_axis_mode": "dual"},
                "final": {"raw": {"wafers": ("W1",), "metrics": ("SPA",)}},
            },
        )
        self.assertEqual(
            workbook.trend_axis_settings, {"ratio": 3.625, "mode": "dual"}
        )
        self.assertEqual(
            workbook.correlation_selections["final"]["raw"],
            {"wafers": ("W1",), "metrics": ("SPA",)},
        )

    def test_legacy_axis_policy_does_not_mix_settings_from_two_stages(self):
        workbook = MatchWorkbook(
            reference=self.reference(), raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(self.reference(), self.raw()),
            result_mode="final",
            correlation_selections={
                "preview": {"trend_axis_ratio": 42.5, "trend_axis_mode": "dual"},
                "final": {"trend_axis_mode": "single"},
            },
        )
        self.assertEqual(
            workbook.trend_axis_settings, {"ratio": 10.0, "mode": "single"}
        )

    def test_shared_axis_policy_takes_precedence_over_legacy_stage_settings(self):
        workbook = MatchWorkbook(
            reference=self.reference(), raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(self.reference(), self.raw()),
            result_mode="final",
            correlation_selections={
                "preview": {"trend_axis_ratio": 2.75, "trend_axis_mode": "dual"},
                "final": {"trend_axis_ratio": 7.125, "trend_axis_mode": "single"},
            },
            trend_axis_settings={"ratio": 1.875, "mode": "auto"},
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "shared-axis-policy.wkb"
            workbook.save(path)
            restored = MatchWorkbook.load(path)
        self.assertEqual(
            restored.trend_axis_settings, {"ratio": 1.875, "mode": "auto"}
        )
        for state in restored.correlation_selections.values():
            self.assertNotIn("trend_axis_ratio", state)
            self.assertNotIn("trend_axis_mode", state)

    def test_schema_one_wkb_still_opens_without_fullmap_stage_tables(self):
        workbook = MatchWorkbook(
            reference=self.reference(),
            raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(self.reference(), self.raw()),
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.wkb"
            save_legacy(workbook, path)
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
        self.assertIsNone(restored.final_match_raw)
        self.assertIsNone(restored.setup_splitter_sizes)
        self.assertEqual(restored.parameter_order, ("CD_Bot", "SPA"))

    def test_schema_two_wkb_opens_without_independent_final_match_data(self):
        workbook = MatchWorkbook(
            reference=self.reference(),
            raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(self.reference(), self.raw()),
            final_match_raw=self.raw().assign(CD_Bot=[11.0, 19.0, 31.0]),
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "schema-two.wkb"
            save_legacy(workbook, path)
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("UPDATE metadata SET schema_version = 2")
                connection.execute("DROP TABLE final_match_raw_data")
            restored = MatchWorkbook.load(path)

        pd.testing.assert_frame_equal(restored.raw, workbook.raw)
        self.assertIsNone(restored.final_match_raw)

    def test_schema_three_wkb_opens_without_exact_map_snapshots(self):
        workbook = MatchWorkbook(
            reference=self.reference(),
            raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(self.reference(), self.raw()),
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "schema-three.wkb"
            save_legacy(workbook, path)
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("UPDATE metadata SET schema_version = 3")
            restored = MatchWorkbook.load(path)

        self.assertIsNone(restored.preview_map)
        self.assertIsNone(restored.final_map)
        self.assertEqual(
            restored.stage_frame("preview")["CD_Bot"].tolist(),
            [12.0, 22.0, 32.0],
        )

    def test_schema_four_wkb_opens_without_dynamic_snapshots(self):
        workbook = MatchWorkbook(
            reference=self.reference(),
            raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(self.reference(), self.raw()),
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "schema-four.wkb"
            save_legacy(workbook, path)
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("UPDATE metadata SET schema_version = 4")
            restored = MatchWorkbook.load(path)

        self.assertIsNone(restored.preview_dynamic)
        self.assertIsNone(restored.final_dynamic)
        self.assertEqual(
            restored.dynamic_frame("preview")["CD_Bot"].tolist(),
            [12.0, 22.0, 32.0],
        )

    def test_schema_five_wkb_opens_without_workspace_selections(self):
        workbook = MatchWorkbook(
            reference=self.reference(),
            raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(
                self.reference(), self.raw()
            ),
            workspace_selections={
                "map": {
                    "preview": {
                        "wafers": ("W1",),
                        "metrics": ("CD_Bot",),
                    }
                }
            },
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "schema-five.wkb"
            save_legacy(workbook, path)
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("UPDATE metadata SET schema_version = 5")
                connection.execute(
                    """CREATE TABLE legacy_metadata AS
                       SELECT schema_version, match_type, result_mode,
                              bias_mode, bias_views, setup_splitter_sizes,
                              parameter_order, saved_utc
                       FROM metadata"""
                )
                connection.execute("DROP TABLE metadata")
                connection.execute(
                    "ALTER TABLE legacy_metadata RENAME TO metadata"
                )
            restored = MatchWorkbook.load(path)

        self.assertEqual(
            restored.workspace_selections,
            {
                "map": {"preview": None, "final": None},
                "dynamic": {"preview": None, "final": None},
            },
        )

    def test_schema_six_workspace_selections_open_without_map_draw_state(self):
        selections = {
            "map": {
                "preview": {
                    "wafers": ("W1",),
                    "metrics": ("CD_Bot",),
                },
                "final": None,
            },
            "dynamic": {"preview": None, "final": None},
        }
        workbook = MatchWorkbook(
            reference=self.reference(),
            raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(
                self.reference(), self.raw()
            ),
            workspace_selections=selections,
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "schema-six.wkb"
            save_legacy(workbook, path)
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("UPDATE metadata SET schema_version = 6")
            restored = MatchWorkbook.load(path)

        self.assertEqual(restored.workspace_selections, selections)

    def test_schema_seven_workspace_selections_open_without_radius_draw_state(self):
        selections = {
            "map": {
                "preview": {
                    "wafers": ("W1",),
                    "metrics": ("CD_Bot",),
                    "map_draw": {
                        "enabled": True,
                        "cells": (("W1", "CD_Bot"),),
                    },
                },
                "final": None,
            },
            "dynamic": {"preview": None, "final": None},
        }
        workbook = MatchWorkbook(
            reference=self.reference(),
            raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(
                self.reference(), self.raw()
            ),
            workspace_selections=selections,
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "schema-seven.wkb"
            save_legacy(workbook, path)
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("UPDATE metadata SET schema_version = 7")
            restored = MatchWorkbook.load(path)

        self.assertEqual(restored.workspace_selections, selections)

    def test_schema_eight_wkb_opens_without_correlation_selections(self):
        workbook = MatchWorkbook(
            reference=self.reference(),
            raw=self.raw(),
            mappings=MatchWorkbook.suggest_mappings(
                self.reference(), self.raw()
            ),
            correlation_selections={
                "preview": {
                    "reference": {
                        "wafers": ("W1",),
                        "metrics": ("CD_Bot", "SPA"),
                    },
                    "raw": {"wafers": ("W1",), "metrics": ("CD_Bot",)},
                }
            },
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "schema-eight.wkb"
            save_legacy(workbook, path)
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("UPDATE metadata SET schema_version = 8")
                connection.execute(
                    """CREATE TABLE legacy_metadata AS
                       SELECT schema_version, match_type, result_mode,
                              bias_mode, bias_views, setup_splitter_sizes,
                              parameter_order, workspace_selections, saved_utc
                       FROM metadata"""
                )
                connection.execute("DROP TABLE metadata")
                connection.execute(
                    "ALTER TABLE legacy_metadata RENAME TO metadata"
                )
            restored = MatchWorkbook.load(path)

        self.assertEqual(
            restored.correlation_selections,
            {"preview": None, "final": None},
        )


if __name__ == "__main__":
    unittest.main()
