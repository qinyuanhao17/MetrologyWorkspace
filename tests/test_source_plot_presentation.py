"""Source identity and literal-valued axes are presentation, not data transforms."""
import unittest

import numpy as np
import pandas as pd
from matplotlib.colors import to_hex
from PyQt6.QtWidgets import QApplication

from metrology_app.correlation_window import CorrelationWindow
from metrology_app.matching import ParameterMapping
from metrology_app.matching_window import MatchingWindow
from metrology_app.analysis_export import capture_window, append_report, plot_figure
from metrology_app.plotting import InteractivePlotWidget
from metrology_app.plotting.annotations import plain_y_axes
from openpyxl import Workbook

APP = QApplication.instance() or QApplication([])


class SourcePlotPresentationTests(unittest.TestCase):
    def test_plain_y_tick_format_preserves_small_large_and_negative_values(self):
        widget = InteractivePlotWidget()
        self.addCleanup(widget.deleteLater)
        plain_y_axes(widget)
        for values, spacing, expected in (([1e-7, 2e-7], 1e-7, ["0.0000001", "0.0000002"]),
                                          ([-1000001, -1000000], 1, ["-1000001", "-1000000"]),
                                          ([-1e-15, .25], .25, ["0.00", "0.25"]),
                                          ([2.5, 5], 2.5, ["2.5", "5.0"])):
            with self.subTest(spacing=spacing):
                self.assertEqual(widget.getAxis("left").tickStrings(values, 1, spacing), expected)
        self.assertTrue(widget.getAxis("bottom").autoSIPrefix)

    def close(self, window):
        window.document.force_close = True
        window.close()
        window.deleteLater()
        APP.processEvents()

    def sources(self):
        window = CorrelationWindow()
        self.addCleanup(self.close, window)
        raw = pd.DataFrame({"Wafer ID": ["W1"]*4, "Die Seq": ["01", "02", "03", "04"],
                            "DP": ["0.001000", "0.002000", "0.003000", "0.004000"],
                            "EW": ["1000001", "1000003", "1000004", "1000006"]})
        ref = raw.copy(deep=True)
        ref["DP"] = ["0.001100", "0.002100", "0.003100", "0.004100"]
        ref["EW"] = ["2000002", "2000004", "2000005", "2000007"]
        window.set_sources(ref, raw, [ParameterMapping(name, name, name) for name in ("DP", "EW")])
        return window, ref, raw

    @staticmethod
    def category(fit):
        return frozenset(source for source, _metric in fit.parameter_keys)

    @staticmethod
    def colors(widget):
        items = widget.getPlotItem().listDataItems()
        points = next(item for item in items if item.name().endswith(" points"))
        line = next(item for item in items if item.name().endswith(" fit"))
        return points.opts["symbolBrush"].color().name(), line.opts["pen"].color().name()

    def test_correlation_y_ticks_keep_original_values_on_screen_and_export(self):
        window, ref, raw = self.sources()
        page = window.correlation_page
        page.selector.selectAll()
        page.draw_plot()
        page.finish_background_draw()
        self.assertEqual(len(page.plot_widgets), 6)
        for widget in page.plot_widgets:
            axis = widget.getAxis("left")
            self.assertFalse(axis.autoSIPrefix)
            self.assertEqual(axis.tickStrings([1000001, 1000002, 1000003], 1, 1),
                             ["1000001", "1000002", "1000003"])
        page.ensure_export_figure()
        page.figure.canvas.draw()
        for axis in page.figure.axes:
            formatter = axis.yaxis.get_major_formatter()
            self.assertFalse(formatter.get_useOffset())
            self.assertEqual(formatter.get_offset(), "")
        pd.testing.assert_frame_equal(window.reference_model.document_frame(), ref)
        pd.testing.assert_frame_equal(window.raw_model.document_frame(), raw)

    def test_match_y_ticks_do_not_apply_an_implicit_multiplier(self):
        window = MatchingWindow()
        self.addCleanup(self.close, window)
        window.match_type.setCurrentText("NOVA")
        window.set_reference_frame(pd.DataFrame({"DP Reference": ["0.0011", "0.0021", "0.0031", "0.0041"]}))
        window.set_raw_frame(pd.DataFrame({"Wafer ID": ["W1"]*4, "Die Seq": [1, 2, 3, 4],
                                           "DP": ["0.0010", "0.0020", "0.0030", "0.0040"]}))
        window.run_analysis()
        plot = window.plot_groups["DP"]["plots"]["match"]
        self.assertFalse(plot.getAxis("left").autoSIPrefix)
        self.assertEqual(plot.getAxis("left").tickStrings([1000001, 1000002], 1, 1), ["1000001", "1000002"])
        np.testing.assert_array_equal(plot.listDataItems()[0].yData, [.0011, .0021, .0031, .0041])

    def test_three_pair_categories_have_distinct_stable_colors_and_matching_exports(self):
        window, ref, raw = self.sources()
        page = window.correlation_page
        page.selector.selectAll()
        page.draw_plot()
        page.finish_background_draw()
        self.assertEqual(len(page.plot_widgets), 6)
        colors = {}
        for fit, widget in zip(page.page_fits(), page.plot_widgets):
            category = self.category(fit)
            current = self.colors(widget)
            if category in colors:
                self.assertEqual(current, colors[category])
            colors[category] = current
        self.assertEqual(len(colors), 3)
        self.assertEqual(len({color[0] for color in colors.values()}), 3)
        self.assertEqual(len({color[1] for color in colors.values()}), 3)
        self.assertEqual(colors[frozenset(('Reference', 'Raw Data'))], ('#009e73', '#006b4f'))
        cross = next(fit for fit in page.page_fits() if len(self.category(fit)) == 2)
        page.swap_axes(cross)
        for fit, widget in zip(page.page_fits(), page.plot_widgets):
            self.assertEqual(self.colors(widget), colors[self.category(fit)])
            self.assertFalse(widget.getAxis("left").autoSIPrefix)
        page.ensure_export_figure()
        for fit, axis in zip(page.page_fits(), page.figure.axes):
            self.assertEqual((to_hex(axis.collections[0].get_facecolors()[0]),
                              to_hex(axis.lines[0].get_color())), colors[self.category(fit)])
        pd.testing.assert_frame_equal(window.reference_model.document_frame(), ref)
        pd.testing.assert_frame_equal(window.raw_model.document_frame(), raw)

    def test_new_trend_y_axes_name_their_ref_or_raw_source_in_screen_and_export(self):
        window, _ref, _raw = self.sources()
        page = window.sequence_page
        page.source_overlay, page.overlay = {}, {}
        page.restore_axis_mode("dual")
        page.selector.selectAll()
        page.draw_plot()
        for primary, secondary in (("Reference", "Raw Data"), ("Raw Data", "Reference")):
            with self.subTest(primary=primary):
                self.assertTrue(page.set_overlay("DP", "DP", primary_source=primary, secondary_source=secondary))
                self.assertTrue(page.set_overlay("DP", "EW", primary_source=primary, secondary_source=primary))
                spec_index = next(index for index, spec in enumerate(page.display_panel_specs())
                                  if spec["source"]["name"] == primary and spec["metric"] == "DP")
                widget = page.plot_widgets[spec_index]
                self.assertEqual(len(widget.secondary_axes), 2)
                self.assertIn(secondary, widget.secondary_axes[0].labelText)
                self.assertIn(primary, widget.secondary_axes[1].labelText)
                self.assertEqual(widget.secondary_axes[1].tickStrings([1000001, 1000002], 1, 1),
                                 ["1000001", "1000002"])
        page.ensure_export_figure()
        labels = [axis.get_ylabel() for axis in page.figure.axes]
        self.assertTrue(any("Raw Data" in label and "EW" in label for label in labels))
        self.assertTrue(any("Reference" in label and "EW" in label for label in labels))

    def test_excel_correlation_preserves_pair_colors_in_native_and_matplotlib_reports(self):
        window, _ref, _raw = self.sources()
        page = window.correlation_page
        page.selector.selectAll()
        page.draw_plot()
        report = capture_window(window)
        plots = [plot for plot in report["plots"] if plot["sheet"] == "Correlation"]
        expected = [self.colors(widget) for widget in page.plot_widgets]
        self.assertEqual(len(expected), 6)
        self.assertEqual(len(plots), 6)
        for plot, colors in zip(plots, expected):
            self.assertEqual(tuple(item.get("color") for item in plot["series"]), colors)
            self.assertTrue(all(list(item["data"].columns) == ["X", "Y"] for item in plot["series"]))
            figure = plot_figure(plot)
            self.assertEqual((to_hex(figure.axes[0].collections[0].get_facecolors()[0]),
                              to_hex(figure.axes[0].lines[0].get_color())), colors)
        book = Workbook()
        append_report(book, set(), report, native=True)
        self.assertEqual(len(book["Correlation"]._charts), 6)
        for chart, colors in zip(book["Correlation"]._charts, expected):
            self.assertEqual("#" + chart.series[0].marker.graphicalProperties.solidFill.srgbClr.lower(), colors[0])
            self.assertEqual("#" + chart.series[1].graphicalProperties.line.solidFill.srgbClr.lower(), colors[1])

    def test_excel_trend_secondary_axes_keep_same_unit_sources_distinct_and_labeled(self):
        window, _ref, _raw = self.sources()
        page = window.sequence_page
        page.source_overlay, page.overlay = {}, {}
        page.restore_axis_mode("dual")
        page.selector.selectAll()
        page.draw_plot()
        page.set_overlay("DP", "DP", primary_source="Reference", secondary_source="Raw Data")
        # Another Ref parameter shares the unit but is a separate added axis.
        page.set_overlay("DP", "EW", primary_source="Reference", secondary_source="Reference")
        report = capture_window(window)
        plot = next(plot for plot in report["plots"] if plot["title"] == "Reference · DP")
        secondary = [item for item in plot["series"] if item.get("secondary")]
        self.assertEqual(len(secondary), 2)
        self.assertIn("Raw Data", secondary[0].get("axis_label", ""))
        self.assertIn("Reference", secondary[1].get("axis_label", ""))
        figure = plot_figure(plot)
        self.assertEqual(len(figure.axes), 3)
        self.assertIn("Raw Data", figure.axes[1].get_ylabel())
        self.assertIn("Reference", figure.axes[2].get_ylabel())
        book = Workbook()
        append_report(book, set(), report, native=True)
        chart_labels = [paragraph.r[0].t for chart in book["Trend"]._charts[:2]
                        for paragraph in chart._charts[1].y_axis.title.tx.rich.p]
        self.assertTrue(any("Raw Data" in label for label in chart_labels))
        self.assertTrue(any("Reference" in label for label in chart_labels))
