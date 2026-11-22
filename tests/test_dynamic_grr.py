"""GRR inputs, template formulas and the Dynamic-to-Match report workflow."""

from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from openpyxl import Workbook, load_workbook
import pandas as pd
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog, QLabel, QMessageBox

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

    def test_master_import_prefers_the_application_root_and_reads_an_older_cache(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config = root / "config"
            config.mkdir()
            legacy = template_at(config / "grr_template.xlsx")
            legacy_bytes = legacy.read_bytes()
            source = template_at(root / "import.xlsx")
            with (
                patch.object(grr.settings, "APPLICATION_ROOT", root),
                patch.object(grr.settings, "APP_DIRECTORY", config),
                patch.object(grr.settings, "SETTINGS_PATH", config / "settings.yaml"),
            ):
                target = root / "grr_template.xlsx"
                self.assertEqual(grr.cached_template_path(), legacy)
                grr.install_template(source)
                self.assertEqual(grr.cached_template_path(), target)
                self.assertEqual(target.read_bytes(), source.read_bytes())
                self.assertEqual(legacy.read_bytes(), legacy_bytes)

    def test_template_must_identify_a_single_grr_sheet(self):
        with TemporaryDirectory() as directory:
            original = Path(directory) / "not-grr.xlsx"
            Workbook().save(original)
            with self.assertRaisesRegex(ValueError, "M96:R98"):
                grr.install_template(original, Path(directory) / "stored.xlsx")



class DynamicGrrWorkflowTests(unittest.TestCase):
    def test_new_workbook_uses_the_installed_master_even_before_opening_the_dynamic_tab(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            master = template_at(root / "grr_template.xlsx")
            master_bytes = master.read_bytes()
            with (
                patch.object(grr, "template_path", return_value=master),
                patch.object(grr, "_excel_recalculate", side_effect=recalculate_fixture),
                patch.object(QFileDialog, "getOpenFileName") as choose,
            ):
                workbook = MatchingWindow()
                try:
                    dynamic = workbook.open_dynamic_workspace("preview")
                    dynamic.set_table(pd.DataFrame([
                        {"Wafer ID": "W1", "Die Seq": die, "CD": cycle * 100 + die}
                        for cycle in range(1, 10) for die in range(1, 14)
                    ]), "New measurements")
                    for index in range(dynamic.parameter_list.topLevelItemCount()):
                        item = dynamic.parameter_list.topLevelItem(index)
                        if item.text(0) == "CD":
                            item.setCheckState(0, Qt.CheckState.Checked)
                    self.assertIsNot(dynamic.tabs.currentWidget(), dynamic.dynamic_page)
                    self.assertTrue(dynamic.dynamic_page.grr_report_controls.isHidden())
                    path = workbook.save_workbook(root / "fresh.mwkb")
                    report_path = path.with_name("GRR_fresh.xlsx")
                    self.assertTrue(report_path.is_file())
                    self.assertEqual(dynamic.dynamic_page.grr_report_path.text(), str(report_path))
                    dynamic.tabs.setCurrentWidget(dynamic.dynamic_page)
                    self.assertTrue(dynamic.dynamic_page.grr_report_controls.isVisible())
                    self.assertEqual(dynamic.dynamic_page.load_grr_button.text(), "Load GRR")
                    self.assertEqual(dynamic.dynamic_page.grr_status.text(), "Using saved GRR template.")
                    self.assertEqual(master.read_bytes(), master_bytes)
                    choose.assert_not_called()
                finally:
                    workbook.document.force_close = True
                    workbook.close()
                    workbook.deleteLater()
                    APP.processEvents()

    def test_excel_lock_warns_after_saving_mwkb_and_report_can_be_retried(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            master = template_at(root / "grr_template.xlsx")
            path = root / "locked-report.mwkb"
            report_path = root / "GRR_locked-report.xlsx"
            with (
                patch.object(grr, "template_path", return_value=master),
                patch.object(grr, "_excel_recalculate", side_effect=recalculate_fixture),
            ):
                workbook = MatchingWindow()
                try:
                    dynamic = workbook.open_dynamic_workspace("preview")
                    dynamic.set_table(pd.DataFrame([
                        {"Wafer ID": "W1", "Die Seq": die, "CD": cycle * 100 + die}
                        for cycle in range(1, 10) for die in range(1, 14)
                    ]), "Dynamic")
                    for index in range(dynamic.parameter_list.topLevelItemCount()):
                        item = dynamic.parameter_list.topLevelItem(index)
                        if item.text(0) == "CD":
                            item.setCheckState(0, Qt.CheckState.Checked)
                    workbook.save_workbook(path)
                    original_report = report_path.read_bytes()
                    page = dynamic.dynamic_page
                    dynamic.tabs.setCurrentWidget(page)
                    column = dynamic.model.document_frame().columns.get_loc("CD")
                    dynamic.model.edit({(1, column): "105"})
                    self.wait_for_results(page, {"CD": "GRR: Review"})
                    temporary_path = Path(page.grr_report_path.text())
                    self.assertTrue(temporary_path.is_file())
                    self.assertNotEqual(temporary_path, report_path)
                    replace = os.replace

                    def locked_replace(source, target):
                        if target == report_path:
                            raise PermissionError("The process cannot access the file because it is being used.")
                        return replace(source, target)

                    with (
                        patch.object(grr.os, "replace", side_effect=locked_replace),
                        patch.object(QMessageBox, "warning") as warning,
                    ):
                        self.assertEqual(workbook.save_workbook(path), path)
                    warning.assert_called_once()
                    self.assertIn(str(report_path), warning.call_args.args[2])
                    self.assertIn("Excel", warning.call_args.args[2])
                    self.assertIn("was saved", warning.call_args.args[2])
                    self.assertEqual(report_path.read_bytes(), original_report)
                    self.assertEqual(page.grr_report_path.text(), str(temporary_path))
                    self.assertTrue(page.grr_report_controls.isVisible())
                    self.assertFalse(workbook.isWindowModified())

                    workbook.save_workbook(path)
                    with report_path.open("rb") as stream:
                        book = load_workbook(stream)
                        try:
                            self.assertEqual(book["CD_GRR"]["D12"].value, 105)
                        finally:
                            book.close()
                    self.assertEqual(dynamic.dynamic_page.grr_report_path.text(), str(report_path))
                finally:
                    workbook.document.force_close = True
                    workbook.close()
                    workbook.deleteLater()
                    APP.processEvents()

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
                    first_preview = Path(page.grr_report_path.text())
                    self.assertTrue(first_preview.is_file())
                    self.assertNotEqual(first_preview.parent, root)
                    with patch.object(QDesktopServices, "openUrl", return_value=True) as open_url:
                        page.open_grr_file_button.click()
                        open_url.assert_called_once_with(QUrl.fromLocalFile(str(first_preview)))
                    theme = "dark" if get_settings().get("theme") == "dark" else "light"
                    self.assertIn(GRR_COLOURS[theme][0], labels["CD"].styleSheet())
                    self.assertIn(GRR_COLOURS[theme][1], labels["EW"].styleSheet())
                    self.assertTrue(labels["CD"].isVisible())
                    APP.processEvents()
                    for name, plot in zip(("CD", "EW"), page.plots[-2:]):
                        axis = plot.getAxis("bottom")
                        axis_label = plot.mapFromScene(axis.label.sceneBoundingRect().center())
                        axis_center = plot.viewport().mapTo(page.plot_host, axis_label).x()
                        label = labels[name]
                        center = label.mapTo(page.plot_host, label.contentsRect().center()).x()
                        self.assertAlmostEqual(center, axis_center, delta=2)
                        gap = label.mapTo(page.plot_host, label.contentsRect().topLeft()).y()
                        gap -= plot.viewport().mapTo(
                            page.plot_host, plot.mapFromScene(axis.label.sceneBoundingRect().bottomLeft())
                        ).y()
                        self.assertTrue(0 <= gap <= 9, gap)

                    cd_column = dynamic.model.document_frame().columns.get_loc("CD")
                    dynamic.model.edit({(1, cd_column): "105"})
                    self.wait_for_results(page, {"CD": "GRR: Review", "EW": "GRR: Review"})
                    dynamic.model.edit({(1, cd_column): "101"})
                    path = workbook.save_workbook(root / "project.mwkb")
                    sidecar = path.with_name("GRR_project.xlsx")
                    self.assertEqual(page.grr_report_path.text(), str(sidecar))
                    self.assertTrue(page.grr_report_controls.isVisible())
                    with patch.object(QDesktopServices, "openUrl", return_value=True) as open_url:
                        page.open_grr_file_button.click()
                        open_url.assert_called_once_with(QUrl.fromLocalFile(str(sidecar)))
                        open_url.reset_mock()
                        page.open_grr_folder_button.click()
                        open_url.assert_called_once_with(QUrl.fromLocalFile(str(root)))
                    report = load_workbook(sidecar)
                    try:
                        self.assertEqual([name for name in report.sheetnames if name.endswith("_GRR")],
                                         ["CD_GRR", "EW_GRR"])
                        self.assertEqual(report["CD_GRR"]["D12"].value, 101)
                        self.assertEqual(report["EW_GRR"]["P26"].value, 1813)
                        self.assertEqual(report["EW_GRR"]["M96"].data_type, "f")
                    finally:
                        report.close()

                    original_report = sidecar.read_bytes()
                    dynamic.model.edit({(1, cd_column): "105"})
                    self.wait_for_results(page, {"CD": "GRR: Review", "EW": "GRR: Review"})
                    edited_preview = Path(page.grr_report_path.text())
                    self.assertTrue(edited_preview.is_file())
                    self.assertNotEqual(edited_preview, sidecar)
                    with edited_preview.open("rb") as stream:
                        preview = load_workbook(stream)
                        try:
                            self.assertEqual(preview["CD_GRR"]["D12"].value, 105)
                        finally:
                            preview.close()
                    self.assertEqual(sidecar.read_bytes(), original_report)
                    dynamic.model.undo.undo()
                    self.wait_for_results(page, {"CD": "GRR: Excellent", "EW": "GRR: Review"})
                    self.assertEqual(page.grr_report_path.text(), str(sidecar))

                    workbook.document.force_close = True
                    workbook.close()
                    reopened = MatchingWindow()
                    reopened.load_workbook(path)
                    with patch.object(QFileDialog, "getOpenFileName") as choose:
                        restored = reopened.open_dynamic_workspace("preview")
                        restored.tabs.setCurrentWidget(restored.dynamic_page)
                        self.assertEqual(restored.dynamic_page.grr_report_path.text(), str(sidecar))
                        self.wait_for_results(restored.dynamic_page, {"CD": "GRR: Excellent", "EW": "GRR: Review"})
                    choose.assert_not_called()
                    self.assertEqual(reopened.save_workbook(root / "copy.mwkb"), root / "copy.mwkb")
                    self.assertTrue((root / "GRR_copy.xlsx").is_file())
                    self.assertEqual(restored.dynamic_page.grr_report_path.text(), str(root / "GRR_copy.xlsx"))
                    self.assertFalse(list(root.glob("GRR_*.bak")))
                finally:
                    for owner in (workbook, reopened):
                        if owner is not None:
                            owner.document.force_close = True
                            owner.close()
                            owner.deleteLater()
                    APP.processEvents()
