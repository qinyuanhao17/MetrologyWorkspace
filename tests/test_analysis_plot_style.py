"""Analysis plots share Workbook styling without changing their observations."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pandas as pd
import pyqtgraph as pg
from matplotlib.colors import to_hex
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from metrology_app.correlation_page import CorrelationPage
from metrology_app.correlation_window import CorrelationWindow
from metrology_app.matching import ParameterMapping
from metrology_app.sequence_page import SequencePage
from metrology_app.settings import get_settings, save_settings

APP = QApplication.instance() or QApplication([])


class AnalysisPlotStyleTests(unittest.TestCase):
    def setUp(self):
        previous = get_settings()
        save_settings({"trend_overlay": {}, "trend_source_overlay": None})
        self.addCleanup(save_settings, previous)

    def source_window(self):
        raw = pd.DataFrame({"Wafer ID": ["001"] * 4, "Die Seq": ["002", "036", "050", "085"],
                            "CD": ["1.000", "2.000", "3.000", "4.000"],
                            "Depth": ["1.000", "2.000", "2.000", "5.000"]})
        reference = raw.copy(deep=True)
        reference["CD"] = ["11.000", "12.000", "13.000", "14.000"]
        window = CorrelationWindow()
        self.addCleanup(APP.processEvents)
        self.addCleanup(window.deleteLater)
        self.addCleanup(self.close_window, window)
        window.document.timer.stop()
        window.set_sources(reference, raw, (ParameterMapping("CD", "CD", "CD"),
                                            ParameterMapping("Depth", "Depth", "Depth")))
        return window

    @staticmethod
    def close_window(window):
        window.document.force_close = True
        window.close()

    def test_standalone_correlation_has_workbook_blue_points_and_orange_fit_in_export_too(self):
        frame = pd.DataFrame({"Wafer ID": ["001"] * 4,
                              "CD": ["1.000", "2.000", "3.000", "4.000"],
                              "Depth": ["1.000", "2.000", "2.000", "5.000"]})
        page = CorrelationPage()
        self.addCleanup(APP.processEvents)
        self.addCleanup(page.deleteLater)
        page.set_input(frame, {"wafer_column": "Wafer ID", "wafers": ["001"],
                               "metrics": ["CD", "Depth"], "groups": {"001": range(4)}})
        page.selector.selectAll()
        page.draw_plot()
        plot = page.plot_widgets[0].getPlotItem()
        points = next(item for item in plot.items if isinstance(item, pg.ScatterPlotItem))
        fit_line = next(item for item in plot.listDataItems() if isinstance(item, pg.PlotDataItem))
        self.assertEqual(points.opts["brush"].color().name(), "#4f8bd6")
        self.assertEqual(points.opts["brush"].color().alpha(), 255)
        self.assertEqual(points.opts["size"], 5)
        self.assertEqual(fit_line.opts["pen"].color().name(), "#e09f3e")
        np.testing.assert_array_equal(points.getData()[0], [1., 2., 3., 4.])
        np.testing.assert_array_equal(points.getData()[1], [1., 2., 2., 5.])
        page.ensure_export_figure()
        axis = page.figure.axes[0]
        self.assertEqual(to_hex(axis.collections[0].get_facecolors()[0]), "#4f8bd6")
        self.assertEqual(axis.collections[0].get_alpha(), 1)
        self.assertEqual(to_hex(axis.lines[0].get_color()), "#e09f3e")
        np.testing.assert_allclose(axis.lines[0].get_ydata(), [.7, 1.9, 3.1, 4.3])
        pd.testing.assert_frame_equal(page.frame, frame)

    def test_ref_and_raw_correlation_share_style_and_keep_it_when_swapping_axes(self):
        window = self.source_window()
        before = window.raw_model.frame().copy(deep=True)
        page = window.correlation_page
        page.selector.selectAll()
        page.draw_plot()
        self.assertEqual(len(page.plot_widgets), 2)
        for widget in page.plot_widgets:
            items = {item.name(): item for item in widget.getPlotItem().listDataItems()}
            points = next(item for name, item in items.items() if name.endswith(" points"))
            line = next(item for name, item in items.items() if name.endswith(" fit"))
            self.assertEqual(points.opts["symbolBrush"].color().name(), "#4f8bd6")
            self.assertEqual(points.opts["symbolSize"], 5)
            self.assertEqual(line.opts["pen"].color().name(), "#e09f3e")
        widgets = list(page.plot_widgets)
        page.swap_axes(page.page_fits()[0])
        self.assertEqual(page.plot_widgets, widgets)
        self.assertEqual(widgets[0].getPlotItem().getAxis("bottom").labelText, "Depth")
        page.ensure_export_figure()
        for axis in page.figure.axes:
            self.assertEqual(to_hex(axis.collections[0].get_facecolors()[0]), "#4f8bd6")
            self.assertEqual(to_hex(axis.lines[0].get_color()), "#e09f3e")
        pd.testing.assert_frame_equal(window.raw_model.frame(), before)

    def test_trend_sources_and_comparisons_use_only_colors_not_shapes_or_dashes(self):
        window = self.source_window()
        before = window.raw_model.frame().copy(deep=True)
        page = window.sequence_page
        page.selector.selectAll()
        page.draw_plot()
        self.assertTrue(page.set_overlay("CD", "CD", primary_source="Reference",
                                         secondary_source="Raw Data"))
        comparison_items = list(page.plot_widgets[0].getPlotItem().listDataItems())
        comparison_items.extend(item for view in page.plot_widgets[0].secondary_views
                                for item in view.addedItems if isinstance(item, pg.PlotDataItem))
        items = [item for widget in page.plot_widgets for item in widget.getPlotItem().listDataItems()]
        items.extend(comparison_items)
        self.assertGreaterEqual(len(comparison_items), 2)
        self.assertEqual({item.opts["symbol"] for item in items}, {"o"})
        self.assertEqual({item.opts["pen"].style() for item in items}, {Qt.PenStyle.SolidLine})
        self.assertEqual(len({item.opts["pen"].color().name() for item in comparison_items}), 2)
        comparison = next(item for item in comparison_items if item.name() == "Raw Data · CD")
        np.testing.assert_array_equal(comparison.getData()[1], [1., 2., 3., 4.])
        page.ensure_export_figure()
        lines = [line for axis in page.figure.axes for line in axis.lines
                 if line.get_label().startswith(("Reference · ", "Raw Data · "))]
        self.assertGreaterEqual(len(lines), 5)
        self.assertEqual({line.get_marker() for line in lines}, {"o"})
        self.assertEqual({line.get_linestyle() for line in lines}, {"-"})
        self.assertEqual({text.get_text() for text in page.figure.axes[0].get_legend().get_texts()},
                         {"Reference · CD", "Raw Data · CD"})
        pd.testing.assert_frame_equal(window.raw_model.frame(), before)

    def test_standalone_trend_and_comparison_share_workbook_point_and_line_style(self):
        frame = pd.DataFrame({"Wafer ID": ["001"] * 4, "Die Seq": [2, 36, 50, 85],
                              "CD": [1., 2., 3., 4.], "Depth": [1., 2., 2., 5.]})
        page = SequencePage()
        self.addCleanup(APP.processEvents)
        self.addCleanup(page.deleteLater)
        page.set_input(frame, {"wafer_column": "Wafer ID", "wafers": ["001"],
                               "metrics": ["CD", "Depth"], "groups": {"001": range(4)}})
        page.selector.selectAll()
        page.draw_plot()
        original = page.plot_widgets[0].listDataItems()[0]
        self.assertEqual(original.opts["pen"].color().name(), "#5b9bd5")
        self.assertEqual(original.opts["pen"].widthF(), 2.2)
        self.assertEqual(original.opts["symbolSize"], 5)
        self.assertTrue(page.set_overlay("CD", "Depth"))
        widget = page.plot_widgets[0]
        items = list(widget.listDataItems())
        items.extend(item for view in widget.secondary_views
                     for item in view.addedItems if isinstance(item, pg.PlotDataItem))
        self.assertEqual(len(items), 2)
        self.assertEqual({item.opts["symbol"] for item in items}, {"o"})
        self.assertEqual({item.opts["pen"].style() for item in items}, {Qt.PenStyle.SolidLine})
        self.assertEqual({item.opts["symbolSize"] for item in items}, {5})
        self.assertEqual({item.opts["pen"].widthF() for item in items}, {2.2})
        self.assertEqual(len({item.opts["pen"].color().name() for item in items}), 2)
        page.ensure_export_figure()
        lines = [line for axis in page.figure.axes for line in axis.lines
                 if line.get_label() in {"CD", "Depth"}]
        self.assertEqual({line.get_marker() for line in lines}, {"o"})
        self.assertEqual({line.get_linestyle() for line in lines}, {"-"})
        pd.testing.assert_frame_equal(page.frame, frame)


if __name__ == "__main__":
    unittest.main()
