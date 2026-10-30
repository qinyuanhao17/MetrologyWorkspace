"""Native Excel charts through the public export seam."""
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from openpyxl import load_workbook
from openpyxl.chart import LineChart, ScatterChart
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from metrology_app.matching_window import MatchingWindow
from metrology_app.dynamic_window import DynamicWindow
from metrology_app.correlation_window import CorrelationWindow
from metrology_app.window import MainWindow
from metrology_app.matching import ParameterMapping
from unittest.mock import patch
from PIL import Image as PillowImage


APP = QApplication.instance() or QApplication([])


def source_column(sheet, name):
    """The template places literal inputs to the right of parameter tables."""
    cells = reversed(sheet[1])
    return next(cell.column for cell in cells if cell.value == name)


def source_cell(sheet, name, row):
    return sheet.cell(row, source_column(sheet, name))


def drawing_xy_px(drawing, sheet):
    anchor = drawing.anchor
    if getattr(anchor, 'pos', None) is not None:
        return anchor.pos.x / 9525, anchor.pos.y / 9525
    from openpyxl.utils import get_column_letter
    x = sum(
        ((sheet.column_dimensions[get_column_letter(column)].width or 13) * 7 + 5)
        for column in range(1, anchor._from.col + 1)
    ) + anchor._from.colOff / 9525
    y = sum(
        (sheet.row_dimensions[row].height or 15.)
        for row in range(1, anchor._from.row + 1)
    ) * 96 / 72 + anchor._from.rowOff / 9525
    return x, y


def drawing_cell(drawing, sheet):
    from openpyxl.utils import get_column_letter
    x, y = drawing_xy_px(drawing, sheet)
    column, cursor = 0, 0.
    while True:
        width = (sheet.column_dimensions[get_column_letter(column + 1)].width or 13) * 7 + 5
        if cursor + width > x:
            break
        cursor += width
        column += 1
    row, cursor = 0, 0.
    while True:
        height = (sheet.row_dimensions[row + 1].height or 15.) * 96 / 72
        if cursor + height > y:
            break
        cursor += height
        row += 1
    return column, row


class ExcelExportTests(unittest.TestCase):
    def test_partial_reference_export_keeps_raw_rows_and_missing_pair_gaps(self):
        reference = pd.DataFrame({"CD Reference": ["3.000", "", "7.000"]})
        raw = pd.DataFrame({"Wafer ID": ["W1"] * 4, "Die Seq": ["001", "003", "005", "007"],
                            "CD": ["1.000", "2.000", "3.000", "4.000"]})
        self.window.match_type.setCurrentText("NOVA")
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        result = self.window.run_analysis()
        self.assertEqual(result.card("CD").valid_pairs, 2)
        with tempfile.TemporaryDirectory() as folder:
            book = self.export(folder)
            try:
                original = book["Match Original (WO Card)"]
                columns = {cell.value: cell.column for cell in original[1] if cell.value is not None}
                self.assertEqual([original.cell(row, columns["CD"]).value for row in range(2, 6)],
                                 ["1.000", "2.000", "3.000", "4.000"])
                self.assertNotIn('CD Reference (NOVA)', columns)
                self.assertEqual([original.cell(row, 5).value for row in range(3, 7)],
                                 [3., None, 7., None])
                self.assertEqual(book["_Plot data"].cell(2, 1).value, "3.000")
            finally:
                book.close()

    def setUp(self):
        chooser = patch('metrology_app.export_job.choose_export_sheets', side_effect=lambda owner, names: names)
        chooser.start()
        self.addCleanup(chooser.stop)
        self.window = MatchingWindow()

    def tearDown(self):
        self.window.document.force_close = True
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def frames(self):
        reference = pd.DataFrame({"CD Reference": [3.0, 5.0, 7.0]})
        raw = pd.DataFrame({"Wafer ID": ["W1"] * 3, "Die Seq": [1, 2, 3],
                            "CD": ["1.000", "2.000", "3.000"]})
        return reference, raw

    def export(self, folder, name="export.xlsx"):
        path = Path(folder) / name
        self.window.export_excel(path)
        return load_workbook(path)

    def test_export_writes_native_match_charts_bound_to_cells(self):
        reference, raw = self.frames()
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.run_analysis()
        with tempfile.TemporaryDirectory() as folder:
            book = self.export(folder)
            self.assertEqual(book.sheetnames,
                             ["_Plot data", "Match Original (WO Card)", "Match Wafer (WO Card)", "RSQ (WO Card)"])
            self.assertEqual(book["_Plot data"].sheet_state, "hidden")
            # Source strings stay text in the data sheets.
            self.assertEqual(source_cell(book["Match Original (WO Card)"], "CD", 2).value, "1.000")
            match = book["Match Original (WO Card)"]
            charts = match._charts
            self.assertEqual([type(chart) for chart in charts],
                             [ScatterChart, LineChart, LineChart])
            cells = [drawing_cell(chart, match) for chart in charts]
            self.assertEqual(cells[0][0], 0)
            self.assertEqual(cells[0][1], cells[1][1])
            self.assertLess(cells[0][0], cells[1][0])
            self.assertEqual(cells[1][0], cells[2][0])
            self.assertLess(cells[1][1], cells[2][1])
            self.assertNotEqual(charts[0].x_axis.numFmt.formatCode, "General")
            points = charts[0].series[0]
            self.assertEqual(points.xVal.numRef.f, "'Match Original (WO Card)'!$C$3:$C$5")
            self.assertEqual(points.yVal.numRef.f, "'Match Original (WO Card)'!$E$3:$E$5")
            self.assertEqual(len(charts[0].series), 1)
            self.assertEqual(points.trendline.trendlineType, 'linear')
            self.assertTrue(points.trendline.dispEq)
            self.assertTrue(points.trendline.dispRSqr)
            self.assertFalse(any(c.value == 'Fit line' for row in match for c in row))
            self.assertEqual(charts[1].series[0].val.numRef.f, "'Match Original (WO Card)'!$D$3:$D$5")
            self.assertEqual(charts[1].series[1].val.numRef.f, "'Match Original (WO Card)'!$E$3:$E$5")
            self.assertEqual(charts[2].series[0].val.numRef.f, "'Match Original (WO Card)'!$F$3:$F$5")
            # Card values retain the software coefficients, independently of
            # the native Match trendline which Excel refits from its cells.
            helper = book["_Plot data"]
            self.assertEqual(helper["K10"].value, 2.0)
            self.assertEqual(helper["K11"].value, 1.0)
            self.assertEqual(helper["K12"].value, 1.0)
            self.assertEqual(match["D3"].value, "=IF(ISNUMBER(C3),'_Plot data'!$K$10*C3+'_Plot data'!$K$11,NA())")
            self.assertEqual(match["F3"].value, '=IF(AND(ISNUMBER(D3),ISNUMBER(E3)),D3-E3,NA())')
            self.assertIn("y = 2x + 1", helper["K20"].value)
            for chart in charts:
                self.assertFalse(chart.title.overlay)
                self.assertFalse(chart.varyColors)
                self.assertEqual(chart.x_axis.axPos, "b")
                self.assertFalse(chart.x_axis.delete)
                self.assertFalse(chart.y_axis.delete)
                self.assertEqual(chart.x_axis.txPr.bodyPr.rot, 0)
                self.assertTrue(all(series.smooth is False for series in chart.series))
                for axis in (chart.x_axis, chart.y_axis):
                    if axis.title is not None:
                        self.assertIs(axis.title.overlay, False)
            category_range = charts[1].series[0].cat.strRef.f
            self.assertEqual(category_range, "'Match Original (WO Card)'!$B$3:$B$5")
            self.assertEqual(charts[2].series[0].cat.strRef.f, category_range)
            self.assertTrue(all(chart.visible_cells_only is False for chart in charts))
            from zipfile import ZipFile
            from xml.etree import ElementTree as ET
            with ZipFile(Path(folder) / "export.xlsx") as archive:
                xml = ET.fromstring(archive.read("xl/charts/chart2.xml"))
                body = xml.find(".//{http://schemas.openxmlformats.org/drawingml/2006/chart}catAx/"
                                "{http://schemas.openxmlformats.org/drawingml/2006/chart}txPr/"
                                "{http://schemas.openxmlformats.org/drawingml/2006/main}bodyPr")
                self.assertEqual(body.get("wrap"), "none")

    def test_export_writes_one_match_sheet_per_group(self):
        reference, raw = self.frames()
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.group_controls.restore(
            {"enabled": True, "head_names": {"0": "Head A", "1": "Head B"}},
            pd.DataFrame({"TestFlag": [0, 0, 1]}),
        )
        self.window.group_controls.apply_button.click()
        self.assertTrue(self.window.result.group_plan.enabled)
        with tempfile.TemporaryDirectory() as folder:
            book = self.export(folder)
            self.assertEqual(book.sheetnames,
                             ["_Plot data", "Match Original (WO Card)", "Match Group (WO Card)",
                              "Match Wafer (WO Card)", "Match Head A (WO Card)",
                              "Match Head B (WO Card)", "RSQ (WO Card)"])
            for title, rows in (("Match Head A", 2), ("Match Head B", 1)):
                sheet = book[title + " (WO Card)"]
                self.assertTrue(sheet._charts, f"{title} needs its own charts")
                self.assertEqual(sheet["A2"].value, "Group")
                filled = [sheet.cell(row=row, column=1).value
                          for row in range(3, 3 + rows)]
                self.assertEqual(filled, [title.removeprefix("Match ")] + [None] * (rows - 1))
                self.assertIsNone(sheet.cell(row=3 + rows, column=1).value)
            trend = book["Match Group (WO Card)"]
            self.assertEqual(trend['A3'].value, 'Head A')
            self.assertEqual(trend['A5'].value, 'Head B')
            for series in trend._charts[1].series:
                categories = series.cat.strRef
                self.assertEqual(categories.f, "'Match Group (WO Card)'!$C$3:$C$5")
                self.assertEqual([point.v for point in categories.strCache.pt], ['1', '2', '3'])
                self.assertTrue(
                    series.val.numRef.f.startswith(
                        "'Match Group (WO Card)'!"))
            rsq = book["RSQ (WO Card)"]
            self.assertEqual(rsq["D1"].value, "CD R²")
            self.assertEqual(rsq["A2"].value, 1)
            self.assertEqual(rsq["B2"].value, "W1")
            self.assertEqual(rsq["D2"].value, 1)
            r_squared_range = rsq._charts[0].series[0].val.numRef.f
            self.assertTrue(r_squared_range.startswith("'RSQ (WO Card)'!$D$"), r_squared_range)

    def test_both_stages_have_card_suffixes_and_english_times_font(self):
        reference, raw = self.frames()
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.result_mode.setCurrentText("Final")
        self.window.set_raw_frame(raw.assign(CD=["3.000", "5.000", "7.000"]))
        self.window.result_mode.setCurrentText("Preview")
        self.window.run_analysis()
        before = self.window.workspace_snapshot()
        with tempfile.TemporaryDirectory() as folder:
            book = self.export(folder)
            self.assertIn("Match Original (WO Card)", book.sheetnames)
            self.assertIn("Match Original (W Card)", book.sheetnames)
            self.assertEqual(source_cell(book["Match Original (W Card)"], "CD", 2).value, "3.000")
            for sheet in book:
                for row in sheet:
                    for cell in row:
                        if cell.value is not None:
                            self.assertEqual(cell.font.name, "Times New Roman")
            self.assertEqual(book["Match Original (WO Card)"]["A2"].value, "Wafer")
        after = self.window.workspace_snapshot()
        self.assertEqual(before.states, after.states)
        for name in before.frames:
            pd.testing.assert_frame_equal(before.frames[name], after.frames[name])

    def test_matplotlib_export_keeps_excel_data_and_embeds_real_pngs(self):
        reference, raw = self.frames()
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.run_analysis()
        with tempfile.TemporaryDirectory() as folder:
            native = self.export(folder)
            target = Path(folder) / "plots.xlsx"
            path = self.window.export_matplotlib(target)
            self.assertEqual(path, target)
            pictures = load_workbook(path)
            self.assertFalse(any(sheet._charts for sheet in pictures))
            self.assertTrue(pictures["Match Original (WO Card)"]._images)
            image = pictures["Match Original (WO Card)"]._images[0]
            self.assertEqual(
                drawing_cell(image, pictures["Match Original (WO Card)"])[0], 0)
            for title in native.sheetnames:
                self.assertEqual(list(native[title].values), list(pictures[title].values))
            self.assertEqual(list(Path(folder).rglob("*.png")), [])
            from io import BytesIO
            with PillowImage.open(BytesIO(pictures["Match Original (WO Card)"]._images[0]._data())) as picture:
                self.assertIn("Matplotlib", picture.info.get("Software", ""))

    def test_large_matplotlib_report_keeps_all_panels_and_matches_serial_pixels(self):
        from io import BytesIO
        from metrology_app.excel_export import parameter_figure, report_sequence_layout
        self.window.match_type.setCurrentText('NOVA')
        count = 3000
        raw = pd.DataFrame({'Wafer ID': ['W1'] * count, 'Die Seq': range(1, count + 1),
                            'CD': [f'{value}.000' for value in range(1, count + 1)]})
        reference = pd.DataFrame({'CD Reference': [2 * value + 1 for value in range(1, count + 1)]})
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.run_analysis()
        before = self.window.workspace_snapshot()
        data = pd.DataFrame({'Raw': range(1, count + 1), 'Reference': reference['CD Reference'],
                             'Die Seq': [str(value) for value in range(1, count + 1)]})
        expected = []
        for panel in ('Match', 'Trend', 'Bias'):
            figure = parameter_figure('CD', data, self.window.result.card('CD'), 'Preview', 'All',
                panel=panel, reference_label='NOVA', unit='nm',
                sequence=None if panel == 'Match' else {**report_sequence_layout(data['Die Seq'].tolist(), name='Die'),
                    'ticks': [], 'mode': 'die'})
            buffer = BytesIO()
            figure.savefig(buffer, format='png', dpi=150, facecolor='white')
            figure.clear()
            expected.append(buffer.getvalue())
        with tempfile.TemporaryDirectory() as folder:
            book = load_workbook(self.window.export_excel(Path(folder) / 'large.xlsx', native=False))
            self.assertEqual(sum(len(sheet._images) for sheet in book), 7)
            original = book['Match Original (WO Card)']
            cell = source_cell(original, 'CD', 3001)
            self.assertEqual(cell.value, '3000.000')
            source = f"'Match Original (WO Card)'!${cell.column_letter}$3001"
            self.assertEqual(book['Match Wafer (WO Card)']['C3002'].value,
                             f'=IF({source}="",NA(),IFERROR({source}*1,NA()))')
            for panel, image, contents in zip(('Match', 'Trend', 'Bias'),
                                             book['Match Original (WO Card)']._images, expected, strict=True):
                with self.subTest(panel=panel), \
                        PillowImage.open(BytesIO(image._data())) as actual, \
                        PillowImage.open(BytesIO(contents)) as serial:
                    self.assertEqual(actual.size, serial.size)
                    self.assertEqual(actual.convert('RGBA').tobytes(), serial.convert('RGBA').tobytes())
        after = self.window.workspace_snapshot()
        self.assertEqual(before.states, after.states)
        for name in before.frames:
            pd.testing.assert_frame_equal(before.frames[name], after.frames[name])

    def test_matplotlib_menu_exports_one_workbook_without_png_sidecars(self):
        from PyQt6.QtWidgets import QFileDialog
        from PyQt6.QtTest import QTest
        import time
        reference, raw = self.frames()
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.run_analysis()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "plots.xlsx"
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")):
                self.window.images_action.trigger()
            deadline = time.monotonic() + 30
            while not self.window.images_action.isEnabled() and time.monotonic() < deadline:
                QTest.qWait(10)
            self.assertTrue(target.is_file())
            self.assertEqual({p.name for p in Path(folder).iterdir()}, {"plots.xlsx"})
            self.assertTrue(load_workbook(target)["Match Original (WO Card)"]._images)

    def test_native_charts_match_the_report_palette_labels_and_ranges(self):
        reference, raw = self.frames()
        self.window.match_type.setCurrentText("NOVA")
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.run_analysis()
        with tempfile.TemporaryDirectory() as folder:
            book = self.export(folder)
            match, trend, bias = book["Match Original (WO Card)"]._charts
            self.assertEqual(trend.series[0].graphicalProperties.line.solidFill.srgbClr, "5B9BD5")
            self.assertEqual(trend.series[1].graphicalProperties.line.solidFill.srgbClr, "ED7D31")
            self.assertEqual(trend.series[1].tx.strRef.f, "'Match Original (WO Card)'!E2")
            self.assertLess(trend.y_axis.scaling.min, 2.)
            self.assertGreater(trend.y_axis.scaling.max, 8.)
            self.assertEqual(trend.y_axis.majorUnit, 1.)
            self.assertAlmostEqual(match.x_axis.scaling.min, .95)
            self.assertAlmostEqual(match.x_axis.scaling.max, 3.05)
            self.assertIsNone(match.legend)

    def test_dynamic_exports_own_cycle_values_and_software_three_sigma(self):
        window = DynamicWindow()
        try:
            window.set_table(pd.DataFrame({"Wafer ID": ["OWN"] * 6,
                "Die Seq": [1, 2, 1, 2, 1, 2], "DP": ["1.000", "2.000", "3.000", "4.000", "5.000", "6.000"]}), "Independent")
            for index in range(window.parameter_list.topLevelItemCount()):
                item = window.parameter_list.topLevelItem(index)
                if item.text(0) == "DP":
                    item.setCheckState(0, Qt.CheckState.Checked)
            APP.processEvents()

            with tempfile.TemporaryDirectory() as folder:
                path = window.export_excel(Path(folder) / "dynamic.xlsx")
                book = load_workbook(path)
                self.assertEqual(book["Dynamic"]["D2"].value, "1.000")
                self.assertIn("Dynamic", book.sheetnames)
                self.assertTrue(book["Dynamic"]._charts)
                from metrology_app.analysis_export import capture_window
                self.assertEqual(capture_window(window)['frames']['Pivot DP'].iloc[-1, 1], 6.)
                formulas = [cell.value for row in book['Dynamic'] for cell in row if cell.data_type == 'f']
                self.assertTrue(any('3*STDEV(' in formula for formula in formulas))
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_correlation_and_trend_export_independent_sources_and_draw_choices(self):
        window = CorrelationWindow()
        try:
            raw = pd.DataFrame({"Wafer ID": ["OWN"] * 4, "Die Seq": [1, 2, 3, 4],
                                "DP": ["1.000", "2.000", "3.000", "4.000"],
                                "EW": ["2.000", "4.000", "6.000", "8.000"]})
            reference = pd.DataFrame({"DP Ref": [10, 20, 30, 40], "EW Ref": [20, 40, 60, 80]})
            window.set_sources(reference, raw, (ParameterMapping("Alias", "DP Ref", "DP"),), "Preview")
            for tree in (window.parameter_list, window.reference_parameter_list):
                for index in range(tree.topLevelItemCount()):
                    item = tree.topLevelItem(index)
                    if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                        item.setCheckState(0, Qt.CheckState.Checked)
            for page in (window.correlation_page, window.sequence_page):
                page.selector.selectAll()
                page.draw_plot()
                self.assertTrue(page.ready)
            before = window.workspace_snapshot()
            with tempfile.TemporaryDirectory() as folder:
                native = load_workbook(window.export_excel(Path(folder) / "own.xlsx"))
                self.assertTrue(native["Correlation"]._charts)
                self.assertTrue(native["Trend"]._charts)
                trend_series = [series for chart in native["Trend"]._charts
                                for series in chart.series]
                self.assertTrue(trend_series)
                self.assertTrue(all(series.marker.symbol == "circle"
                                    for series in trend_series))
                self.assertTrue(all(series.marker.size == 6 for series in trend_series))
                self.assertTrue(all(series.graphicalProperties.line.w == 31750
                                    for series in trend_series))
                self.assertEqual(native["Raw Data"]["C2"].value, "1.000")
                self.assertEqual(native["Ref Data"]["C1"].value, "DP Ref")
                table = [cell.value for row in native["Trend"] for cell in row]
                self.assertIn("Source row", table)
                self.assertNotIn("Alias", table)
                pictures = load_workbook(window.export_matplotlib(Path(folder) / "pictures"))
                self.assertFalse(any(sheet._charts for sheet in pictures))
                self.assertTrue(pictures["Trend"]._images)
            after = window.workspace_snapshot()
            self.assertEqual(before.states, after.states)
            for name in before.frames:
                pd.testing.assert_frame_equal(before.frames[name], after.frames[name])
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_radius_export_reuses_the_existing_png_in_both_modes(self):
        window = MainWindow()
        try:
            window.set_table(pd.DataFrame({"Wafer ID": ["OWN"] * 3, "Die Seq": [1, 2, 3],
                "FIELD X": [-1, 0, 1], "FIELD Y": [0, 1, 0], "DP": ["1.000", "2.000", "3.000"]}), "Independent")
            for index in range(window.parameter_list.topLevelItemCount()):
                item = window.parameter_list.topLevelItem(index)
                if item.text(0) == "DP":
                    item.setCheckState(0, Qt.CheckState.Checked)
            window.radius_page.selector.selectAll()
            window.radius_page.draw_plot()
            self.assertTrue(window.radius_page.ready)
            with tempfile.TemporaryDirectory() as folder:
                native = load_workbook(window.export_excel(Path(folder) / "radius.xlsx"))
                pictures = load_workbook(window.export_matplotlib(Path(folder) / "pictures"))
                self.assertFalse(native["Radius"]._charts)
                self.assertEqual(native["Radius"]._images[0]._data(), pictures["Radius"]._images[0]._data())
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_export_failure_preserves_existing_file_and_cleans_partial_output(self):
        reference, raw = self.frames()
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.run_analysis()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "existing.xlsx"
            self.window.export_excel(path)
            before = path.read_bytes()
            with patch("openpyxl.workbook.workbook.Workbook.save", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    self.window.export_excel(path)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(folder).glob(".export-*")), [])

    def test_missing_values_stay_blank_and_source_text_is_not_a_formula(self):
        reference, raw = self.frames()
        raw.loc[0, "CD"] = ""
        raw["Note"] = ["=not a formula", "00123", "literal"]
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.run_analysis()
        with tempfile.TemporaryDirectory() as folder:
            book = self.export(folder)
            self.assertEqual(source_cell(book["Match Original (WO Card)"], 'Note', 2).data_type, "s")
            self.assertEqual(source_cell(book["Match Original (WO Card)"], 'Note', 2).value, "=not a formula")
            match = book["Match Original (WO Card)"]
            cell = source_cell(match, 'CD', 2)
            self.assertIsNone(cell.value)
            source = f"'Match Original (WO Card)'!${cell.column_letter}$2"
            self.assertEqual(match["C3"].value, f'=IF({source}="",NA(),IFERROR({source}*1,NA()))')
            self.assertEqual(match["D3"].value, "=IF(ISNUMBER(C3),'_Plot data'!$K$10*C3+'_Plot data'!$K$11,NA())")
            self.assertEqual(match._charts[1].display_blanks, "gap")

    def test_native_trendline_uses_the_measurement_series_with_missing_reference_gaps(self):
        reference, raw = self.frames()
        reference.loc[2, "CD Reference"] = float("nan")
        raw.loc[2, "CD"] = "999.000"
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.run_analysis()
        with tempfile.TemporaryDirectory() as folder:
            match = self.export(folder)["Match Original (WO Card)"]
            points = match._charts[0].series[0]
            self.assertIsNotNone(points.trendline)
            self.assertEqual(points.xVal.numRef.f, "'Match Original (WO Card)'!$C$3:$C$5")
            self.assertEqual(points.yVal.numRef.f, "'Match Original (WO Card)'!$E$3:$E$5")
            self.assertIsNone(match['E5'].value)
            self.assertIsNone(match.parent['_Plot data']['C7'].value)

    def test_native_trend_keeps_different_secondary_units_in_separate_charts(self):
        window = CorrelationWindow()
        try:
            window.set_table(pd.DataFrame({"Wafer ID": ["OWN"] * 4, "Die Seq": [1, 2, 3, 4],
                "P [nm]": [1, 2, 3, 4], "Q [um]": [.1, .2, .3, .4], "R [nm]": [5, 6, 7, 8]}), "Independent")
            for index in range(window.parameter_list.topLevelItemCount()):
                item = window.parameter_list.topLevelItem(index)
                if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                    item.setCheckState(0, Qt.CheckState.Checked)
            page = window.sequence_page
            window.set_trend_axis_mode("dual")
            page.selector.selectAll()
            page.draw_plot()
            page.set_overlay("P [nm]", "Q [um]")
            page.set_overlay("P [nm]", "R [nm]")
            with tempfile.TemporaryDirectory() as folder:
                book = load_workbook(window.export_excel(Path(folder) / "units.xlsx"))
                charts = book["Trend"]._charts
                self.assertEqual(len(charts), 4)  # The two standalone panels remain, as in the software.
                for chart in charts[:2]:
                    self.assertEqual(len(chart._charts), 2)
                    self.assertEqual(len(chart._charts[1].series), 1)
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_wafer_map_export_reuses_the_current_png_without_interpolation(self):
        from PyQt6.QtTest import QTest
        import time
        window = MainWindow()
        try:
            window.set_table(pd.DataFrame({"Wafer ID": ["OWN"] * 4, "Die Seq": [1, 2, 3, 4],
                "FIELD X": [-1, 1, 0, 0], "FIELD Y": [0, 0, -1, 1], "DP": ["1.000", "2.000", "3.000", "4.000"]}), "Independent")
            for index in range(window.parameter_list.topLevelItemCount()):
                item = window.parameter_list.topLevelItem(index)
                if item.text(0) == "DP":
                    item.setCheckState(0, Qt.CheckState.Checked)
            page = window.plot_page
            page.selector.selectAll()
            page.draw_maps()
            deadline = time.monotonic() + 30
            while page.background_render_pending and time.monotonic() < deadline:
                QTest.qWait(10)
            self.assertIsNone(page.worker)
            self.assertTrue(page.artists)
            before = page.result
            with tempfile.TemporaryDirectory() as folder:
                native = load_workbook(window.export_excel(Path(folder) / "maps.xlsx"))
                pictures = load_workbook(window.export_matplotlib(Path(folder) / "pictures"))
                self.assertEqual(native["Wafer Map"]._images[0]._data(), pictures["Wafer Map"]._images[0]._data())
                self.assertIs(page.result, before)
                self.assertIsNone(page.worker)
        finally:
            window.document.force_close = True
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_excel_menu_exports_in_background_and_reports_completion(self):
        from PyQt6.QtWidgets import QFileDialog
        from PyQt6.QtTest import QTest
        import time
        reference, raw = self.frames()
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.run_analysis()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "background.xlsx"
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")):
                self.window.export_action.trigger()
            self.assertFalse(self.window.export_action.isEnabled())
            deadline = time.monotonic() + 30
            while not self.window.export_action.isEnabled() and time.monotonic() < deadline:
                QTest.qWait(10)
            self.assertTrue(self.window.export_action.isEnabled())
            self.assertIn("Match Original (WO Card)", load_workbook(target).sheetnames)

    def test_large_menu_export_keeps_the_gui_ticking_and_all_sources_unchanged(self):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QFileDialog
        from PyQt6.QtTest import QTest
        import time
        count = 3000
        raw = pd.DataFrame({'Wafer ID': ['W1'] * count, 'Die Seq': range(1, count + 1),
                            **{f'P{i}': [f'{value+i}.000' for value in range(count)] for i in range(4)}})
        reference = pd.DataFrame({f'P{i} Reference': [2 * (value+i) + 1 for value in range(count)] for i in range(4)})
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.run_analysis()
        before = self.window.workspace_snapshot()
        ticks = []
        heartbeat = QTimer()
        heartbeat.timeout.connect(lambda: ticks.append(time.monotonic()))
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'responsive.xlsx'
            heartbeat.start(10)
            try:
                with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(target), '')):
                    self.window.images_action.trigger()
                deadline = time.monotonic() + 45
                while not self.window.images_action.isEnabled() and time.monotonic() < deadline:
                    QTest.qWait(10)
                self.assertTrue(self.window.images_action.isEnabled())
                self.assertEqual(self.window.statusBar().currentMessage(), 'Exported responsive.xlsx')
                self.assertGreater(len(ticks), 10)
                self.assertLess(max(right-left for left, right in zip(ticks, ticks[1:])), .5)
                self.assertEqual(sum(len(sheet._images) for sheet in load_workbook(target)), 28)
            finally:
                heartbeat.stop()
        after = self.window.workspace_snapshot()
        self.assertEqual(before.states, after.states)
        for name in before.frames:
            pd.testing.assert_frame_equal(before.frames[name], after.frames[name])

    def test_large_export_publish_failure_preserves_previous_file_and_cleans_private_output(self):
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        from PyQt6.QtTest import QTest
        import time
        count = 5000
        raw = pd.DataFrame({'Wafer ID': ['W1'] * count, 'Die Seq': range(count),
                            'CD': range(count), 'Depth': range(count)})
        reference = pd.DataFrame({'CD Reference': range(count), 'Depth Reference': range(count)})
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.run_analysis()
        with tempfile.TemporaryDirectory() as folder:
            target = self.window.export_excel(Path(folder) / 'previous.xlsx')
            previous = target.read_bytes()
            with patch('os.replace', side_effect=OSError('Cannot publish this report')), \
                    patch.object(QFileDialog, 'getSaveFileName', return_value=(str(target), '')), \
                    patch.object(QMessageBox, 'warning', return_value=QMessageBox.StandardButton.Ok) as warning:
                self.window.export_action.trigger()
                deadline = time.monotonic() + 45
                while not self.window.export_action.isEnabled() and time.monotonic() < deadline:
                    QTest.qWait(10)
                self.assertTrue(self.window.export_action.isEnabled())
                self.assertIn('Cannot publish this report', warning.call_args.args[2])
            self.assertEqual(target.read_bytes(), previous)
            self.assertEqual(list(Path(folder).glob('.export-*')), [])

    def test_cancel_during_excel_write_preserves_the_previous_export(self):
        from threading import Event
        from PyQt6.QtWidgets import QFileDialog, QProgressDialog, QPushButton
        from PyQt6.QtTest import QTest
        from openpyxl import Workbook
        import time
        reference, raw = self.frames()
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.run_analysis()
        entered, release = Event(), Event()
        original_save = Workbook.save
        def delayed_save(book, path):
            entered.set()
            if not release.wait(10):
                raise OSError("test write did not resume")
            original_save(book, path)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "existing.xlsx"
            self.window.export_excel(target)
            before = target.read_bytes()
            with patch.object(Workbook, "save", delayed_save), patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")):
                try:
                    self.window.export_action.trigger()
                    deadline = time.monotonic() + 10
                    while not entered.is_set() and time.monotonic() < deadline:
                        QTest.qWait(10)
                    self.assertTrue(entered.is_set())
                    progress = self.window.findChild(QProgressDialog)
                    next(button for button in progress.findChildren(QPushButton) if button.text() == "Cancel").click()
                finally:
                    release.set()
                while not self.window.export_action.isEnabled() and time.monotonic() < deadline:
                    QTest.qWait(10)
            self.assertTrue(self.window.export_action.isEnabled())
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(list(Path(folder).glob(".export-*")), [])

    def test_cancel_at_parameter_progress_stops_both_renderers_before_publishing(self):
        from threading import Event
        from metrology_app.excel_export import write_workbook
        reference, raw = self.frames()
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.run_analysis()
        snapshot = self.window.excel_export_snapshot()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'previous.xlsx'
            self.window.export_excel(target)
            previous = target.read_bytes()
            for native in (True, False):
                with self.subTest(native=native):
                    stopped, messages = Event(), []
                    def progress(message):
                        messages.append(message)
                        if 'CD' in message:
                            stopped.set()
                    with self.assertRaises(InterruptedError):
                        write_workbook(target, **snapshot, native=native,
                                       progress=progress, cancelled=stopped.is_set)
                    self.assertTrue(any('CD' in message for message in messages))
                    self.assertEqual(target.read_bytes(), previous)
                    self.assertEqual(list(Path(folder).glob('.export-*')), [])

    def test_cancel_during_large_sheet_serialization_keeps_previous_report(self):
        from threading import Event
        from metrology_app.excel_export import write_workbook
        count = 2500
        self.window.set_reference_frame(pd.DataFrame({'CD Reference': range(count)}))
        self.window.set_raw_frame(pd.DataFrame({'Wafer ID': ['W1'] * count,
            'Die Seq': range(count), 'CD': [f'{value}.000' for value in range(count)]}))
        self.window.run_analysis()
        snapshot = self.window.excel_export_snapshot()
        with tempfile.TemporaryDirectory() as folder:
            target = self.window.export_excel(Path(folder) / 'previous.xlsx')
            previous = target.read_bytes()
            for native in (True, False):
                with self.subTest(native=native):
                    stopped, messages = Event(), []
                    def progress(message):
                        messages.append(message)
                        if message.startswith('Writing worksheet Match Original'):
                            stopped.set()
                    with self.assertRaises(InterruptedError):
                        write_workbook(target, **snapshot, native=native,
                            progress=progress, cancelled=stopped.is_set)
                    self.assertTrue(any(message.startswith('Writing worksheet Match Original') for message in messages))
                    self.assertEqual(target.read_bytes(), previous)
                    self.assertEqual(list(Path(folder).glob('.export-*')), [])

    def test_large_export_preserves_literal_xml_text_precision_and_typed_values(self):
        from datetime import datetime
        from metrology_app.excel_export import write_workbook
        count = 2500
        notes = [' \r\nA<&>\"\' Ω中文\t ', '=SUM(A1:A2)', '0000000000000000123.4500']
        self.window.set_reference_frame(pd.DataFrame({'CD Reference': range(count)}))
        raw = pd.DataFrame({'Wafer ID': ['W1'] * count, 'Die Seq': range(count),
            'CD': [f'{value}.000' for value in range(count)],
            'Note': [notes[index % len(notes)] for index in range(count)]})
        self.window.set_raw_frame(raw)
        self.window.run_analysis()
        snapshot = self.window.excel_export_snapshot()
        typed = pd.DataFrame({'Date': [datetime(2026, 10, 16, 3, 4, 5)],
            'Value': [1.234567890123456], 'Enabled': [True], 'Blank': [None]})
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'literal.xlsx'
            write_workbook(target, **{**snapshot, 'extra_frames': [('Typed', typed)]})
            book = load_workbook(target)
            sheet = book['Match Original (WO Card)']
            for index, text in enumerate(notes, 2):
                self.assertEqual(source_cell(sheet, 'Note', index).value, text)
                self.assertEqual(source_cell(sheet, 'Note', index).data_type, 's')
            self.assertEqual(source_cell(sheet, 'CD', 2501).value, '2499.000')
            self.assertEqual(book['Typed']['A2'].value, datetime(2026, 10, 16, 3, 4, 5))
            self.assertEqual(book['Typed']['B2'].value, 1.234567890123456)
            self.assertIs(book['Typed']['C2'].value, True)
            self.assertIsNone(book['Typed']['D2'].value)

    def test_invalid_xml_text_in_large_export_never_replaces_previous_report(self):
        from metrology_app.excel_export import write_workbook
        count = 2500
        self.window.set_reference_frame(pd.DataFrame({'CD Reference': range(count)}))
        self.window.set_raw_frame(pd.DataFrame({'Wafer ID': ['W1'] * count,
            'Die Seq': range(count), 'CD': range(count)}))
        self.window.run_analysis()
        snapshot = self.window.excel_export_snapshot()
        with tempfile.TemporaryDirectory() as folder:
            target = self.window.export_excel(Path(folder) / 'previous.xlsx')
            previous = target.read_bytes()
            for invalid in ('\uffff', '\ud800'):
                with self.subTest(invalid=repr(invalid)), self.assertRaises(ValueError):
                    write_workbook(target, **{**snapshot,
                        'extra_frames': [('Invalid', pd.DataFrame({'Note': [invalid]}))]})
                self.assertEqual(target.read_bytes(), previous)
                self.assertEqual(list(Path(folder).glob('.export-*')), [])

    def test_failed_export_cleans_partial_file_and_keeps_previous_workbook(self):
        from openpyxl import Workbook
        reference, raw = self.frames()
        self.window.set_reference_frame(reference)
        self.window.set_raw_frame(raw)
        self.window.run_analysis()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'previous.xlsx'
            self.window.export_excel(target)
            previous = target.read_bytes()
            def failed_save(_book, temporary):
                Path(temporary).write_bytes(b'partial XLSX')
                raise OSError('Disk write failed')
            with patch.object(Workbook, 'save', failed_save):
                with self.assertRaisesRegex(OSError, 'Disk write failed'):
                    self.window.export_excel(target)
            self.assertEqual(target.read_bytes(), previous)
            self.assertEqual(list(Path(folder).glob('.export-*')), [])


if __name__ == "__main__":
    unittest.main()
