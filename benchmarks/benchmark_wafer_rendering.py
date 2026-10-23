"""Measure prepared-map presentation, excluding numerical interpolation.

Run through the settings-isolated runner:
  python run_tests.py benchmarks.benchmark_wafer_rendering -v

Uses only deterministic synthetic data. Reports the first presentation separately
from repeated presentations; neither measurement is a cold application startup.
"""
from statistics import median
from time import perf_counter
import unittest


class WaferRenderingBenchmark(unittest.TestCase):
    def test_rendering(self):
        import json
        from PyQt6.QtWidgets import QApplication
        from metrology_app.array_plot import ArrayOptions, prepare_array
        from metrology_app.plot_page import PlotPage
        from tests.test_wafer_static import map_fixture

        app = QApplication.instance() or QApplication([])
        frame, selection = map_fixture()
        result = prepare_array(frame, selection, ArrayOptions("X mm", "Y mm"))
        page = PlotPage()
        page.font_size.setCurrentText("10")
        page.resize(1200, 800)
        page.show()
        app.processEvents()
        try:
            samples = []
            for _ in range(6):
                start = perf_counter()
                page.render_result(result)
                app.processEvents()
                samples.append(perf_counter()-start)
                self.assertIsNotNone(page.result, page.empty.text())
            print(json.dumps({"maps": 10, "points_per_map": len(frame)//2,
                              "actual_viewport_px": [page.scroll.viewport().width(), page.scroll.viewport().height()],
                              "first_presentation_seconds": samples[0],
                              "repeat_seconds": samples[1:], "repeat_median_seconds": median(samples[1:])},
                             indent=2), flush=True)
        finally:
            page.stop()
            page.close()
            page.deleteLater()
            app.processEvents()
