"""Measured-point identification uses the same source record after filtering."""
import os
from types import SimpleNamespace
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QApplication

from metrology_app.array_plot import ArrayOptions, prepare_array
from metrology_app.plot_page import PlotPage

APP = QApplication.instance() or QApplication([])


class WaferHoverTests(unittest.TestCase):
    def test_map_die_identity_stays_positional_with_duplicate_source_index_and_missing_coordinates(self):
        frame = pd.DataFrame({"Wafer ID": ["W1"] * 6,
                              "X(mm)": [-1, "bad", -1, 1, 0, 0], "Y(mm)": [-1, -1, 1, 1, 0, 2],
                              "Die ID": ["002", "036", "050", "066", "085", "099"],
                              "CD": ["1.000", "2.000", "3.000", "4.000", "5.000", "bad"]},
                             index=[9, 9, 4, 4, 2, 2])
        result = prepare_array(frame, {"wafers": ["W1"], "metrics": ["CD"], "wafer_column": "Wafer ID"},
                               ArrayOptions("X(mm)", "Y(mm)", diameter=6, fill_edge=False))
        self.assertEqual(result["scenes"][0]["layer"].die.tolist(), ["002", "050", "066", "085"])

    def test_hover_identifies_the_measured_die_after_invalid_rows_and_keeps_source_strings(self):
        frame = pd.DataFrame({"Wafer ID": ["W1"] * 6,
                              "X(mm)": [-1, 1, -1, 1, 0, 0], "Y(mm)": [-1, -1, 1, 1, 0, 2],
                              "Die Seq": ["00002", "00036", "00050", "00066", "00085", "00099"],
                              "CD": ["1.000", "2.000", "3.000", "4.000", "5.000", "bad"]})
        before = frame.copy(deep=True)
        result = prepare_array(frame, {"wafers": ["W1"], "metrics": ["CD"], "wafer_column": "Wafer ID"},
                               ArrayOptions("X(mm)", "Y(mm)", diameter=6, fill_edge=False))
        page = PlotPage()
        try:
            page.render_result(result)
            page.canvas.draw()
            plot, scene = page.artists[0]
            x, y = plot.axes.transData.transform(plot.positions[1])
            page.hover_point(SimpleNamespace(x=x, y=y, inaxes=plot.axes))
            self.assertIn("Die 00036", page.status.text())
            self.assertIn("CD = 2", page.status.text())
            self.assertEqual(scene["layer"].die.tolist(), ["00002", "00036", "00050", "00066", "00085"])
            np.testing.assert_allclose(plot.positions, [[-1, -1], [1, -1], [-1, 1], [1, 1], [0, 0]])
            pd.testing.assert_frame_equal(frame, before)
        finally:
            page.stop()
            page.close()
            page.deleteLater()
            APP.processEvents()


if __name__ == "__main__":
    unittest.main()
