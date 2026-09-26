"""Regression checks for real-table parsing and scientific data handling."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg

from metrology_app.data import Dataset, read_table
from metrology_app.plot import (
    PlotOptions, WaferPlot, infer_geometry,
    infer_wafer_geometry, interpolate, interpolate_many,
)


ROOT = Path(__file__).resolve().parents[1]


class DataTests(unittest.TestCase):
    def test_real_csv_layers(self):
        data = Dataset(read_table(ROOT / "sample_data" / "OCD_measurement_data.csv"), "fixture")
        self.assertEqual(len(data.frame), 480)
        self.assertEqual(len(data.metrics), 20)
        self.assertEqual(len(data.wafers()), 3)
        for wafer in data.wafers():
            a, b = data.groups(wafer)
            layer = data.layer(wafer, a, "OCD_H1", b)
            self.assertEqual(len(layer), 80)
            np.testing.assert_allclose(layer.value, layer.value_a - layer.value_b)

    def test_clipboard_and_xlsx(self):
        original = pd.DataFrame({"X": [0, 1, 0], "Y": [0, 0, 1], "Thickness": [1.2, 1.3, 1.4]})
        pasted = read_table(text=original.to_csv(sep="\t", index=False))
        pd.testing.assert_frame_equal(pasted, original)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.xlsx"
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                original.to_excel(writer, index=False, sheet_name="data")
                (original * 2).to_excel(writer, index=False, sheet_name="other")
            pd.testing.assert_frame_equal(read_table(path, sheet="data"), original)
            pd.testing.assert_frame_equal(read_table(path, sheet="other"), original * 2)

    def test_difference_matches_coordinates_not_row_order(self):
        frame = pd.DataFrame({"X": [0, 1, 2, 1, 0, 3], "Y": [0] * 6,
                              "PAD Name": ["A"] * 3 + ["B"] * 3,
                              "Value": [10, 20, 30, 3, 4, 5]})
        data = Dataset(frame, "test")
        delta = data.layer("全部", "A", "Value", "B").set_index("x")
        self.assertEqual(delta.value.to_dict(), {0: 6, 1: 17})

    def test_invalid_values_and_duplicates(self):
        frame = pd.DataFrame({"X": [0, 1, 2, 3], "Y": [0, 1, 0, 1],
                              "Value": [1, np.inf, "bad", 4]})
        data = Dataset(frame, "test")
        self.assertEqual(len(data.layer("全部", "全部", "Value")), 2)
        duplicate = Dataset(pd.concat([frame, frame.iloc[:1]], ignore_index=True), "test")
        with self.assertRaisesRegex(ValueError, "重复坐标"):
            duplicate.layer("全部", "全部", "Value")


class PlotTests(unittest.TestCase):
    def setUp(self):
        self.points = np.array([[-1., -1.], [1., -1.], [1., 1.], [-1., 1.], [0., 0.]])
        self.values = np.array([1., 2., 3., 2., 2.])

    def test_circle_mask_and_optional_edge_fill(self):
        geometry = infer_geometry(self.points)
        gx, gy, surface, edge = interpolate(self.points, self.values, geometry, resolution=70)
        inside = (gx - geometry[0]) ** 2 + (gy - geometry[1]) ** 2 <= geometry[2] ** 2
        self.assertTrue(surface.mask[~inside].all())
        self.assertFalse(surface.mask[inside].any())
        self.assertTrue(edge.any())
        unfilled = interpolate(self.points, self.values, geometry, False, resolution=70)[2]
        self.assertTrue(unfilled.mask[edge].all())
        self.assertGreaterEqual(surface.min(), self.values.min())
        self.assertLessEqual(surface.max(), self.values.max())

    def test_collinear_coordinates_rejected(self):
        with self.assertRaisesRegex(ValueError, "不共线"):
            interpolate(np.array([[0., 0.], [1., 0.], [2., 0.]]), np.array([1., 2., 3.]), (1, 0, 2))

    def test_common_mm_wafer_sizes_are_inferred(self):
        angle = np.linspace(0, 2 * np.pi, 36, endpoint=False)
        ring = np.column_stack((140 * np.cos(angle), 140 * np.sin(angle)))
        for scale, expected in ((1, 300), (2 / 3, 200), (1 / 3, 100)):
            geometry, diameter = infer_wafer_geometry(ring * scale, ("X(mm)", "Y(mm)"))
            self.assertEqual(diameter, expected)
            self.assertEqual(geometry[2], expected / 2)

    def test_axes_colorbar_constant_and_rotation(self):
        layer = pd.DataFrame(self.points, columns=["x", "y"])
        layer["value"] = 2.0
        plot = WaferPlot()
        options = PlotOptions(*infer_geometry(self.points), rotation=90, difference=True)
        _, bounds = plot.draw(layer, "Value", "W1", options)
        self.assertEqual(bounds, (-2., 2.))
        self.assertTrue(all(spine.get_visible() for spine in plot.axes.spines.values()))
        self.assertIsNotNone(plot.colorbar)
        self.assertEqual(plot.axes.get_title(loc="center"), "Value  [A - B]")
        self.assertEqual(plot.axes.title.get_fontweight(), "bold")
        self.assertEqual([text.get_text() for text in plot.axes._wafer_title_details],
                         ["W1", "Min 2   Max 2   Mean 2"])
        self.assertTrue(all(text.get_ha() == "center" for text in plot.axes._wafer_title_details))
        np.testing.assert_allclose(plot.positions[0], [1, -1], atol=1e-12)
        no_bar = WaferPlot()
        no_bar.draw(layer, "Value", "W1", PlotOptions(0, 0, 2, cmap="plasma", show_colorbar=False))
        self.assertIsNone(no_bar.colorbar)
        self.assertTrue(no_bar.axes.images[0].get_cmap().name.startswith("plasma"))
        self.assertEqual(no_bar.axes.get_xlim(), (-2, 2))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "plot.png"
            plot.save(path)
            self.assertGreater(path.stat().st_size, 10000)

    def test_dense_value_labels_are_thinned_without_overlap(self):
        grid = np.linspace(-1, 1, 11)
        points = np.array([(x, y) for y in grid for x in grid])
        layer = pd.DataFrame(points, columns=["x", "y"])
        layer["value"] = np.linspace(10, 99, len(layer))
        plot = WaferPlot()
        plot.figure.set_size_inches(2.2, 2.2)
        plot.draw(layer, "Value", "W1", PlotOptions(0, 0, 1.5, resolution=35,
                                                      show_colorbar=False), compact=True)
        FigureCanvasAgg(plot.figure).draw()
        boxes = plot.value_labels.drawn_boxes
        self.assertGreater(len(boxes), 0)
        self.assertLess(len(boxes), len(layer))
        for index, box in enumerate(boxes):
            for other in boxes[index + 1:]:
                overlaps = (box[0] < other[2] and box[2] > other[0]
                            and box[1] < other[3] and box[3] > other[1])
                self.assertFalse(overlaps)

    def test_edge_continuation_does_not_saturate_to_extreme(self):
        points = np.array([[-1., -1.], [1., -1.], [1., 1.], [-1., 1.], [0., 0.]])
        values = np.array([2., 2., 2., 2., 10.])
        _, _, surface, edge = interpolate(points, values, (0, 0, 2), resolution=101)
        self.assertTrue(edge.any())
        self.assertLess(float(surface.data[edge].max()), 6)
        self.assertGreaterEqual(float(surface.data[edge].min()), 2)

    def test_mirrored_edge_keeps_the_radial_trend(self):
        # A radially decreasing wafer: the unsampled rim must keep falling instead
        # of flattening into a uniform ring (the old zero-flux extension).
        angle = np.linspace(0, 2 * np.pi, 40, endpoint=False)
        rings = [np.column_stack((r * np.cos(angle), r * np.sin(angle))) for r in (30, 70, 110)]
        points = np.vstack(rings)
        values = np.concatenate([np.full(len(angle), value) for value in (58.0, 56.0, 54.0)])
        gx, gy, surface, edge = interpolate(points, values, (0, 0, 150), resolution=201)
        radius = np.hypot(gx, gy)
        bins = [(0, 50), (50, 100), (100, 130), (135, 150)]
        means = [float(surface.data[(radius >= low) & (radius < high)].mean()) for low, high in bins]
        self.assertTrue(all(later < earlier for earlier, later in zip(means, means[1:])),
                        f"rim flattened instead of continuing the trend: {means}")
        self.assertLess(means[0] - means[-1], 4.5)

    def test_multi_parameter_interpolation_matches_individual_results(self):
        geometry = infer_geometry(self.points)
        combined = np.column_stack((self.values, self.values * 2 + 1))
        gx, gy, surfaces, edge = interpolate_many(
            self.points, combined, geometry, resolution=70
        )
        one = interpolate(self.points, self.values, geometry, resolution=70)
        two = interpolate(self.points, combined[:, 1], geometry, resolution=70)
        np.testing.assert_allclose(gx, one[0])
        np.testing.assert_allclose(gy, one[1])
        np.testing.assert_allclose(surfaces[0].filled(np.nan), one[2].filled(np.nan), equal_nan=True)
        np.testing.assert_allclose(surfaces[1].filled(np.nan), two[2].filled(np.nan), equal_nan=True)
        np.testing.assert_array_equal(edge, one[3])

    def test_shared_solve_keeps_smoothing_per_parameter(self):
        # A wide-range parameter in the same batch must not smooth a narrow one:
        # the smoothing amount is defined per column, not on the pooled range.
        geometry = infer_geometry(self.points)
        combined = np.column_stack((self.values, self.values * 40 + 500))
        _, _, surfaces, _ = interpolate_many(self.points, combined, geometry,
                                             resolution=60, smoothing=0.06)
        _, _, alone, _ = interpolate_many(self.points, self.values[:, None], geometry,
                                          resolution=60, smoothing=0.06)
        np.testing.assert_allclose(surfaces[0].filled(np.nan), alone[0].filled(np.nan),
                                   rtol=1e-9, atol=1e-9)


if __name__ == "__main__":
    unittest.main()
