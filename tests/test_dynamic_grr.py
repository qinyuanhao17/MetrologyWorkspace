"""GRR inputs, template formulas and the Dynamic-to-Match report workflow."""

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from openpyxl import Workbook, load_workbook
import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog, QLabel

from metrology_app import dynamic_grr as grr
from metrology_app.dynamic_page import GRR_COLOURS
from metrology_app.matching_window import MatchingWindow
from metrology_app.settings import get_settings


APP = QApplication.instance() or QApplication([])


def template_at(path):
    book = Workbook()
    book.active.title = "Instructions"
    sheet = book.create_sheet("GRR Report")
    sheet.merge_cells("M96:R98")
    sheet["M96"] = '=IF(D12=101,"Excellent","Review")'
    sheet["Q26"] = "Keep"
    book.save(path)
    return path


def recalculate_fixture(path, _source, sheet_name, batches):
    book = load_workbook(path)
    master = book[sheet_name]
    sheets = [master, *(book.copy_worksheet(master) for _ in batches[1:])]
    results = []
    for sheet, batch in zip(sheets, batches, strict=True):
        sheet.title = batch["name"]
        for row, column, value in batch["cells"]:
            sheet.cell(row, column, value)
        results.append("Excellent" if sheet["D12"].value == 101 else "Review")
    book.save(path)
    book.close()
    return results


class GrrInputTests(unittest.TestCase):
    def test_first_nine_cycles_and_thirteen_dies_fill_three_input_blocks(self):
        values = [[cycle * 100 + die for die in range(1, 15)] for cycle in range(1, 11)]
        pivot = pd.DataFrame(values, index=range(1, 11), columns=range(1, 15))
        pivot.loc["3 Sigma"] = 9999
        matrix = grr.input_values(pivot)

        self.assertEqual((len(matrix), len(matrix[0])), (9, 13))
        with TemporaryDirectory() as directory:
            template = template_at(Path(directory) / "template.xlsx")

            with patch.object(grr, "_excel_recalculate", side_effect=recalculate_fixture):
                report = grr.evaluate(grr.request([("CD", matrix)], template))

            workbook = load_workbook(BytesIO(report.content))
            sheet = workbook["CD_GRR"]
            self.assertEqual(report.results, (("CD", "Excellent"),))
            for address, expected in {
                "D12": 101, "P14": 313, "D18": 401, "P20": 613, "D24": 701, "P26": 913,
                "Q26": "Keep", "M96": '=IF(D12=101,"Excellent","Review")',
            }.items():
                self.assertEqual(sheet[address].value, expected)
            self.assertIsNone(sheet["D15"].value)
            self.assertIsNone(sheet["D21"].value)
            workbook.close()
            source = load_workbook(template)
            self.assertIsNone(source["GRR Report"]["D12"].value)
            source.close()

    def test_missing_measurement_is_not_filled_from_a_later_cycle_or_die(self):
        pivot = pd.DataFrame(1.0, index=range(1, 11), columns=range(1, 15))
        pivot.loc["3 Sigma"] = 0
        pivot.iat[1, 3] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite"):
            grr.input_values(pivot)
        with self.assertRaisesRegex(ValueError, "9 cycles and 13 dies"):
            grr.input_values(pivot.iloc[:, :12])

    def test_template_must_identify_a_single_grr_sheet(self):
        with TemporaryDirectory() as directory:
            original = Path(directory) / "not-grr.xlsx"
            Workbook().save(original)
            with self.assertRaisesRegex(ValueError, "M96:R98"):
                grr.install_template(original, Path(directory) / "stored.xlsx")



class DynamicGrrWorkflowTests(unittest.TestCase):
    def wait_for_results(self, page, expected):
        for _ in range(200):
            labels = {
                label.property("parameter"): label
                for label in page.findChildren(QLabel, "dynamicGrrResult")
            }
            current = {name: label.text() for name, label in labels.items()}
            if current == expected:
                return labels
            QTest.qWait(15)
        self.fail(f"Expected {expected}, got {current}")

    def test_load_grr_updates_each_plot_and_saves_each_parameter_beside_mwkb(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            master = template_at(root / "import.xlsx")
            stored = root / "config" / "grr_template.xlsx"
            with (
                patch.object(grr, "template_path", return_value=stored),
                patch.object(grr, "_excel_recalculate", side_effect=recalculate_fixture),
            ):
                workbook = MatchingWindow()
                reopened = None
                try:
                    dynamic = workbook.open_dynamic_workspace("preview")
                    frame = pd.DataFrame([
                        {"Wafer ID": "W1", "Die Seq": die, "CD": cycle * 100 + die, "EW": cycle * 100 + die + 900}
                        for cycle in range(1, 11) for die in range(1, 15)
                    ])
                    dynamic.set_table(frame, "Dynamic")
                    for index in range(dynamic.parameter_list.topLevelItemCount()):
                        item = dynamic.parameter_list.topLevelItem(index)
                        if item.text(0) in ("CD", "EW"):
                            item.setCheckState(0, Qt.CheckState.Checked)
                    dynamic.tabs.setCurrentWidget(dynamic.dynamic_page)
                    page = dynamic.dynamic_page
                    self.assertEqual(page.load_grr_button.text(), "Load GRR")
                    with patch.object(QFileDialog, "getOpenFileName", return_value=(str(master), "")):
                        page.load_grr_button.click()
                    self.assertEqual(stored.read_bytes(), master.read_bytes())
                    labels = self.wait_for_results(page, {"CD": "GRR: Excellent", "EW": "GRR: Review"})
                    theme = "dark" if get_settings().get("theme") == "dark" else "light"
                    self.assertIn(GRR_COLOURS[theme][0], labels["CD"].styleSheet())
                    self.assertIn(GRR_COLOURS[theme][1], labels["EW"].styleSheet())
                    self.assertTrue(labels["CD"].isVisible())

                    cd_column = dynamic.model.document_frame().columns.get_loc("CD")
                    dynamic.model.edit({(1, cd_column): "105"})
                    self.wait_for_results(page, {"CD": "GRR: Review", "EW": "GRR: Review"})
                    dynamic.model.edit({(1, cd_column): "101"})
                    path = workbook.save_workbook(root / "project.mwkb")
                    sidecar = path.with_name("GRR_project.xlsx")
                    report = load_workbook(sidecar)
                    try:
                        self.assertEqual([name for name in report.sheetnames if name.endswith("_GRR")],
                                         ["CD_GRR", "EW_GRR"])
                        self.assertEqual(report["CD_GRR"]["D12"].value, 101)
                        self.assertEqual(report["EW_GRR"]["P26"].value, 1813)
                        self.assertEqual(report["EW_GRR"]["M96"].data_type, "f")
                    finally:
                        report.close()

                    workbook.document.force_close = True
                    workbook.close()
                    reopened = MatchingWindow()
                    reopened.load_workbook(path)
                    self.assertEqual(reopened.save_workbook(root / "copy.mwkb"), root / "copy.mwkb")
                    self.assertTrue((root / "GRR_copy.xlsx").is_file())
                    self.assertFalse(list(root.glob("GRR_*.bak")))
                    with patch.object(QFileDialog, "getOpenFileName") as choose:
                        restored = reopened.open_dynamic_workspace("preview")
                        restored.tabs.setCurrentWidget(restored.dynamic_page)
                        self.wait_for_results(restored.dynamic_page, {"CD": "GRR: Excellent", "EW": "GRR: Review"})
                    choose.assert_not_called()
                finally:
                    for owner in (workbook, reopened):
                        if owner is not None:
                            owner.document.force_close = True
                            owner.close()
                            owner.deleteLater()
                    APP.processEvents()
