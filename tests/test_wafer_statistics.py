"""Wafer Mean / Sigma is a two-column bar view inside Correlation and Trend."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from metrology_app import sequence_page as sequence_module
from metrology_app import settings as settings_module
from metrology_app.analysis_export import capture_window
from metrology_app.correlation_window import CorrelationWindow
from metrology_app.matching import MatchWorkbook, ParameterMapping
from metrology_app.sequence_page import CompareComboBox
from metrology_app.settings import get_settings


APP = QApplication.instance() or QApplication([])


class WaferStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.windows = []
        self._saved_overlay = get_settings().get("trend_overlay", {})
        self._saved_source_overlay = get_settings().get("trend_source_overlay")
        settings_module._current["trend_overlay"] = {}
        settings_module._current.pop("trend_source_overlay", None)
        self._settings_patch = patch("metrology_app.sequence_page.save_settings")
        self._settings_patch.start()

    def tearDown(self):
        self._settings_patch.stop()
        settings_module._current["trend_overlay"] = self._saved_overlay
        if self._saved_source_overlay is None:
            settings_module._current.pop("trend_source_overlay", None)
        else:
            settings_module._current["trend_source_overlay"] = (
                self._saved_source_overlay
            )
        for window in self.windows:
            self.close_window(window)

    def close_window(self, window):
        window.document.force_close = True
        window.close()
        window.deleteLater()
        APP.processEvents()

    def window(self):
        window = CorrelationWindow()
        self.windows.append(window)
        return window

    @staticmethod
    def single_source_frame():
        return pd.DataFrame({
            "Wafer ID": ["W1"] * 3 + ["W2"] * 3,
            "Die Seq": [1, 2, 3] * 2,
            "CD": [1.0, 3.0, 5.0, 2.0, 4.0, 6.0],
        })

    @staticmethod
    def source_frames():
        reference = pd.DataFrame({
            "Wafer ID": ["W1"] * 3 + ["W2"] * 3,
            "Die Seq": [1, 2, 3] * 2,
            "CD Ref": [1.0, 3.0, 5.0, 2.0, 4.0, 6.0],
        })
        raw = pd.DataFrame({
            "Wafer ID": ["W1"] * 3 + ["W2"] * 3,
            "Die Seq": [1, 2, 3] * 2,
            "CD Raw": [2.0, 4.0, 6.0, 4.0, 6.0, 8.0],
        })
        return reference, raw, (ParameterMapping("CD", "CD Ref", "CD Raw"),)

    def draw_sources(self):
        window = self.window()
        reference, raw, mappings = self.source_frames()
        window.set_sources(reference, raw, mappings)
        page = window.wafer_statistics_page
        page.selector.selectAll()
        page.draw_plot()
        APP.processEvents()
        self.assertTrue(page.ready, page.status.text())
        return window, page

    def test_trend_and_statistics_show_base_and_combined_groups(self):
        window = self.window()
        reference, raw, mappings = self.source_frames()
        flags = pd.DataFrame({"TestFlag": [0] * 3 + [1] * 3})
        book = MatchWorkbook(reference, raw, mappings, test_flags=flags,
                             grouping_state={"enabled": True, "show_wafer_groups": ["All:0"],
                                 "combined_groups": [{"id": "combined:pair", "name": "Pair",
                                                      "members": ["All:0", "All:1"]}]})
        window.set_sources(reference, raw, mappings)
        window.set_workbook_groups(book)
        for page in (window.sequence_page, window.wafer_statistics_page):
            page.selector.selectAll()
            page.draw_plot()
            self.assertTrue(page.ready, page.status.text())
        trend = window.sequence_page.plot_widgets[0]
        self.assertEqual([label for _, _, label in trend._wafer_axis.spans], ["TestFlag 0", "TestFlag 1"])
        self.assertEqual([label for _, _, label in trend._combined_caption_axis.spans], ["Pair"])
        stats = window.wafer_statistics_page.plot_widgets[0]._statistic_caption_axes
        self.assertEqual([label for _, _, label in stats["base"].spans], ["TestFlag 0", "TestFlag 1"])
        self.assertEqual([label for _, _, label in stats["combined"].spans], ["Pair"])
        self.assertIn("W1", stats["wafer"].spans[0][2])
        self.assertEqual(len(stats["wafer"].spans), 1)

    def test_compare_colour_never_reuses_its_primary_colour(self):
        _window, page = self.draw_sources()
        for primary in page.panel_specs:
            source, metric = primary["source"], primary["metric"]
            panel = {**primary, "comparisons": ((source["name"], metric),) * 2}
            compare = page._comparison_colours(panel)
            self.assertEqual(len(set((source["color"], *compare))), 3)

    def test_axis_precision_uses_scientific_labels_for_tiny_sigma(self):
        window, page = self.draw_sources()
        axis = page.plot_widgets[0].getAxis("left")
        self.assertEqual(axis.tickStrings([1.23456], 1, .5), ["1.235"])
        self.assertEqual(axis.tickStrings([1e-15, 2e-15], 1, 1e-15), ["1.000e-15", "2.000e-15"])
        window.plot_decimal_places.setValue(2)
        axis = page.plot_widgets[0].getAxis("left")
        self.assertEqual(axis.tickStrings([1.23456], 1, .5), ["1.23"])

    def test_secondary_axes_and_bias_keep_the_same_plot_width(self):
        window, page = self.draw_sources()
        window.resize(1600, 900)
        window.tabs.setCurrentWidget(page)
        window.show()
        page.add_compare("CD Ref", "Reference")
        page.restore_axis_mode("dual")
        QTest.qWait(40)
        self.assertTrue(any(widget.secondary_axes for widget in page.plot_widgets))
        self.assertTrue(any(panel.get("plot_kind") == "bias" for panel in page.panel_specs))
        widths = [widget.getViewBox().sceneBoundingRect().width() for widget in page.plot_widgets]
        self.assertGreater(min(widths), 100)
        self.assertLessEqual(max(widths) - min(widths), 2)

    def test_draws_wafer_mean_then_sigma_in_a_fixed_two_column_grid(self):
        window = self.window()
        window.set_table(self.single_source_frame(), "Raw Data")
        page = window.wafer_statistics_page
        page.selector.selectAll()
        page.draw_plot()
        APP.processEvents()

        self.assertTrue(page.ready, page.status.text())
        self.assertEqual(
            [panel["statistic"] for panel in page.panel_specs],
            ["mean", "sigma"],
        )
        self.assertEqual(page.columns.currentText(), "2")
        self.assertFalse(page.columns.isEnabled())
        self.assertEqual(len(page.plot_widgets), 2)
        self.assertEqual(
            [widget.getAxis("bottom").labelText for widget in page.plot_widgets],
            ["Wafer", "Wafer"],
        )

        mean_bar = page.plot_widgets[0].listDataItems()[0]
        sigma_bar = page.plot_widgets[1].listDataItems()[0]
        self.assertIsInstance(mean_bar, pg.BarGraphItem)
        np.testing.assert_allclose(mean_bar.opts["height"], [3.0, 4.0])
        expected_sigma = np.sqrt(8 / 3)
        np.testing.assert_allclose(
            sigma_bar.opts["height"], [expected_sigma, expected_sigma]
        )

        plots = page.export_plot_data()
        self.assertEqual(
            [plot["title"] for plot in plots],
            ["CD · Wafer Mean", "CD · Wafer Sigma"],
        )
        self.assertTrue(all(plot["sheet"] == "Wafer Mean and Sigma"
                            for plot in plots))
        report = capture_window(window)
        self.assertEqual(
            len([plot for plot in report["plots"]
                 if plot["sheet"] == "Wafer Mean and Sigma"]),
            2,
        )
        with TemporaryDirectory() as directory:
            from openpyxl import load_workbook

            output = window.export_excel(
                Path(directory) / "wafer-statistics.xlsx"
            )
            book = load_workbook(output, read_only=True)
            try:
                self.assertIn("Wafer Mean and Sigma", book.sheetnames)
            finally:
                book.close()

    def test_add_compare_aligns_ref_and_raw_bars_in_the_same_panels(self):
        window, page = self.draw_sources()
        window.resize(1200, 900)
        window.show()
        APP.processEvents()

        self.assertTrue(page.add_compare("CD Ref", "Reference"))
        APP.processEvents()

        index, panel = next(
            (index, panel)
            for index, panel in enumerate(page.panel_specs)
            if panel["source"]["name"] == "Reference"
            and panel["metric"] == "CD Ref"
            and panel["statistic"] == "mean"
        )
        self.assertEqual(
            panel["comparisons"], (("Raw Data", "CD Raw"),)
        )
        bars = [
            item for item in page.plot_widgets[index].listDataItems()
            if isinstance(item, pg.BarGraphItem)
        ]
        self.assertEqual(len(bars), 2)
        np.testing.assert_allclose(bars[0].opts["height"], [3.0, 4.0])
        np.testing.assert_allclose(bars[1].opts["height"], [4.0, 6.0])
        self.assertEqual(bars[0].opts["width"], page.BAR_WIDTH)
        self.assertEqual(bars[1].opts["width"], page.BAR_WIDTH)
        self.assertEqual(
            bars[0].opts["brush"].color().name().upper(), "#ED7D31"
        )
        self.assertEqual(
            bars[1].opts["brush"].color().name().upper(), "#5B9BD5"
        )
        combo = page.panel_hosts[index].findChild(CompareComboBox)
        self.assertIsNotNone(combo)
        self.assertEqual(combo.currentData(), ("Raw Data", "CD Raw"))
        self.assertEqual(combo.currentText(), "Raw Data · CD Raw")

        kinds = [
            panel.get("plot_kind", "statistic")
            for panel in page.panel_specs
        ]
        self.assertLess(max(index for index, kind in enumerate(kinds)
                            if kind == "statistic"),
                        min(index for index, kind in enumerate(kinds)
                            if kind == "bias"))
        self.assertEqual(kinds.count("bias"), 2)
        bias_mean_index = next(
            index for index, panel in enumerate(page.panel_specs)
            if panel.get("plot_kind") == "bias"
            and panel["statistic"] == "mean"
            and panel["source"]["name"] == "Reference"
        )
        bias_bar = page.plot_widgets[bias_mean_index].listDataItems()[0]
        np.testing.assert_allclose(bias_bar.opts["height"], [1.0, 2.0])
        self.assertEqual(bias_bar.opts["width"], page.BAR_WIDTH)
        QTest.qWait(20)
        for splitter in page.plot_host.row_splitters:
            left, right = splitter.sizes()
            self.assertLessEqual(abs(left - right), 1)

        mean_plot = next(
            plot for plot in page.export_plot_data()
            if plot["title"] == "Reference · CD Ref · Wafer Mean"
        )
        self.assertEqual(
            [series["name"] for series in mean_plot["series"]],
            ["Reference · CD Ref", "Raw Data · CD Raw"],
        )
        np.testing.assert_allclose(
            mean_plot["series"][1]["data"]["Y"].to_numpy(float),
            [4.0, 6.0],
        )
        self.assertEqual(mean_plot["series"][1]["color"], "#5b9bd5")
        bias_plot = next(
            plot for plot in page.export_plot_data()
            if plot["title"].startswith("Wafer Mean Bias")
        )
        np.testing.assert_allclose(
            bias_plot["series"][0]["data"]["Y"].to_numpy(float),
            [1.0, 2.0],
        )
        self.assertTrue(page.remove_overlay_at("CD Ref", 0, "Reference"))
        APP.processEvents()
        self.assertFalse(any(
            panel.get("plot_kind") == "bias"
            for panel in page.panel_specs
        ))

    def test_comparison_colours_start_with_orange_for_ref_and_blue_for_raw(self):
        window = self.window()
        reference = pd.DataFrame({
            "Wafer ID": ["W1"] * 3,
            "Die Seq": [1, 2, 3],
            "CD Ref": [1.0, 3.0, 5.0],
            "Alt Ref": [2.0, 4.0, 6.0],
        })
        raw = pd.DataFrame({
            "Wafer ID": ["W1"] * 3,
            "Die Seq": [1, 2, 3],
            "CD Raw": [2.0, 4.0, 6.0],
            "Alt Raw": [3.0, 5.0, 7.0],
        })
        window.set_sources(reference, raw, (
            ParameterMapping("CD", "CD Ref", "CD Raw"),
            ParameterMapping("Alt", "Alt Ref", "Alt Raw"),
        ))
        page = window.wafer_statistics_page
        page.selector.selectAll()
        page.draw_plot()
        self.assertTrue(page.set_overlay(
            "CD Ref", "CD Raw", "Reference", "Raw Data"
        ))
        self.assertTrue(page.set_overlay(
            "CD Ref", "Alt Raw", "Reference", "Raw Data"
        ))
        self.assertTrue(page.set_overlay(
            "CD Raw", "CD Ref", "Raw Data", "Reference"
        ))
        APP.processEvents()

        panel = next(
            panel for panel in page.panel_specs
            if panel["source"]["name"] == "Reference"
            and panel["metric"] == "CD Ref"
            and panel["statistic"] == "mean"
            and panel.get("plot_kind", "statistic") == "statistic"
        )
        index = page.panel_specs.index(panel)
        bars = [
            item for item in page.plot_widgets[index].listDataItems()
            if isinstance(item, pg.BarGraphItem)
        ]
        self.assertEqual([
            bar.opts["brush"].color().name().upper() for bar in bars
        ], ["#ED7D31", "#5B9BD5", "#2F75B5"])

        raw_panel = next(
            panel for panel in page.panel_specs
            if panel["source"]["name"] == "Raw Data"
            and panel["metric"] == "CD Raw"
            and panel["statistic"] == "mean"
            and panel.get("plot_kind", "statistic") == "statistic"
        )
        raw_index = page.panel_specs.index(raw_panel)
        raw_bars = [
            item for item in page.plot_widgets[raw_index].listDataItems()
            if isinstance(item, pg.BarGraphItem)
        ]
        self.assertEqual([
            bar.opts["brush"].color().name().upper() for bar in raw_bars
        ], ["#5B9BD5", "#ED7D31"])

    def test_workspace_restores_bar_boxes_comparison_and_draw_state(self):
        window, page = self.draw_sources()
        self.assertTrue(page.add_compare("CD Ref", "Reference"))
        APP.processEvents()
        draw_state = page.draw_state()
        overlay = dict(page.source_overlay)
        window.tabs.setCurrentIndex(4)

        restored = self.window()
        restored.restore_workspace(window.workspace_snapshot())
        APP.processEvents()
        restored_page = restored.wafer_statistics_page

        self.assertTrue(restored_page.ready, restored_page.status.text())
        self.assertEqual(restored_page.draw_state(), draw_state)
        self.assertEqual(restored_page.source_overlay, overlay)
        self.assertEqual(restored.tabs.tabText(4), "5. Wafer Mean / Sigma")
        self.assertEqual(restored.tabs.currentIndex(), 4)
        mean_panel = next(
            panel for panel in restored_page.panel_specs
            if panel["source"]["name"] == "Reference"
            and panel["metric"] == "CD Ref"
            and panel["statistic"] == "mean"
        )
        self.assertEqual(
            mean_panel["comparisons"], (("Raw Data", "CD Raw"),)
        )


if __name__ == "__main__":
    unittest.main()
