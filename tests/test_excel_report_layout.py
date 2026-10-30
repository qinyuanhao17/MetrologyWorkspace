"""Report layout through the two public Workbook export commands."""
import math
from pathlib import Path
import tempfile
import unittest

import pandas as pd
from openpyxl import load_workbook

from tests import test_excel_export as fixtures


class ExcelReportLayoutTests(unittest.TestCase):
    # Reuse only the public fixture/lifecycle, not the older test cases.
    tearDown = fixtures.ExcelExportTests.tearDown
    frames = fixtures.ExcelExportTests.frames
    export = fixtures.ExcelExportTests.export

    def setUp(self):
        self.window = fixtures.MatchingWindow()
        self.window.match_type.setCurrentText("NOVA")

    def test_continuous_x_limits_follow_only_drawable_pairs_without_outer_tick_rounding(self):
        import numpy as np
        from metrology_app.analysis_export import plot_figure, append_report
        from openpyxl import Workbook
        for title in ('Correlation', 'Trend'):
            plot = {'sheet': title, 'title': 'CD', 'x': 'PMISH', 'y': 'NOVA',
                    'series': [{'name': 'NOVA', 'data': pd.DataFrame({
                        'X': [10., 10.1, 10.2, 999.], 'Y': [20., 21., 22., np.nan]})}]}
            figure = plot_figure(plot)
            try:
                self.assertAlmostEqual(figure.axes[0].get_xlim()[0], 9.995)
                self.assertAlmostEqual(figure.axes[0].get_xlim()[1], 10.205)
            finally:
                figure.clear()
            book = Workbook()
            append_report(book, set(), {'suffix': '', 'frames': {}, 'pictures': [], 'plots': [plot]})
            chart = book[title]._charts[0]
            self.assertAlmostEqual(chart.x_axis.scaling.min, 9.995)
            self.assertAlmostEqual(chart.x_axis.scaling.max, 10.205)

    def test_match_and_trend_use_readable_strokes_and_reference_is_solid_on_top(self):
        from metrology_app.excel_export import parameter_figure
        data = pd.DataFrame({'Raw': [10., 10.1, 10.2], 'Reference': [10., 10.1, 10.2]})
        for reference in ('TEM', 'NOVA', 'KLA'):
            figure = parameter_figure('CD', data, None, 'Final', 'All', panel='Trend', reference_label=reference)
            try:
                raw, ref = figure.axes[0].lines[:2]
                self.assertEqual(ref.get_linestyle(), '-')
                self.assertGreater(ref.get_zorder(), raw.get_zorder())
                self.assertTrue(all(line.get_linewidth() == 2.5 for line in (raw, ref)))
                self.assertTrue(all(line.get_markersize() == 6 for line in (raw, ref)))
                self.assertTrue(all(spine.get_linewidth() >= 1.2 for spine in figure.axes[0].spines.values()))
            finally:
                figure.clear()
        figure = parameter_figure('CD', data, None, 'Final', 'All')
        try:
            self.assertAlmostEqual(figure.axes[0].get_xlim()[0], 9.995)
            self.assertAlmostEqual(figure.axes[0].get_xlim()[1], 10.205)
            self.assertGreaterEqual(figure.axes[0].collections[0].get_sizes()[0], 25)
        finally:
            figure.clear()

    def test_all_match_sheets_stack_right_panels_with_uniform_gaps(self):
        from metrology_app.excel_export import PANEL_HEIGHT_CM
        reference = pd.DataFrame({
            "CD Reference": [3., 5., 7.],
            "Depth Reference": [9., 11., 13.],
        })
        raw = pd.DataFrame({
            "Wafer ID": ["W1"] * 3, "Die Seq": [1, 2, 3],
            "CD": ["1.000", "2.000", "3.000"],
            "Depth": ["2.000", "4.000", "6.000"],
            "TestFlag": [0, 1, 0],
        })
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.group_controls.restore(
            {"enabled": True, "head_names": {"0": "Head A", "1": "Head B"}},
            raw[["TestFlag"]])
        self.window.group_controls.apply_button.click()
        self.window.run_analysis()
        with tempfile.TemporaryDirectory() as folder:
            for native in (True, False):
                path = self.window.export_excel(
                    Path(folder) / f"spacing-{native}.xlsx", native=native)
                book = load_workbook(path)
                match_sheets = [
                    name for name in book.sheetnames
                    if name.startswith("Match ")]
                self.assertIn("Match Original (WO Card)", match_sheets)
                self.assertIn("Match Group (WO Card)", match_sheets)
                self.assertIn("Match Wafer (WO Card)", match_sheets)
                self.assertIn("Match Head A (WO Card)", match_sheets)
                for sheet_name in match_sheets:
                    sheet = book[sheet_name]
                    charts = sheet._charts if native else sheet._images
                    self.assertGreaterEqual(len(charts), 6, sheet_name)
                    self.assertEqual(len(charts) % 3, 0)
                    positions = [
                        tuple(value * 2.54 / 96 for value in
                              fixtures.drawing_xy_px(chart, sheet))
                        for chart in charts]
                    for base in range(0, len(charts), 3):
                        match, trend, bias = positions[base:base + 3]
                        match_width = (
                            charts[base].anchor.ext.cx / 360000)
                        self.assertAlmostEqual(
                            match[1], trend[1], places=2)
                        self.assertAlmostEqual(
                            trend[0] - match[0] - match_width,
                            1.0, places=2)
                        self.assertAlmostEqual(
                            bias[0], trend[0], places=2)
                        self.assertAlmostEqual(
                            bias[1] - trend[1] - PANEL_HEIGHT_CM,
                            0.5, places=2)
                        if base + 3 < len(charts):
                            next_match = positions[base + 3]
                            self.assertAlmostEqual(
                                next_match[1] - match[1],
                                2 * (PANEL_HEIGHT_CM + 0.5),
                                places=2)

    def test_wide_match_wafer_is_one_complete_untitled_chart(self):
        import re

        wafer_count = 12
        labels = [f"WAFER-{index:02d}-IDENTITY-ABCDEFGHIJKLMN"
                  for index in range(wafer_count)]
        raw = pd.DataFrame({
            "Wafer ID": labels,
            "Lot ID": [f"LOT-{index:02d}-REFERENCE-ABCDEFGHIJKLMN"
                       for index in range(wafer_count)],
            "PAD Name": [f"PAD-{index:02d}-MEASUREMENT" for index in range(wafer_count)],
            "Die Seq": [1] * wafer_count,
            "CD": [str(index + 1) for index in range(wafer_count)],
            "Depth": [str(index + 2) for index in range(wafer_count)],
        })
        reference = pd.DataFrame({
            "CD Reference": [index + 2 for index in range(wafer_count)],
            "Depth Reference": [index + 3 for index in range(wafer_count)],
        })
        self.window.percent_bias.setChecked(True)
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.run_analysis()

        def title_text(chart):
            if isinstance(chart.title, str):
                return chart.title
            rich = chart.title.tx.rich
            return "".join(run.t for paragraph in rich.p for run in paragraph.r)

        def rectangles(drawings, sheet):
            result = []
            for drawing in drawings:
                x, y = fixtures.drawing_xy_px(drawing, sheet)
                result.append((x, y, drawing.anchor.ext.cx / 9525,
                               drawing.anchor.ext.cy / 9525))
            return result

        with tempfile.TemporaryDirectory() as folder:
            for native in (True, False):
                images = []
                path = self.window.export_excel(
                    Path(folder) / f"complete-wafer-{native}.xlsx",
                    native=native, images=images)
                sheet = load_workbook(path)["Match Wafer (WO Card)"]
                drawings = sheet._charts if native else sheet._images
                page_labels = set()
                if native:
                    page_labels = {
                        label for chart in drawings
                        for label in re.findall(r"Page \d+/\d+", title_text(chart))}
                else:
                    page_labels = {
                        label for item in images
                        for label in re.findall(r"Page \d+/\d+", item[0])}
                self.assertEqual(page_labels, set())
                self.assertEqual(len(drawings), 2 * 4)
                self.assertGreater(
                    drawings[1].anchor.ext.cx / 360000, 45)

                boxes = rectangles(drawings, sheet)
                positions_cm = [
                    tuple(value * 2.54 / 96 for value in (x, y))
                    for x, y, _width, _height in boxes]
                for base in range(0, len(drawings), 4):
                    match, trend, bias, percent = positions_cm[
                        base:base + 4]
                    self.assertAlmostEqual(match[1], trend[1])
                    self.assertAlmostEqual(trend[0], bias[0])
                    self.assertAlmostEqual(trend[0], percent[0])
                    self.assertAlmostEqual(
                        bias[1] - trend[1], 11.5)
                    self.assertAlmostEqual(
                        percent[1] - bias[1], 11.5)
                for index, left in enumerate(boxes):
                    for right in boxes[index + 1:]:
                        separated = (
                            left[0] + left[2] <= right[0] + .5
                            or right[0] + right[2] <= left[0] + .5
                            or left[1] + left[3] <= right[1] + .5
                            or right[1] + right[3] <= left[1] + .5)
                        self.assertTrue(separated, (native, left, right))
                if native:
                    trend = [
                        chart for chart in drawings
                        if title_text(chart) == "CD"
                        and len(chart.series) == 2]
                    def category_count(chart):
                        categories = chart.series[0].cat.strRef
                        self.assertEqual(categories.f,
                                         "'Match Wafer (WO Card)'!$B$3:$B$14")
                        self.assertEqual([point.v for point in categories.strCache.pt],
                                         ['1'] * wafer_count)
                        return len(categories.strCache.pt)
                    self.assertEqual(
                        sum(category_count(chart) for chart in trend),
                        wafer_count)

    def test_wide_wafer_layout_has_dense_die_seq_ticks(self):
        from metrology_app.excel_export import sequence_export_layout

        rows = [
            {
                "Wafer": f"WAFER-{wafer:02d}",
                "Wafer key": (wafer,),
                "Die Seq": str(die + 1),
                "Raw": 1.,
                "Reference": 1.,
            }
            for wafer in range(60)
            for die in range(10)
        ]
        layout = sequence_export_layout(pd.DataFrame(rows), mode="wafer")
        self.assertGreater(len(layout["ticks"]), 18)
        self.assertEqual(len(layout["ticks"]),
                         len(layout["tick_indices"]))
        for left, right in zip(
                layout["display"], layout["display"][1:]):
            span_labels = [
                int(label)
                for position, label in layout["ticks"]
                if left <= position < right]
            self.assertTrue(span_labels)
            self.assertEqual(span_labels, sorted(span_labels))

    def test_child_trend_reference_stays_orange_and_above_raw_independent_of_selection_order(self):
        from metrology_app.analysis_export import plot_figure, append_report
        from openpyxl import Workbook
        data = pd.DataFrame({'X': [1., 2., 3.], 'Y': [2., 4., 3.]})
        plot = {'sheet': 'Trend', 'title': 'CD', 'x': 'Die Seq', 'y': 'CD', 'series': [
            {'name': 'Reference · CD', 'source': 'Reference', 'data': data.copy()},
            {'name': 'Raw Data · CD', 'source': 'Raw Data', 'data': data.copy()}]}
        figure = plot_figure(plot)
        try:
            reference, raw = figure.axes[0].lines
            self.assertEqual(reference.get_color(), '#ED7D31')
            self.assertEqual(reference.get_linestyle(), '-')
            self.assertGreater(reference.get_zorder(), raw.get_zorder())
        finally:
            figure.clear()
        book = Workbook()
        append_report(book, set(), {'suffix': '', 'frames': {}, 'pictures': [], 'plots': [plot]})
        chart = book['Trend']._charts[0]
        self.assertEqual(chart.series[-1].tx.v, 'Reference · CD')
        self.assertEqual(chart.series[-1].graphicalProperties.line.solidFill.srgbClr, 'ED7D31')
        self.assertEqual(chart.series[-1].graphicalProperties.line.prstDash, 'solid')
        # Draw order must not reorder or replace the source records in the report.
        self.assertEqual(book['Trend']['A4'].value, 'Reference · CD')
        pd.testing.assert_frame_equal(plot['series'][0]['data'], data)

    def test_native_charts_have_four_sided_frame_and_readable_solid_reference(self):
        reference, raw = self.frames()
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.run_analysis()
        with tempfile.TemporaryDirectory() as folder:
            book = self.export(folder)
            match, trend, bias = book['Match Original (WO Card)']._charts
            from zipfile import ZipFile
            from xml.etree import ElementTree as ET
            ns = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
                  'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
            with ZipFile(Path(folder) / 'export.xlsx') as archive:
                for index in (1, 2, 3):
                    xml = ET.fromstring(archive.read(f'xl/charts/chart{index}.xml'))
                    frame = xml.find('c:chart/c:plotArea/c:spPr/a:ln', ns)
                    self.assertGreaterEqual(int(frame.get('w')), 15240)
                    self.assertIsNotNone(frame.find('a:solidFill', ns))
            for chart in (match, trend, bias):
                for axis in (chart.x_axis, chart.y_axis):
                    self.assertGreaterEqual(axis.spPr.ln.w, 15240)
            self.assertGreaterEqual(match.series[0].marker.size, 5)
            self.assertEqual(match.x_axis.numFmt.formatCode, '0.00',
                             'A tight .95 boundary must not be labelled as integer 1')
            self.assertEqual(trend.series[-1].tx.strRef.f, "'Match Original (WO Card)'!E2")
            self.assertTrue(all(series.graphicalProperties.line.prstDash == 'solid'
                                for series in trend.series))
            self.assertTrue(all(series.graphicalProperties.line.w == 31750
                                for series in trend.series))
            self.assertTrue(all(series.marker.size == 6 for series in trend.series))

    def test_group_reference_curves_overlay_later_raw_groups_without_losing_group_colours(self):
        from metrology_app.analysis_export import plot_figure
        data = pd.DataFrame({'X': [1., 2., 3.], 'Y': [2., 4., 3.]})
        series = [{'name': name, 'data': data.copy(), 'reference': reference}
                  for name, reference in [('A PMISH', False), ('A NOVA', True),
                                          ('B PMISH', False), ('B NOVA', True)]]
        figure = plot_figure({'title': 'Group trends', 'x': 'Row', 'y': 'CD', 'series': series})
        try:
            lines = figure.axes[0].lines
            self.assertGreater(lines[1].get_zorder(), lines[2].get_zorder())
            self.assertGreater(lines[3].get_zorder(), lines[0].get_zorder())
            self.assertEqual([line.get_color() for line in lines],
                             ['#5B9BD5', '#ED7D31', '#70AD47', '#A879C2'])
            self.assertTrue(all(line.get_linestyle() == '-' for line in lines))
        finally:
            figure.clear()

    def test_compact_match_table_in_both_renderers(self):
        reference, raw = self.frames()
        raw["Lot ID"], raw["PAD Name"] = "L1", "ARRAY"
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.run_analysis()
        before = self.window.workspace_snapshot()
        with tempfile.TemporaryDirectory() as folder:
            books = []
            for native in (True, False):
                book = load_workbook(self.window.export_excel(Path(folder) / f"{native}.xlsx", native=native))
                books.append(book)
                self.assertEqual([s.title for s in book if s.sheet_state == "visible"],
                                 ["Match Original (WO Card)", "Match Wafer (WO Card)", "RSQ (WO Card)"])
                sheet = book["Match Original (WO Card)"]
                self.assertEqual(sheet["A1"].value, "CD")
                self.assertEqual(fixtures.source_cell(sheet, 'CD', 2).value, "1.000")
                headers = next(row for row in sheet.values if "PMISH+Card" in row)
                self.assertEqual(headers[:7], ("Wafer", "Die Seq", "PMISH", "PMISH+Card", "NOVA", "Bias", "Bias %"))
                header_row = next(cell.row for row in sheet for cell in row if cell.value == "PMISH+Card")
                self.assertIn("LOT: L1", sheet.cell(header_row + 1, 1).value)
                self.assertIn("PAD: ARRAY", sheet.cell(header_row + 1, 1).value)
                objects = sheet._charts if native else sheet._images
                self.assertTrue(objects)
                cells = [fixtures.drawing_cell(obj, sheet) for obj in objects]
                self.assertEqual(cells[0][1], 4)
                self.assertEqual(cells[1][1], 4)
                self.assertGreater(cells[2][1], cells[1][1])
                self.assertEqual(cells[0][0], 0)
                values = [c.value for row in sheet for c in row]
                self.assertNotIn("Card source", values)
                self.assertNotIn("Source row", values)
            self.assertEqual(list(books[0]["Match Original (WO Card)"].values), list(books[1]["Match Original (WO Card)"].values))
        after = self.window.workspace_snapshot()
        self.assertEqual(before.states, after.states)
        for name in before.frames:
            pd.testing.assert_frame_equal(before.frames[name], after.frames[name])

    def test_final_table_omits_second_card_column(self):
        reference, raw = self.frames()
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.result_mode.setCurrentText("Final")
        self.window.set_raw_frame(raw.assign(CD=["3.000", "5.000", "7.000"]))
        self.window.run_analysis()
        with tempfile.TemporaryDirectory() as folder:
            book = self.export(folder)
            sheet = book["Match Original (W Card)"]
            headers = next(row for row in sheet.values if "Bias %" in row)
            self.assertEqual(headers[:6], ("Wafer", "Die Seq", "PMISH", "NOVA", "Bias", "Bias %"))
            self.assertNotIn("PMISH+Card", [c.value for row in sheet for c in row])
            row = next(c.row for cells in sheet for c in cells if c.value == "PMISH") + 1
            source = fixtures.source_cell(sheet, 'CD', 2)
            self.assertEqual(source.value, "3.000")
            self.assertIn(f"'Match Original (W Card)'!${source.column_letter}$2", sheet.cell(row, 3).value)

    def test_export_opens_at_match_original_plots(self):
        reference, raw = self.frames()
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.run_analysis()
        with tempfile.TemporaryDirectory() as folder:
            for native in (True, False):
                book = load_workbook(self.window.export_excel(Path(folder) / f'opening-{native}.xlsx', native=native))
                self.assertEqual(book.active.title, 'Match Original (WO Card)')
                self.assertEqual(book.active.sheet_view.pane.topLeftCell, 'A3')
                self.assertIn(book.active.sheet_view.topLeftCell, (None, 'A1'))
                self.assertEqual(book.active.sheet_view.selection[-1].activeCell, 'A1')
                sheet = book['Match Original (WO Card)']
                self.assertEqual(fixtures.source_cell(sheet, 'CD', 2).value, '1.000')
                if native:
                    self.assertEqual(len(sheet._charts), 3)
                    self.assertEqual(sheet._images, [])
                else:
                    self.assertEqual(sheet._charts, [])
                    self.assertEqual(len(sheet._images), 3)

    def test_both_renderers_use_physical_panel_sizes_and_full_width_parameter_heading(self):
        reference, raw = self.frames()
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.run_analysis()
        with tempfile.TemporaryDirectory() as folder:
            for native in (True, False):
                book = load_workbook(self.window.export_excel(Path(folder) / f"sizes-{native}.xlsx", native=native))
                sheet = book["Match Original (WO Card)"]
                objects = sheet._charts if native else sheet._images
                self.assertEqual(len(objects), 3, "Match, Trend and Bias must be independently sized panels")
                dimensions = [(obj.anchor.ext.cx / 360000, obj.anchor.ext.cy / 360000) for obj in objects]
                for actual, expected in zip(dimensions, ((15, 11), (25, 11), (25, 11))):
                    self.assertAlmostEqual(actual[0], expected[0], places=3)
                    self.assertAlmostEqual(actual[1], expected[1], places=3)
                self.assertIn("A1:G1", {str(area) for area in sheet.merged_cells.ranges})
                self.assertEqual(sheet["A1"].value, "CD")
                rows = [
                    fixtures.drawing_cell(obj, sheet)[1]
                    for obj in objects]
                self.assertEqual(rows[0], 4)
                self.assertEqual(rows[1], 4)
                self.assertGreater(rows[2], rows[1])

    def test_long_identity_charts_use_tight_physical_side_margins(self):
        from openpyxl import Workbook
        from openpyxl.chart import LineChart
        from metrology_app.excel_export import (
            parameter_figure, sequence_layout, style_workbook)

        width_cm = 60.
        chart = LineChart()
        chart.width, chart.height = width_cm, 11
        chart._identity_captions = [{
            'text': 'Old MM1', 'source': "'Match Group'!A3",
            'start': 0., 'end': 1., 'center': .5,
            'role': 'group', 'level': 0, 'show': True,
        }]
        book = Workbook()
        sheet = book.active
        sheet.title = 'Match Group'
        sheet.add_chart(chart, 'A1')
        style_workbook(book)
        manual = sheet._charts[0].layout.manualLayout
        left_cm = manual.x * width_cm
        right_cm = (1 - manual.x - manual.w) * width_cm
        self.assertAlmostEqual(left_cm, 3., places=2)
        self.assertAlmostEqual(right_cm, .7, places=2)

        data = pd.DataFrame({
            "Raw": [1., 2., 3.],
            "Reference": [2., 3., 4.],
            "Die Seq": ["1", "2", "3"],
        })
        sequence = sequence_layout(["Old MM1"] * 3, name="Group")
        sequence["width"] = sequence["native_width"] = width_cm
        figure = parameter_figure(
            "CD", data, None, "Final", "Group",
            panel="Trend", sequence=sequence)
        try:
            figure.canvas.draw()
            axis_box = figure.axes[0].get_position()
            figure_width_cm = figure.get_figwidth() * 2.54
            self.assertAlmostEqual(
                axis_box.x0 * figure_width_cm, 3., places=2)
            self.assertAlmostEqual(
                (1 - axis_box.x1) * figure_width_cm, .7, places=2)
        finally:
            figure.clear()

    def test_group_overview_and_complete_wafer_detail_export_side_by_side_in_both_modes(self):
        raw = pd.DataFrame({"Wafer ID": [f"WAFER-{index:03}" for index in range(20) for _ in range(3)],
            "Lot ID": ["LOT-001"] * 60, "PAD Name": ["ARRAY"] * 60, "Die Seq": [1, 2, 3] * 20,
            "CD": [str(index + 1) for index in range(60)], "TestFlag": [0] * 30 + [1] * 30})
        self.window.set_reference_frame(pd.DataFrame({"CD Reference": [2 * index + 3 for index in range(60)]}))
        self.window.set_raw_frame(raw)
        self.window.group_controls.restore({"enabled": True, "head_names": {"0": "Head A", "1": "Head B"}}, raw[["TestFlag"]])
        self.window.group_controls.apply_button.click()
        with tempfile.TemporaryDirectory() as folder:
            for native in (True, False):
                book = load_workbook(self.window.export_excel(Path(folder) / f"identities-{native}.xlsx", native=native))
                sheet = book["Match Original (WO Card)"]
                panels = sheet._charts if native else sheet._images
                self.assertEqual(len(panels), 3, 'Original has its own Match, Die Trend and Bias')
                dimensions = [panel.anchor.ext.cx / 360000 for panel in panels]
                self.assertEqual(dimensions[0], 15)
                self.assertGreaterEqual(dimensions[1], 25)
                cells = [fixtures.drawing_cell(panel, sheet) for panel in panels]
                self.assertEqual(cells[0][1], cells[1][1])
                self.assertLess(cells[0][0], cells[1][0])
                self.assertEqual(cells[1][0], cells[2][0])
                self.assertLess(cells[1][1], cells[2][1])
                if native:
                    wafer_sheet = book['Match Wafer (WO Card)']
                    trend_pages = [
                        chart for chart in wafer_sheet._charts
                        if len(chart.series) == 2]
                    self.assertGreaterEqual(len(trend_pages), 1)
                    category_count = 0
                    for detail in trend_pages:
                        categories = detail.series[0].cat.strRef
                        self.assertEqual(categories.f,
                                         "'Match Wafer (WO Card)'!$C$3:$C$62")
                        page_values = [
                            point.v for point in categories.strCache.pt]
                        self.assertEqual(page_values, ['1', '2', '3'] * 20)
                        category_count += len(page_values)
                        self.assertEqual(detail.y_axis.crossBetween, 'between')
                    self.assertEqual(category_count, 60)

    def test_fullmap_matplotlib_trend_keeps_tight_ordinal_limits(self):
        from metrology_app.analysis_export import plot_figure
        plot = {"title": "DP", "x": "", "y": "DP", "labels": ["W1"] * 51,
                "series": [{"name": "DP", "line": True, "data": pd.DataFrame({"X": range(1, 52), "Y": range(51)})}]}
        figure = plot_figure(plot)
        self.assertEqual(figure.axes[0].get_xlim(), (.5, 51.5))
        self.assertAlmostEqual(figure.get_figwidth() * 2.54, 25, places=3)
        self.assertAlmostEqual(figure.get_figheight() * 2.54, 11, places=3)
        line = figure.axes[0].lines[0]
        self.assertEqual(line.get_linewidth(), 2.5)
        self.assertEqual(line.get_marker(), "o")
        self.assertEqual(line.get_markersize(), 6)
        figure.clear()

    def test_report_trend_keeps_die_sequence_and_once_per_span_identity_captions(self):
        from metrology_app.excel_export import parameter_figure, sequence_layout
        data = pd.DataFrame({'Raw': [1., 2., 3., 4., 5., 6.], 'Reference': [1., 2., 3., 4., 5., 6.],
                             'Die Seq': ['10', '20', '30', '10', '20', '30']})
        figure = parameter_figure('CD', data, None, 'Final', 'All', panel='Trend',
                                  sequence=sequence_layout(['W1'] * 3 + ['W2'] * 3))
        axis = figure.axes[0]
        self.assertEqual(axis.get_xlabel(), 'Die Seq')
        self.assertEqual([label.get_text() for label in axis.get_xticklabels()], data['Die Seq'].tolist())
        self.assertEqual([text.get_text() for text in axis.texts], ['W1', 'W2'])
        figure.canvas.draw()
        renderer = figure.canvas.get_renderer()
        for text in (*axis.get_xticklabels(), *axis.texts, axis.xaxis.label, axis.yaxis.label, axis.title):
            bounds = text.get_window_extent(renderer)
            self.assertGreaterEqual(bounds.x0, 0)
            self.assertGreaterEqual(bounds.y0, 0)
            self.assertLessEqual(bounds.x1, figure.bbox.width)
            self.assertLessEqual(bounds.y1, figure.bbox.height)
        self.assertEqual(axis.get_xlim(), (.5, 6.5))
        figure.clear()

    def test_expanded_axis_keeps_the_true_boundary_between_unequal_wafer_spans(self):
        import numpy as np
        from metrology_app.excel_export import sequence_layout
        layout = sequence_layout(['W1', 'W2', 'W2', 'W2'])
        # Equally wide captions each receive half the compact expanded axis,
        # even though the second Wafer contains three observations.
        self.assertAlmostEqual(float(np.interp(1.5, layout['source'], layout['display'])), 2.5)

    def test_group_export_uses_independent_group_and_wafer_width_rules(self):
        import numpy as np
        from openpyxl import Workbook
        from metrology_app.excel_export import (
            parameter_figure, parameter_footer, sequence_export_layout)
        data = pd.DataFrame({
            "Group": ["A", "B", "B", "B", "B"],
            "Group label": ["GROUP"] * 5,
            "Wafer": ["WAFER"] * 5,
            "Wafer key": ["W1", "W2", "W2", "W3", "W3"],
            "Show wafer": [False, True, True, True, True],
            "Raw": [1., 2., 3., 4., 5.],
            "Reference": [1., 2., 3., 4., 5.],
            "Die Seq": ["1", "1", "2", "1", "2"],
        })

        captions = parameter_footer(Workbook().active, 3, data,
                                    {"Group": 1, "Wafer": 2}, "group")
        layout = sequence_export_layout(
            data, mode="group", captions=captions)

        group_only = layout["group_only_widths"]
        mixed = layout["group_widths"]
        self.assertAlmostEqual(group_only["B"] / group_only["A"], 4, places=6)
        self.assertAlmostEqual(mixed["B"] / mixed["A"], 2, places=6)
        self.assertEqual(mixed["A"], group_only["A"])
        self.assertGreater(group_only["B"], mixed["B"])
        self.assertEqual(len(layout["wafer_widths"]["B"]), 2)
        self.assertAlmostEqual(
            sum(layout["wafer_widths"]["B"].values()), mixed["B"], places=6)
        groups = [item for item in captions if item["role"] == "group"]
        self.assertEqual(len(groups), 2)
        self.assertTrue(all(item["show"] for item in groups))
        figure = parameter_figure(
            "CD", data, None, "Final", "Group", panel="Trend",
            sequence=layout)
        try:
            positions = {text.get_text(): [] for text in figure.axes[0].texts}
            for text in figure.axes[0].texts:
                positions[text.get_text()].append(float(text.xy[0]))
            a_width = mixed["A"]
            b_width = mixed["B"]
            wafer_a, wafer_b = layout["wafer_widths"]["B"].values()
            self.assertTrue(np.allclose(
                sorted(positions["GROUP"]),
                [a_width / 2, a_width + b_width / 2]))
            self.assertTrue(np.allclose(
                sorted(positions["WAFER"]),
                [a_width + wafer_a / 2,
                 a_width + wafer_a + wafer_b / 2]))
        finally:
            figure.clear()
        hidden = data.assign(**{"Show wafer": False})
        hidden_captions = parameter_footer(
            Workbook().active, 3, hidden, {"Group": 1, "Wafer": 2}, "group")
        hidden_layout = sequence_export_layout(
            hidden, mode="group", captions=hidden_captions)
        self.assertEqual(hidden_layout["group_widths"],
                         hidden_layout["group_only_widths"])

    def test_group_x_axis_uses_single_line_captions_without_leader_lines(self):
        from xml.etree import ElementTree as ET
        from openpyxl import Workbook
        from metrology_app.excel_export import (
            parameter_figure, parameter_footer, sequence_export_layout)
        from metrology_app.native_chart_labels import _drawing

        counts = [20, 4, 1]
        labels = ["Old Unknown", "New MM1", "New MM2"]
        data = pd.DataFrame({
            "Group": [
                f"All:{index}" for index, count in enumerate(counts)
                for _ in range(count)],
            "Group label": [
                label for label, count in zip(labels, counts)
                for _ in range(count)],
            "Group caption": [
                label.replace(" ", "\n")
                for label, count in zip(labels, counts)
                for _ in range(count)],
            "Wafer": ["W1"] * sum(counts),
            "Wafer key": ["W1"] * sum(counts),
            "Show wafer": [False] * sum(counts),
            "Raw": list(range(1, sum(counts) + 1)),
            "Reference": list(range(2, sum(counts) + 2)),
            "Die Seq": [str(index) for index in range(sum(counts))],
        })
        captions = parameter_footer(
            Workbook().active, 3, data,
            {"Group": 1, "Wafer": 2}, "group")
        self.assertEqual(
            [item["text"] for item in captions
             if item["role"] == "group"],
            labels)
        layout = sequence_export_layout(
            data, mode="group", captions=captions)
        geometry = (2. / layout["width"], 1. - 2.7 / layout["width"])
        root = ET.fromstring(_drawing(
            captions, geometry, layout["width"] * 96 / 2.54))
        ns = {
            "d": "http://schemas.openxmlformats.org/drawingml/2006/chartDrawing",
            "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        }
        native = {}
        for anchor in root:
            shape = anchor.find("d:sp[@textlink]", ns)
            if shape is None:
                continue
            text = "".join(
                item.text or "" for item in anchor.findall(".//a:t", ns))
            native[text] = {
                "center": (
                    float(anchor.find("d:from/d:x", ns).text)
                    + float(anchor.find("d:to/d:x", ns).text)) / 2,
                "wrap": shape.find("d:txBody/a:bodyPr", ns).get("wrap"),
                "no_fill": shape.find("d:spPr/a:noFill", ns) is not None,
            }
        group_captions = [
            item for item in layout["captions"]
            if item["role"] == "group"]
        for item in group_captions:
            expected = geometry[0] + geometry[1] * item["center"]
            self.assertAlmostEqual(
                native[item["text"]]["center"], expected, places=6)
            self.assertEqual(native[item["text"]]["wrap"], "none")
            self.assertTrue(native[item["text"]]["no_fill"])

        figure = parameter_figure(
            "CD", data, None, "Final", "Group",
            panel="Trend", sequence=layout)
        try:
            texts = [text.get_text() for text in figure.axes[0].texts]
            self.assertEqual(texts.count(labels[0]), 1)
            self.assertEqual(texts.count(labels[1]), 1)
            self.assertEqual(texts.count(labels[2]), 1)
            self.assertNotIn("", texts, "Caption leaders must not be drawn")
            low, high = layout["limits"]
            for item in group_captions:
                text = next(
                    text for text in figure.axes[0].texts
                    if text.get_text() == item["text"])
                self.assertAlmostEqual(
                    float(text.xy[0]),
                    low + item["center"] * (high - low), places=6)
                self.assertEqual(
                    text.get_bbox_patch().get_facecolor()[3], 0.)
        finally:
            figure.clear()

    def test_show_wafer_captions_stay_centred_over_their_own_spans(self):
        from openpyxl import Workbook
        from metrology_app.excel_export import (
            parameter_footer, sequence_export_layout)
        from metrology_app.native_chart_labels import caption_boxes

        counts = [100, 80, 40, 26, 10]
        labels = ["Old MM1", "Old MM2", "Old Unknown", "New MM1", "New MM2"]
        rows = [
            {
                "Group": f"All:{group}",
                "Group label": label,
                "Wafer": (
                    f"WAFER-{group:02d}-{wafer:02d}\n"
                    f"LOT: LOT-{wafer:02d}\n"
                    "PAD: ARRAY-IDENTITY"),
                "Wafer key": (group, wafer),
                "Show wafer": group >= 3,
                "Raw": 1.,
                "Reference": 1.,
                "Die Seq": "1",
            }
            for group, (label, count) in enumerate(zip(labels, counts))
            for wafer in range(count)
        ]
        data = pd.DataFrame(rows)
        captions = parameter_footer(
            Workbook().active, 3, data,
            {"Group": 1, "Wafer": 2}, "group")
        layout = sequence_export_layout(
            data, mode="group", captions=captions)
        wafers = [
            item for item in layout["captions"]
            if item["role"] == "wafer"]
        left, right = 3. / layout["width"], .7 / layout["width"]
        boxes = caption_boxes(
            wafers, (left, 1. - left - right),
            width_px=layout["width"] * 96 / 2.54)

        for item, (center, _width) in zip(wafers, boxes):
            self.assertAlmostEqual(
                center,
                left + (1. - left - right) * item["center"],
                places=6)
        for (_left_center, left_width), (right_center, right_width) in zip(
                boxes, boxes[1:]):
            self.assertLessEqual(
                _left_center + left_width / 2,
                right_center - right_width / 2 + 1e-12)

    def test_match_group_splits_group_only_and_selective_show_wafer_sheets(self):
        from metrology_app.export_sheets import export_sheet_names
        from openpyxl.chart import LineChart, ScatterChart

        wafer_ids = ["OLD-WAFER"] * 12 + [
            "NEW-WAFER-LONG-IDENTITY-01"] * 2 + [
            "NEW-WAFER-LONG-IDENTITY-02"] * 2
        raw = pd.DataFrame({
            "Wafer ID": wafer_ids,
            "Lot ID": [f"LOT-{index:02}" for index in range(len(wafer_ids))],
            "PAD Name": ["ARRAY-IDENTITY"] * len(wafer_ids),
            "Die Seq": list(range(1, 13)) + [1, 2, 1, 2],
            "CD": [str(index + 1) for index in range(len(wafer_ids))],
        })
        self.window.set_reference_frame(pd.DataFrame({
            "CD Reference": [index + 2 for index in range(len(raw))]}))
        self.window.result_mode.setCurrentText("Final")
        self.window.set_raw_frame(raw.copy())
        self.window.result_mode.setCurrentText("Preview")
        self.window.set_raw_frame(raw)
        self.window.group_controls.restore(
            {
                "enabled": True,
                "head_names": {"0": "Old A", "1": "New B"},
                "show_wafer_groups": ["All:1"],
            },
            pd.DataFrame({"TestFlag": [0] * 12 + [1] * 4}))
        self.window.group_controls.apply_button.click()
        self.window.run_analysis()

        snapshot = self.window.excel_export_snapshot()
        planned = export_sheet_names(snapshot, matching=True)
        self.assertIn("Match Group (WO Card)", planned)
        self.assertIn("Match Group show Wafer(WO Card)", planned)
        self.assertIn("Match Group show Wafer (W Card)", planned)

        with tempfile.TemporaryDirectory() as folder:
            for native in (True, False):
                images = []
                path = self.window.export_excel(
                    Path(folder) / f"group-views-{native}.xlsx",
                    native=native, images=images)
                book = load_workbook(path)
                self.assertIn("Match Group show Wafer(WO Card)", book.sheetnames)
                self.assertIn("Match Group show Wafer (W Card)", book.sheetnames)
                for suffix, shown_name in (
                        ("WO Card", "Match Group show Wafer(WO Card)"),
                        ("W Card", "Match Group show Wafer (W Card)")):
                    group = book[f"Match Group ({suffix})"]
                    shown = book[shown_name]
                    group_panels = group._charts if native else group._images
                    shown_panels = shown._charts if native else shown._images
                    self.assertEqual(len(group_panels), 3)
                    self.assertEqual(len(shown_panels), 3)
                    if native:
                        self.assertIsInstance(group_panels[1], LineChart)
                        self.assertEqual(group_panels[1].y_axis.crossBetween, 'between')
                        for series in group_panels[1].series:
                            categories = series.cat.strRef
                            self.assertEqual(categories.f,
                                             f"'Match Group ({suffix})'!$C$3:$C$18")
                            self.assertEqual([point.v for point in categories.strCache.pt],
                                             [str(die) for die in raw['Die Seq']])
                            self.assertTrue(series.val.numRef.f.startswith(
                                f"'Match Group ({suffix})'!"))
                        self.assertIsInstance(shown_panels[1], ScatterChart)
                        for series in shown_panels[1].series:
                            self.assertTrue(
                                series.xVal.numRef.f.startswith(
                                    "'_Plot data'!"))
                            self.assertIsNotNone(series.yVal.numRef)
                        for chart in (group_panels[1], shown_panels[1]):
                            self.assertFalse(chart.visible_cells_only)
                            self.assertIsNone(chart.x_axis.title)
                            self.assertIsNone(
                                chart.x_axis.tickLblPos)
                    if native:
                        from xml.etree import ElementTree as ET
                        from zipfile import ZipFile
                        ns = {
                            "d": "http://schemas.openxmlformats.org/"
                                 "drawingml/2006/chartDrawing",
                            "a": "http://schemas.openxmlformats.org/"
                                 "drawingml/2006/main",
                        }
                        caption_text = {}
                        with ZipFile(path) as archive:
                            for name in archive.namelist():
                                if not name.startswith(
                                        "xl/drawings/identity-"):
                                    continue
                                root = ET.fromstring(archive.read(name))
                                for shape in root.findall(
                                        ".//d:sp[@textlink]", ns):
                                    source = shape.get("textlink", "")
                                    for title, sheet_name in (
                                            ("Match Group",
                                             f"Match Group ({suffix})"),
                                            ("Match Group show Wafer",
                                             shown_name),
                                            ("Match Old A",
                                             f"Match Old A ({suffix})"),
                                            ("Match New B",
                                             f"Match New B ({suffix})")):
                                        if source.startswith(
                                                f"'{sheet_name}'!"):
                                            caption_text.setdefault(
                                                title, []).append(
                                                "".join(
                                                    node.text or ""
                                                    for node in shape.findall(
                                                        ".//a:t", ns)))
                        self.assertTrue(any(
                            "OLD-WAFER" in text
                            for text in caption_text["Match Old A"]))
                        self.assertTrue(any(
                            "NEW-WAFER-LONG-IDENTITY-01" in text
                            for text in caption_text["Match New B"]))
                        self.assertFalse(any(
                            "OLD-WAFER" in text
                            for text in caption_text["Match Group"]))
                        self.assertFalse(any(
                            "OLD-WAFER" in text
                            for text in caption_text[
                                "Match Group show Wafer"]))
                        self.assertTrue(any(
                            "NEW-WAFER-LONG-IDENTITY-01" in text
                            for text in caption_text[
                                "Match Group show Wafer"]))
                    self.assertLess(
                        group_panels[1].anchor.ext.cx,
                        shown_panels[1].anchor.ext.cx,
                        "The group-only Trend must not reserve Show Wafer label width")

    def test_wafer_export_keeps_every_visible_label_and_has_no_width_cap(self):
        from openpyxl import Workbook
        from metrology_app.excel_export import parameter_footer, sequence_export_layout
        rows = []
        for wafer in range(1, 7):
            for die in (1, 2):
                rows.append({
                    "Group": "All",
                    "Group label": "All",
                    "Wafer": f"WAFER-{wafer:02}\nLOT: LONG-LOT-{wafer:02}\nPAD: LONG-PAD-{wafer:02}",
                    "Wafer key": (f"WAFER-{wafer:02}", f"LOT-{wafer:02}", "PAD"),
                    "Show wafer": True,
                    "Raw": float(wafer * 10 + die),
                    "Reference": float(wafer * 10 + die + 1),
                    "Die Seq": str(die),
                })
        data = pd.DataFrame(rows)
        captions = parameter_footer(Workbook().active, 3, data,
                                    {"Group": 1, "Wafer": 2}, "wafer")
        layout = sequence_export_layout(data, mode="wafer", captions=captions)

        self.assertEqual(len(captions), 6)
        self.assertTrue(all(item["show"] for item in captions))
        self.assertEqual(len(layout["captions"]), 6)
        self.assertGreater(layout["width"], 25,
                           "Visible full labels take precedence over the old 25 cm floor")
        self.assertEqual(len(layout["x"]), len(data))

    def test_report_axes_keep_decimal_ticks_and_signed_bias_inside_fixed_size(self):
        from metrology_app.excel_export import parameter_figure, sequence_layout
        data = pd.DataFrame({'Raw': [138.43, 139.56, 140.12],
                             'Reference': [138.5, 139.7, 140.2], 'Die Seq': ['1', '2', '3']})
        for panel in ('Match', 'Trend', 'Bias'):
            with self.subTest(panel=panel):
                figure = parameter_figure('CutDeponFin_Reference', data, None, 'Final', 'All',
                    panel=panel, reference_label='NOVA', unit='nm',
                    sequence=None if panel == 'Match' else sequence_layout(['W1'] * 3))
                figure.canvas.draw()
                bounds = figure.axes[0].get_tightbbox(figure.canvas.get_renderer())
                self.assertGreaterEqual(bounds.x0, 0)
                self.assertGreaterEqual(bounds.y0, 0)
                self.assertLessEqual(bounds.x1, figure.bbox.width)
                self.assertLessEqual(bounds.y1, figure.bbox.height)
                self.assertAlmostEqual(figure.get_figheight() * 2.54, 11)
                figure.clear()

    def test_native_trend_uses_editable_local_ranges_square_excel_style_and_merged_wafer(self):
        from zipfile import ZipFile
        from xml.etree import ElementTree as ET
        reference, raw = self.frames()
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.run_analysis()
        with tempfile.TemporaryDirectory() as folder:
            path = self.window.export_excel(Path(folder) / "editable.xlsx")
            sheet = load_workbook(path)["Match Original (WO Card)"]
            trend = sheet._charts[1]
            category = trend.series[0].cat.strRef
            self.assertIsNotNone(category, "Native categories must reference the visible identity columns")
            self.assertEqual(category.f, "'Match Original (WO Card)'!$B$3:$B$5")
            self.assertEqual(trend.series[0].val.numRef.f, "'Match Original (WO Card)'!$D$3:$D$5")
            self.assertEqual(trend.series[1].val.numRef.f, "'Match Original (WO Card)'!$E$3:$E$5")
            self.assertEqual(trend.series[1].graphicalProperties.line.solidFill.srgbClr, "ED7D31")
            self.assertIn("A3:A5", {str(area) for area in sheet.merged_cells.ranges})
            self.assertEqual([sheet.cell(row, 1).value for row in range(3, 6)], ["W1", None, None])
            self.assertEqual([fixtures.source_cell(sheet, 'Wafer ID', row).value for row in range(2, 5)], ["W1"] * 3)
            with ZipFile(path) as archive:
                chart = ET.fromstring(archive.read("xl/charts/chart2.xml"))
                ns = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}
                self.assertEqual(chart.find("c:roundedCorners", ns).get("val"), "0")

    def test_native_group_captions_are_merged_and_match_series_share_the_visible_sheet(self):
        reference, raw = self.frames()
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.group_controls.restore({'enabled': True, 'head_names': {'0': 'Head A', '1': 'Head B'}},
                                           pd.DataFrame({'TestFlag': [0, 0, 1]}))
        self.window.group_controls.apply_button.click()
        with tempfile.TemporaryDirectory() as folder:
            sheet = self.export(folder)['Match Original (WO Card)']
            self.assertIn('A3:A4', {str(area) for area in sheet.merged_cells.ranges})
            self.assertEqual(sheet._charts[1].x_axis.tickLblSkip, 1)
            for series in sheet._charts[0].series:
                self.assertTrue(series.xVal.numRef.f.startswith("'Match Original (WO Card)'!"))
                self.assertTrue(series.yVal.numRef.f.startswith("'Match Original (WO Card)'!"))

    def test_grouped_exports_reference_original_rows_instead_of_copying_reordered_values(self):
        raw = pd.DataFrame({"Wafer ID": ["W1", "W2", "W1", "W2"], "Die Seq": ["01", "01", "02", "02"],
                            "CD": ["1.000", "8.000", "2.000", "9.000"]})
        self.window.set_reference_frame(pd.DataFrame({"CD Reference": [3, 17, 5, 19]}))
        self.window.set_raw_frame(raw)
        self.window.group_controls.restore({"enabled": True, "trend_order": "original",
            "head_names": {"0": "Head A", "1": "Head B"}}, pd.DataFrame({"TestFlag": [0, 1, 0, 1]}))
        self.window.group_controls.apply_button.click()
        before = self.window.workspace_snapshot()
        with tempfile.TemporaryDirectory() as folder:
            for native in (True, False):
                book = load_workbook(self.window.export_excel(Path(folder) / f"original-{native}.xlsx", native=native))
                original = book["Match Original (WO Card)"]
                self.assertEqual([fixtures.source_cell(original, 'CD', row).value for row in range(2, 6)], ["1.000", "8.000", "2.000", "9.000"])
                source_letter = fixtures.source_cell(original, 'CD', 2).column_letter
                sheet = book["Match Group (WO Card)"]
                header = next(cell.row for row in sheet for cell in row if cell.value == "PMISH+Card")
                self.assertEqual([sheet.cell(row, 1).value for row in range(header + 1, header + 5)], ["Head A", None, "Head B", None])
                values = [sheet.cell(row, 4).value for row in range(header + 1, header + 5)]
                for formula, source_row in zip(values, (2, 4, 3, 5)):
                    self.assertIn(f"'Match Original (WO Card)'!${source_letter}${source_row}", formula)
                group = book["Match Head A (WO Card)"]
                self.assertIn(f"'Match Original (WO Card)'!${source_letter}$4", group["D4"].value)
        after = self.window.workspace_snapshot()
        self.assertEqual(before.states, after.states)
        for name in before.frames:
            pd.testing.assert_frame_equal(before.frames[name], after.frames[name])

    def test_merged_wafer_captions_keep_distinct_hidden_identities_and_isolated_styles(self):
        raw = pd.DataFrame({'Wafer ID': ['W1'] * 6, 'Lot ID': ['L1'] * 2 + ['L2'] * 2 + ['L1'] * 2,
                            'PAD Name': ['A'] * 4 + ['B'] * 2, 'Die Seq': ['01', '02'] * 3,
                            'CD': ['1.000', '2.000', '3.000', '4.000', '5.000', '6.000']})
        self.window.set_reference_frame(pd.DataFrame({'CD Reference': [3, 5, 7, 9, 11, 13]}))
        self.window.set_raw_frame(raw)
        self.window.group_controls.restore({'enabled': True, 'head_names': {'0': 'Head A', '1': 'Head B'}},
                                           pd.DataFrame({'TestFlag': [0] * 4 + [1] * 2}))
        self.window.group_controls.apply_button.click()
        self.window.set_plot_labels({'trend': {'lot': False, 'pad': False}})
        with tempfile.TemporaryDirectory() as folder:
            for native in (True, False):
                with self.subTest(native=native):
                    path = self.window.export_excel(Path(folder) / f'captions-{native}.xlsx', native=native)
                    book = load_workbook(path)
                    sheet = book['Match Original (WO Card)']
                    self.assertEqual({str(area) for area in sheet.merged_cells.ranges},
                                     {'A1:H1', 'A3:A6', 'A7:A8', 'B3:B4', 'B5:B6', 'B7:B8'})
                    self.assertEqual([sheet.cell(row, 2).value for row in range(3, 9)],
                                     ['W1', None, 'W1', None, 'W1', None])
                    for row in (3, 5, 7):
                        caption = sheet.cell(row, 2)
                        self.assertEqual(caption.alignment.horizontal, 'center')
                        self.assertTrue(caption.alignment.wrap_text)
                        self.assertTrue(caption.protection.locked)
                        self.assertEqual(caption.font.name, 'Times New Roman')
                    source_letter = fixtures.source_cell(sheet, 'CD', 2).column_letter
                    for row in range(3, 9):
                        numeric = sheet.cell(row, 4)
                        self.assertIsNone(numeric.alignment.horizontal)
                        self.assertIsNone(numeric.alignment.wrap_text)
                        self.assertTrue(numeric.protection.locked)
                        self.assertIn(f"'Match Original (WO Card)'!${source_letter}${row - 1}", numeric.value)
                    self.assertEqual([sheet.cell(row, 1).value for row in range(3, 9)],
                                     ['Head A', None, None, None, 'Head B', None])
                    self.assertEqual([fixtures.source_cell(sheet, 'CD', row).value for row in range(2, 8)],
                                     raw['CD'].tolist())
                    # The exported merge remains an ordinary editable Excel merge.
                    sheet.unmerge_cells('B3:B4')
                    sheet['B4'] = 'Edited caption'
                    edited = Path(folder) / f'edited-{native}.xlsx'
                    book.save(edited)
                    self.assertEqual(load_workbook(edited)['Match Original (WO Card)']['B4'].value, 'Edited caption')

    def test_wafer_sheet_references_original_in_first_appearance_order_in_both_modes(self):
        raw = pd.DataFrame({"Wafer ID": ["W2", "W1", "W2", "W1"], "Die Seq": ["01", "01", "02", "02"],
                            "CD": ["1.000", "8.000", "2.000", "9.000"]})
        self.window.set_reference_frame(pd.DataFrame({"CD Reference": [3, 17, 5, 19]}))
        self.window.set_raw_frame(raw)
        self.window.group_controls.restore({"enabled": True, "trend_order": "original",
            "head_names": {"0": "Head A", "1": "Head B"}}, pd.DataFrame({"TestFlag": [0, 1, 1, 0]}))
        self.window.group_controls.apply_button.click()
        before = self.window.workspace_snapshot()
        widths = []
        with tempfile.TemporaryDirectory() as folder:
            for native in (True, False):
                book = load_workbook(self.window.export_excel(Path(folder) / f"wafer-{native}.xlsx", native=native))
                original = book["Match Original (WO Card)"]
                original_panels = original._charts if native else original._images
                self.assertGreaterEqual(len(original_panels), 1)
                self.assertEqual([fixtures.source_cell(original, 'CD', row).value for row in range(2, 6)], ["1.000", "8.000", "2.000", "9.000"])
                self.assertFalse(any(c.value == 'CD Reference (NOVA)' for c in original[1]))
                self.assertEqual([original.cell(row, 6).value for row in range(3, 7)], [3, 17, 5, 19])
                raw_letter = fixtures.source_cell(original, 'CD', 2).column_letter
                ref_letter = original.cell(2, 6).column_letter
                wafer = book["Match Wafer (WO Card)"]
                self.assertEqual([wafer.cell(row, 3).value for row in range(3, 7)], ["01", "02", "01", "02"])
                self.assertEqual([wafer.cell(row, 2).value for row in range(3, 7)], ["W2", None, "W1", None])
                for row, source_row in zip(range(3, 7), (2, 4, 3, 5)):
                    self.assertIn(f"'Match Original (WO Card)'!${raw_letter}${source_row}", wafer.cell(row, 4).value)
                    self.assertIn(f"'Match Original (WO Card)'!${ref_letter}${source_row + 1}", wafer.cell(row, 6).value)
                panels = wafer._charts if native else wafer._images
                self.assertEqual(len(panels), 3, "Match, Wafer Trend and Wafer Bias, without a Group overview")
                panel_cells = [
                    fixtures.drawing_cell(panel, wafer)
                    for panel in panels]
                self.assertEqual(panel_cells[0][1], 4)
                self.assertEqual(panel_cells[1][1], 4)
                self.assertGreater(panel_cells[2][1], panel_cells[1][1])
                widths.append(panels[1].anchor.ext.cx / 360000)
                self.assertGreater(widths[-1], 0)
                self.assertLess(widths[-1], 25, "Small wafer sheets must stay tight")
                if native:
                    categories = panels[1].series[0].cat.strRef
                    self.assertEqual(categories.f,
                                     "'Match Wafer (WO Card)'!$C$3:$C$6")
                    self.assertEqual([point.v for point in categories.strCache.pt],
                                     ['01', '02', '01', '02'])
        self.assertAlmostEqual(widths[0], widths[1], places=4)
        after = self.window.workspace_snapshot()
        self.assertEqual(before.states, after.states)
        for name in before.frames:
            pd.testing.assert_frame_equal(before.frames[name], after.frames[name])

    def test_group_and_wafer_trend_widths_match_between_export_renderers(self):
        raw = pd.DataFrame({
            "Wafer ID": ["W1", "W2", "W2", "W3", "W3"],
            "Die Seq": [1, 1, 2, 1, 2],
            "CD": ["1.000", "2.000", "3.000", "4.000", "5.000"],
        })
        self.window.set_reference_frame(
            pd.DataFrame({"CD Reference": [2., 3., 4., 5., 6.]}))
        self.window.set_raw_frame(raw)
        self.window.group_controls.restore(
            {"enabled": True, "mark_enabled": False,
             "head_names": {"0": "A", "1": "B"},
             "show_wafer_groups": ["All:1"]},
            pd.DataFrame({"TestFlag": [0, 1, 1, 1, 1]}))
        self.window.group_controls.apply_button.click()
        widths = {}
        with tempfile.TemporaryDirectory() as folder:
            for native in (True, False):
                book = load_workbook(
                    self.window.export_excel(
                        Path(folder) / f"widths-{native}.xlsx", native=native))
                for prefix in ("Match Group", "Match Wafer"):
                    sheet = book[f"{prefix} (WO Card)"]
                    panels = sheet._charts if native else sheet._images
                    self.assertEqual(panels[1].anchor.ext.cx, panels[2].anchor.ext.cx)
                    widths[(prefix, native)] = panels[1].anchor.ext.cx
        for prefix in ("Match Group", "Match Wafer"):
            self.assertEqual(widths[(prefix, True)], widths[(prefix, False)])
        self.assertNotEqual(widths[("Match Group", True)],
                            widths[("Match Wafer", True)])

    def test_fullmap_trend_uses_own_data_and_only_mapped_parameters(self):
        self.window.match_type.setCurrentText('TEM')
        reference, raw = self.frames()
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        full = raw.assign(CD=["11.000", "21.000", "31.000"], Other=[101, 102, 103])
        self.window.set_preview_frame(full)
        self.window.run_analysis()
        expected = self.window.workbook.stage_frame("preview")["CD"].astype(float).tolist()
        with tempfile.TemporaryDirectory() as folder:
            for native in (True, False):
                book = load_workbook(self.window.export_excel(Path(folder) / f"full-{native}.xlsx", native=native))
                sheet = book["FullMap (WO Card)"]
                self.assertEqual([fixtures.source_cell(sheet, 'CD', row).value for row in range(2, 5)], expected)
                objects = sheet._charts if native else sheet._images
                self.assertEqual(len(objects), 1)
                self.assertEqual(objects[0].anchor._from.row, 4)
                self.assertEqual(objects[0].anchor._from.col, 0)
                if native:
                    series = objects[0].series[0]
                    source = series.val.numRef.f
                    self.assertIn("'FullMap (WO Card)'", source)
                    self.assertEqual(series.marker.symbol, "circle")
                    self.assertEqual(series.marker.size, 6)
                    self.assertEqual(series.graphicalProperties.line.w, 31750)
                    letter = fixtures.source_cell(sheet, 'CD', 2).column_letter
                    formulas = [cell.value for row in sheet for cell in row
                                if cell.data_type == "f" and f'IF({letter}2=""' in cell.value]
                    self.assertEqual(len(formulas), 1)
                    self.assertIn(f"{letter}2*1", formulas[0])

    def test_fullmap_reuses_only_mapped_drawn_panels_without_changing_child(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        import time
        reference, raw = self.frames()
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        full = pd.DataFrame({"Wafer ID": ["OWN"] * 4, "Die Seq": [1, 2, 3, 4],
            "FIELD X": [-1, 1, 0, 0], "FIELD Y": [0, 0, -1, 1],
            "CD": [11, 21, 31, 41], "Other": [101, 102, 103, 104]})
        self.window.set_preview_frame(full)
        self.window.run_analysis()
        child = self.window.open_stage_workspace("preview")
        for index in range(child.parameter_list.topLevelItemCount()):
            item = child.parameter_list.topLevelItem(index)
            if item.text(0) in {"CD", "Other"}:
                item.setCheckState(0, Qt.CheckState.Checked)
        child.plot_page.selector.selectAll()
        child.plot_page.draw_maps()
        deadline = time.monotonic() + 30
        while child.plot_page.background_render_pending and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertIsNone(child.plot_page.worker)
        self.assertEqual(len(child.plot_page.artists), 2)
        child.radius_page.selector.selectAll()
        child.radius_page.draw_plot()
        self.assertTrue(child.radius_page.ready)
        before = child.workspace_snapshot()
        result = child.plot_page.result
        expected_pngs = [child.plot_page.png_bytes(), child.radius_page.png_bytes()]
        with tempfile.TemporaryDirectory() as folder:
            books = []
            for native in (True, False):
                book = load_workbook(self.window.export_excel(Path(folder) / f"drawn-{native}.xlsx", native=native))
                books.append(book)
                sheet = book["FullMap (WO Card)"]
                # NOVA retains software Map/Radius; Trends belong to the Match views.
                self.assertEqual((len(sheet._charts), len(sheet._images)), (0, 2))
                self.assertEqual(sheet['A1'].value, 'Wafer')
                self.assertTrue(all(obj.anchor._from.row == 4 for obj in [*sheet._charts, *sheet._images]))
            for index in (0, 1):
                self.assertEqual(books[0]["FullMap (WO Card)"]._images[index]._data(), expected_pngs[index])
                self.assertEqual(books[1]["FullMap (WO Card)"]._images[index]._data(), expected_pngs[index])
        self.assertIs(child.plot_page.result, result)
        after = child.workspace_snapshot()
        self.assertEqual(before.states, after.states)
        for name in before.frames:
            pd.testing.assert_frame_equal(before.frames[name], after.frames[name])
