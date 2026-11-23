"""Match Workbook Wafer Mean/Sigma/Bias result tab."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication, QLabel, QSplitter

from metrology_app.matching import ParameterMapping
from metrology_app.matching_window import MatchingWindow
from tests.match_fixtures import configure_match_fixture

APP = QApplication.instance() or QApplication([])


class MatchWaferStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.window = MatchingWindow()
        self.window.document.force_close = True

    def tearDown(self):
        if hasattr(self.window, "match_statistics_page"):
            self.window.match_statistics_page.clear()
            APP.processEvents()
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def load(self, *, second=True):
        raw = pd.DataFrame({
            "Wafer ID": ["W1"] * 3 + ["W2"] * 3,
            "Die Seq": [1, 2, 3] * 2,
            "CD": [1.0, 3.0, 5.0, 2.0, 4.0, 6.0],
            "Depth": [3.0, 5.0, 7.0, 4.0, 6.0, 8.0],
        })
        reference = pd.DataFrame({
            "CD Reference": [2.0, 4.0, 6.0, 4.0, 6.0, 8.0],
            "Depth Reference": [4.0, 6.0, 8.0, 5.0, 7.0, 9.0],
        })
        mappings = [ParameterMapping("CD", "CD Reference", "CD")]
        if second:
            mappings.append(ParameterMapping("Depth", "Depth Reference", "Depth"))
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        configure_match_fixture(self.window, *mappings)

    def test_main_window_has_four_statistics_plots(self):
        self.load(second=False)
        from metrology_app.settings import apply_theme
        apply_theme(self.window, "dark")
        self.window.run_analysis()
        page = self.window.match_statistics_page
        self.assertGreaterEqual(self.window.results_tabs.indexOf(page), 0)
        self.assertEqual(
            self.window.results_tabs.tabText(self.window.results_tabs.indexOf(page)),
            "Wafer Mean / Sigma",
        )
        self.window.results_tabs.setCurrentWidget(page)
        page.render()
        self.assertEqual(page.rendered_parameters, ("CD",))
        self.assertEqual(len(page.plots_by_parameter["CD"]), 4)
        self.assertEqual(
            [plot.getAxis("left").labelText for plot in page.plots_by_parameter["CD"]],
            ["CD · Wafer Mean", "CD · Wafer Sigma",
             "CD · Wafer Mean Bias", "CD · Wafer Sigma Bias"],
        )
        self.assertEqual(
            [plot.getPlotItem().titleLabel.text for plot in page.plots_by_parameter["CD"]],
            ["CD · Wafer Mean", "CD · Wafer Sigma",
             "CD · Wafer Mean Bias", "CD · Wafer Sigma Bias"],
        )
        for plot in page.plots_by_parameter["CD"]:
            bottom = plot.getAxis("bottom")
            self.assertEqual(bottom.labelText, "")
            lengths = bottom.style["tickLength"]
            self.assertEqual(lengths[0] if isinstance(lengths, list) else lengths, 0)
            offsets = bottom.style["tickTextOffset"]
            self.assertLessEqual(
                offsets[1] if isinstance(offsets, list) else offsets,
                2,
            )
            self.assertEqual([label for _, label in bottom.ticks], ["1", "2"])
            captions = plot._statistics_caption_axis
            caption_lengths = captions.style["tickLength"]
            self.assertEqual(
                caption_lengths[0] if isinstance(caption_lengths, list) else caption_lengths,
                0,
            )
            for axis_name in ("top", "right", "bottom", "left"):
                frame_lengths = plot.getAxis(axis_name).style["tickLength"]
                self.assertEqual(
                    frame_lengths[0] if isinstance(frame_lengths, list) else frame_lengths,
                    0,
                )
            self.assertEqual(
                bottom.style["tickFont"].pointSizeF(),
                captions.style["tickFont"].pointSizeF(),
            )
            self.assertEqual(
                [label.splitlines()[0] for _, _, label in captions.spans],
                ["W1", "W2"],
            )
        self.assertTrue(any(
            label.text().endswith("CD")
            for label in page.findChildren(QLabel, "parameterDragHandle")
        ))
        parameter_plots = self.window.plot_groups["CD"]["plots"]
        statistic_plots = (
            *parameter_plots.values(),
            self.window.plot_groups["CD"]["wafer_r2"],
            self.window.plot_groups["CD"]["wafer_slope"],
            *page.plots_by_parameter["CD"],
        )
        for plot in statistic_plots:
            self.assertEqual(plot.backgroundBrush().color().name(), "#ffffff")
            self.assertEqual(plot.getAxis("left").textPen().color().name(), "#30343b")
        self.assertTrue(all(
            plot.getAxis("left").tickStrings([0.0, 2.5, 25.0], 1, 1)
            == ["0.000", "2.500", "25.000"]
            for plot in page.plots_by_parameter["CD"]
        ))

    def test_wafer_statistics_caption_follows_trend_plot_label_switches(self):
        from copy import deepcopy

        raw = pd.DataFrame({
            "Wafer ID": ["W1"] * 3 + ["W2"] * 3,
            "Lot ID": ["L1"] * 6,
            "PAD Name": ["P1"] * 6,
            "Die Seq": [1, 2, 3] * 2,
            "CD": [1.0, 3.0, 5.0, 2.0, 4.0, 6.0],
        })
        reference = pd.DataFrame({"CD Reference": [2.0, 4.0, 6.0, 4.0, 6.0, 8.0]})
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        configure_match_fixture(self.window, ParameterMapping("CD", "CD Reference", "CD"))
        self.window.run_analysis()
        page = self.window.match_statistics_page

        options = deepcopy(self.window._plot_label_options)
        options["trend"] = {"pad": False, "lot": True}
        self.window.set_plot_labels(options)
        page.render()
        labels = [
            label
            for _start, _end, label in page.plots_by_parameter["CD"][0]._statistics_caption_axis.spans
        ]
        self.assertTrue(all("LOT: L1" in label for label in labels))
        self.assertTrue(all("PAD:" not in label for label in labels))

        options["trend"] = {"pad": True, "lot": False}
        self.window.set_plot_labels(options)
        page.render()
        labels = [
            label
            for _start, _end, label in page.plots_by_parameter["CD"][0]._statistics_caption_axis.spans
        ]
        self.assertTrue(all("PAD: P1" in label for label in labels))
        self.assertTrue(all("LOT:" not in label for label in labels))
        self.assertTrue(all(label.splitlines()[-1] != "All" for label in labels))

    def test_grouped_statistics_only_show_wafer_captions_for_checked_groups(self):
        self.load()
        window = self.window
        raw = window.raw_frame
        raw = pd.concat([raw, raw.iloc[:3].assign(**{"Wafer ID": "W3"})], ignore_index=True)
        reference = window.reference_frame
        window.set_reference_frame(pd.concat([reference, reference.iloc[:3]], ignore_index=True))
        window.set_raw_frame(raw)
        window.group_controls.restore(
            {"enabled": True, "trend_order": "groups", "show_wafer_groups": ["All:0"],
             "head_names": {"0": "POR", "1": "New"}},
            pd.DataFrame({"TestFlag": [1] * 3 + [0] * 3 + [1] * 3}),
        )
        window.run_analysis()

        def captions_for(workbook):
            page = workbook.match_statistics_page
            page.render()
            APP.processEvents()
            self.assertEqual(set(page.plots_by_parameter), {"CD", "Depth"})
            return [tuple(plot._statistics_caption_axis.spans)
                    for plots in page.plots_by_parameter.values() for plot in plots]

        expected = ((0.5, 1.5, "W2\nPOR"), (1.5, 3.5, "New"))
        self.assertEqual(captions_for(window), [expected] * 8)
        window.result_mode.setCurrentText("Final")
        window.set_raw_frame(raw)
        window.run_analysis()
        self.assertEqual(window.result.result_mode, "final")
        self.assertEqual(captions_for(window), [expected] * 8)

        with TemporaryDirectory() as folder:
            path = window.save_workbook(Path(folder) / "group-wafer-labels.mwkb")
            reopened = MatchingWindow()
            reopened.document.force_close = True
            try:
                reopened.load_workbook(path)
                self.assertEqual(reopened.result.result_mode, "final")
                self.assertEqual(captions_for(reopened), [expected] * 8)
            finally:
                reopened.match_statistics_page.clear()
                APP.processEvents()
                reopened.close()
                reopened.deleteLater()
                APP.processEvents()

        window.group_controls.set_display_groups([], [])
        window.run_analysis(apply_groups=False)
        self.assertEqual(captions_for(window), [((0.5, 1.5, "POR"), (1.5, 3.5, "New"))] * 8)

    def test_statistics_follow_trend_order_and_label_single_wafer_matrix_rows(self):
        self.load(second=False)
        window = self.window
        window.group_controls.restore(
            {"enabled": True, "trend_order": "groups"},
            pd.DataFrame({"TestFlag": [1, 1, 1, 0, 0, 0]}),
        )
        window.run_analysis()
        menu = next(action.menu() for action in window.analysis_menu.actions()
                    if action.text() == "Wafer Mean / Sigma Plot Type")
        bar, line = menu.actions()
        self.assertTrue(bar.isChecked())
        page = window.match_statistics_page
        page.render()
        mean = page.plots_by_parameter["CD"][0]
        self.assertEqual(mean.getAxis("bottom").ticks, [(1., "1"), (2., "2")])
        np.testing.assert_allclose(mean._statistics_bars[1].opts["height"], [4., 3.])
        line.trigger()
        self.assertTrue(line.isChecked())
        self.assertFalse(bar.isChecked())

        page.render()
        mean, sigma, *_ = page.plots_by_parameter["CD"]
        for plot in (mean, sigma):
            reference, raw = plot.listDataItems()
            self.assertGreater(reference.zValue(), raw.zValue())
        raw = mean.listDataItems()[1]
        matrix = window.plot_groups["CD"]["wafer_model"].frame
        self.assertEqual(matrix["Wafer"].tolist(), ["W2", "W1"])
        self.assertEqual(mean.getAxis("bottom").ticks, [(1., str(matrix["Row"].iloc[0])),
                                                      (2., str(matrix["Row"].iloc[1]))])
        self.assertEqual(mean._statistics_group_boundaries.positions, (1.5,))
        np.testing.assert_equal(raw.xData, [1., 2.])
        np.testing.assert_allclose(raw.yData, [4., 3.])
        self.assertEqual(raw.opts["symbol"], "o")

        with TemporaryDirectory() as folder:
            path = window.save_workbook(Path(folder) / "line.mwkb")
            reopened = MatchingWindow()
            reopened.document.force_close = True
            try:
                reopened.load_workbook(path)
                restored = reopened.match_statistics_page
                restored.render()
                self.assertIsInstance(restored.plots_by_parameter["CD"][0].listDataItems()[1],
                                      pg.PlotDataItem)
            finally:
                reopened.match_statistics_page.clear()
                APP.processEvents()
                reopened.close()
                reopened.deleteLater()
                APP.processEvents()

    def test_single_wafer_matrix_divider_starts_at_three_fifths_and_can_move(self):
        self.load(second=False)
        window = self.window
        window.resize(1560, 930)
        window.run_analysis()
        window.results_tabs.setCurrentIndex(1)
        window.show()
        APP.processEvents()
        group = window.plot_groups["CD"]
        splitter = group["wafer_view"].parentWidget()
        self.assertIsInstance(splitter, QSplitter)
        left, right = splitter.sizes()
        self.assertAlmostEqual(left / (left + right), 3 / 5, delta=.02)
        splitter.moveSplitter(splitter.width() // 2, 1)
        self.assertLess(splitter.sizes()[0], left)
        self.assertGreater(splitter.sizes()[1], right)

    def test_statistics_include_only_checked_parameter_mappings(self):
        self.load(second=True)
        self.window.mapping_table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
        self.window.run_analysis()
        page = self.window.match_statistics_page
        self.window.results_tabs.setCurrentWidget(page)
        page.render()
        self.assertEqual(page.rendered_parameters, ("CD",))
        self.assertEqual(set(page.plots_by_parameter), {"CD"})

    def test_match_child_windows_hide_the_wafer_statistics_tab(self):
        self.load(second=False)
        self.window.run_analysis()
        self.window.results_tabs.setCurrentIndex(0)
        child = self.window.open_correlation_workspace()
        index = next(
            index for index in range(child.tabs.count())
            if child.tabs.tabText(index) == "5. Wafer Mean / Sigma"
        )
        self.assertFalse(child.tabs.isTabVisible(index))
        child.document.force_close = True
        child.close()

    def test_single_wafer_metrics_plots_have_draggable_saved_layout(self):
        self.load(second=False)
        self.window.run_analysis()
        group = self.window.plot_groups["CD"]
        area = group["wafer_plot_area"]
        self.assertEqual(set(area.docks), {"wafer_r2", "wafer_slope"})
        changed = QSignalSpy(area.layoutChanged)
        area.moveDock(area.docks["wafer_slope"], "bottom", area.docks["wafer_r2"])
        self.assertEqual(len(changed), 1)
        splitter = area.findChild(QSplitter)
        self.assertIsNotNone(splitter)
        self.assertGreaterEqual(splitter.count(), 2)
        saved = self.window.workspace_snapshot().states["match_ui"]["plot_layouts"]
        self.assertIn("wafer_r2|wafer_slope", saved["preview"]["CD"])

    def test_wafer_statistics_plots_have_draggable_saved_layout(self):
        self.load(second=False)
        self.window.run_analysis()
        page = self.window.match_statistics_page
        page.render()
        area = page.parameter_areas["CD"]
        self.assertEqual(
            set(area.docks),
            {"wafer_mean", "wafer_sigma", "wafer_mean_bias", "wafer_sigma_bias"},
        )
        top = area.topContainer
        self.assertEqual((top.type(), top.count()), ("horizontal", 2))
        self.assertTrue(all(top.widget(index).type() == "vertical" for index in range(2)))
        self.assertTrue(all(top.widget(index).count() == 2 for index in range(2)))
        changed = QSignalSpy(area.layoutChanged)
        area.moveDock(
            area.docks["wafer_sigma_bias"],
            "bottom",
            area.docks["wafer_mean"],
        )
        self.assertEqual(len(changed), 1)
        saved = self.window.workspace_snapshot().states["match_ui"]["plot_layouts"]
        self.assertIn(
            "wafer_mean|wafer_sigma|wafer_mean_bias|wafer_sigma_bias",
            saved["preview"]["CD"],
        )

    def test_mean_sigma_and_bias_use_the_current_match_rows(self):
        self.load(second=False)
        self.window.run_analysis()
        page = self.window.match_statistics_page
        page.render()
        mean_plot, sigma_plot, mean_bias_plot, sigma_bias_plot = page.plots_by_parameter["CD"]
        mean_bars = [item for item in mean_plot.listDataItems() if isinstance(item, pg.BarGraphItem)]
        sigma_bars = [item for item in sigma_plot.listDataItems() if isinstance(item, pg.BarGraphItem)]
        mean_bias_bar = next(item for item in mean_bias_plot.listDataItems()
                             if isinstance(item, pg.BarGraphItem))
        sigma_bias_bar = next(item for item in sigma_bias_plot.listDataItems()
                              if isinstance(item, pg.BarGraphItem))
        np.testing.assert_allclose(mean_bars[0].opts["height"], [4.0, 6.0])
        np.testing.assert_allclose(mean_bars[1].opts["height"], [3.0, 4.0])
        np.testing.assert_allclose(
            sigma_bars[0].opts["height"],
            [np.sqrt(8 / 3), np.sqrt(8 / 3)],
        )
        np.testing.assert_allclose(
            sigma_bars[1].opts["height"],
            [np.sqrt(8 / 3), np.sqrt(8 / 3)],
        )
        np.testing.assert_allclose(mean_bias_bar.opts["height"], [-1.0, -2.0])
        np.testing.assert_allclose(sigma_bias_bar.opts["height"], [0.0, 0.0])
        for plot in (mean_bias_plot, sigma_bias_plot):
            low, high = plot.getViewBox().viewRange()[1]
            self.assertAlmostEqual(low, -high)
            self.assertAlmostEqual(low + high, 0.0)

    def test_opened_workbook_publishes_statistics_without_an_extra_click(self):
        self.load(second=False)
        self.window.run_analysis()
        with TemporaryDirectory() as folder:
            path = Path(folder) / "stats.mwkb"
            self.window.save_workbook(path)
            reopened = MatchingWindow()
            try:
                reopened.document.force_close = True
                reopened.load_workbook(path)
                page = reopened.match_statistics_page
                self.assertIsNotNone(page.result)
                reopened.results_tabs.setCurrentWidget(page)
                APP.processEvents()
                self.assertEqual(page.rendered_parameters, ("CD",))
                self.assertEqual(len(page.plots_by_parameter["CD"]), 4)
            finally:
                reopened.close()
                reopened.deleteLater()
                APP.processEvents()


if __name__ == "__main__":
    unittest.main()
