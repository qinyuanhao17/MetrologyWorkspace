import tempfile
import unittest
from pathlib import Path

import pandas as pd
import numpy as np
from openpyxl import Workbook

from metrology_app.mark2 import config, hierarchy, import_excel, labels_for_raw, ordered_rows


HEADERS = ["Cur SME File Path", "Wafer ID", "Lot ID", "Tool SN", "PAD Name", "Die Seq", "FIELD X", "FIELD Y"]


def fixture():
    rows = [["a", "03", "L", "T", "P", "1", "0", "0"],
            ["b", "03", "L", "T", "P", "2", "0", "1"],
            ["c", "04", "L", "T", "P", "1", "0", "0"]]
    state = config({"identity_columns": HEADERS, "columns": ["Product", "Slot", "Die"],
                    "selected": ["Product", "Slot", "Die"], "order_mode": "hierarchy",
                    "records": [{"identity": r, "values": v} for r, v in zip(rows, [
                        ["B", "03", "1"], ["A", "11", "2"], ["A", "2", "1"]])]})
    return pd.DataFrame(rows, columns=HEADERS), state


class Mark2Tests(unittest.TestCase):
    def test_source_identity_survives_reordering_and_preserves_leading_zeros(self):
        raw, state = fixture()
        raw = raw.iloc[[2, 0, 1]].reset_index(drop=True)
        labels = labels_for_raw(raw, state)
        self.assertEqual(labels[1], ("B", "03", "1"))
        self.assertEqual(ordered_rows(range(3), labels, state), [0, 2, 1])
        state["order_mode"] = "source"
        self.assertEqual(ordered_rows([2, 0, 1], labels, state), [0, 1, 2])
        raw.loc[1, "Wafer ID"] = "3"
        self.assertEqual(labels_for_raw(raw, state)[1], ("", "", ""))

    def test_ambiguous_or_missing_identities_have_empty_labels(self):
        raw, state = fixture()
        raw = pd.concat([raw, raw.iloc[[0]]], ignore_index=True)
        self.assertEqual(labels_for_raw(raw, state)[0], ("", "", ""))
        self.assertEqual(labels_for_raw(raw, state)[3], ("", "", ""))

    def test_nested_spans_follow_parent_prefixes_and_contiguous_runs(self):
        spans = hierarchy(["Product", "Slot"], [["A", "1"], ["A", "2"], ["B", "2"], ["A", "1"]])
        self.assertEqual([(s["start"], s["end"]) for s in spans if s["level"] == 1],
                         [(.5, 2.5), (2.5, 3.5), (3.5, 4.5)])
        self.assertEqual(len([s for s in spans if s["level"] == 0]), 4)

    def test_import_ignores_empty_formatted_columns_and_rejects_duplicates(self):
        raw, _state = fixture()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "labels.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.append(HEADERS + [None, "Product", "Slot"])
            for row in raw.itertuples(index=False, name=None):
                sheet.append([*row, None, "A", "03"])
            sheet.cell(4, 34).number_format = "0.00"
            book.save(path)
            imported = import_excel(path)
            self.assertEqual(imported["columns"], ["Product", "Slot"])
            self.assertEqual(labels_for_raw(raw, imported)[0], ("A", "03"))
            sheet.append([*raw.iloc[0].tolist(), None, "B", "04"])
            book.save(path)
            with self.assertRaisesRegex(ValueError, "duplicate"):
                import_excel(path)

    def test_legacy_state_defaults_off_and_mark2_is_exclusive(self):
        from metrology_app.match_groups import group_state
        self.assertFalse(group_state({})["mark2_enabled"])
        state = group_state({"mark2_enabled": True, "enabled": True, "mark_enabled": True})
        self.assertFalse(state["enabled"])
        self.assertFalse(state["mark_enabled"])

    def test_product_codes_are_text_while_slots_and_die_sort_numerically(self):
        from metrology_app.mark2 import natural_key
        self.assertEqual(sorted(["0E69", "0CM2", "0EYB"], key=natural_key), ["0CM2", "0E69", "0EYB"])
        self.assertEqual(sorted(["11", "03", "2"], key=natural_key), ["2", "03", "11"])

    def test_rebinding_numeric_values_reuses_labels_but_identity_changes_cannot(self):
        from metrology_app.match_groups import GroupPlan
        raw, state = fixture()
        raw = raw.rename(columns={"FIELD X": "Field X"})
        raw["CD"] = ["1", "2", "3"]
        reference = pd.DataFrame(index=range(3))
        plan = GroupPlan(raw, state={"mark2_enabled": True, "mark2": state}, reference=reference)
        numeric = raw.copy()
        numeric.loc[0, "CD"] = "4"
        self.assertIsNotNone(plan.rebind_sources(numeric, reference))
        numeric.loc[0, "Field X"] = "123"
        self.assertIsNone(plan.rebind_sources(numeric, reference))


class Mark2IntegrationTests(unittest.TestCase):
    def setUp(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        self.app = QApplication.instance() or QApplication([])
        self.window = MatchingWindow()
        self.window.apply_analysis_settings({"workbook_type": "type2"}, refresh=False)
        raw, self.state = fixture()
        raw["CD"] = ["1.000", "2.000", "3.000"]
        ref = raw.iloc[[1, 0]][["Wafer ID", "Die Seq"]].copy()
        ref["CD"] = ["5.0000", "3.0000"]
        self.window.set_reference_frame(ref)
        self.window.set_raw_frame(raw)
        self.window.set_matching_keys({"reference": ["Wafer ID", "Die Seq"], "raw": ["Wafer ID", "Die Seq"]})
        controls = self.window.group_controls
        controls.change("mark2", self.state)
        controls.mark2_enabled.setChecked(True)
        self.window.percent_bias.setChecked(True)
        self.window.run_analysis()

    def tearDown(self):
        for child in self.window._stage_windows:
            child.document.force_close = True
            child.close()
        self.window.document.force_close = True
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_window_axes_pairing_and_saved_recovery(self):
        from metrology_app.mark2_plotting import HierarchyAxis
        from metrology_app.matching_window import MatchingWindow
        controls = self.window.group_controls
        self.assertFalse(controls.enabled.isEnabled())
        self.assertFalse(controls.mark_enabled.isChecked())
        self.assertFalse(controls.order.isEnabled())
        data = self.window._parameter_plot_data("CD")
        self.assertEqual(data["Source row"].tolist(), [2, 1, 0])
        np.testing.assert_allclose(data["Reference"], [np.nan, 5, 3], equal_nan=True)
        plots = self.window.plot_groups["CD"]["plots"]
        for panel in ("trend", "bias", "bias-percent"):
            self.assertIsInstance(plots[panel].getAxis("bottom"), HierarchyAxis)
        self.assertGreater(self.window.plot_groups["CD"]["plot_area"].plot_height, 330)
        with tempfile.TemporaryDirectory() as folder:
            path = self.window.save_workbook(Path(folder) / "mark2.mwkb")
            reopened = MatchingWindow()
            try:
                reopened.load_workbook(path)
                self.assertEqual(reopened.group_controls.state["mark2"], self.state)
                self.assertEqual(reopened._parameter_plot_data("CD")["Source row"].tolist(), [2, 1, 0])
                self.assertFalse(reopened.document.is_dirty())
                self.assertFalse(reopened.group_controls.order.isEnabled())
                self.window.matching_settings_toggle.setChecked(False)
                self.window.document.recovery_path = Path(folder) / "recovery.mwkb"
                self.window.document.write_recovery()
                reopened.document.recover(self.window.document.recovery_path)
                self.assertTrue(reopened.group_controls.state["mark2_enabled"])
            finally:
                reopened.document.force_close = True
                reopened.close()
                reopened.deleteLater()
        controls.mark2_enabled.setChecked(False)
        self.window.run_analysis()
        self.assertTrue(controls.enabled.isEnabled())
        self.assertTrue(controls.order.isEnabled())
        self.assertNotIsInstance(self.window.plot_groups["CD"]["plots"]["trend"].getAxis("bottom"), HierarchyAxis)

    def test_source_mode_reordering_and_single_wafer_keep_labels_on_their_rows(self):
        from metrology_app.match_groups import GroupPlan
        raw, state = fixture()
        for mode, expected in (("source", [0, 1, 2]), ("hierarchy", [2, 1, 0])):
            state["order_mode"] = mode
            plan = GroupPlan(raw, state={"mark2_enabled": True, "mark2": state})
            self.assertEqual(plan.trend_spans()[0]["rows"], expected)
        scoped = self.window.result.plot_scope([0, 2], label="Wafers")
        self.assertEqual(scoped.group_series("CD", trend=True)["Source row"].tolist(), [2, 0])
        from metrology_app.mark2_plotting import HierarchyAxis
        self.window._wafer_checked("CD", 0, True)
        details = self.window.plot_groups["CD"]["wafer_details"]
        self.assertEqual(len(details), 1)
        detail = next(iter(details.values()))
        for panel in ("trend", "bias", "bias-percent"):
            self.assertIsInstance(detail["plots"][panel].getAxis("bottom"), HierarchyAxis)
        self.assertEqual(detail["result"].group_series("CD", trend=True)["Raw"].tolist(), [2, 1])

    def test_changing_order_applies_to_curves_without_refitting_or_modifying_sources(self):
        from metrology_app.mark2_ui import Mark2Dialog
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QDialogButtonBox
        raw_before = self.window.raw_model.document_frame().copy()
        ref_before = self.window.reference_model.document_frame().copy()
        card_before = self.window.result.card("CD")
        state = {**self.state, "order_mode": "source"}
        self.window.group_controls.change("mark2", state)
        self.assertEqual(self.window._parameter_plot_data("CD")["Source row"].tolist(), [2, 1, 0])
        self.window.run_analysis()
        self.assertEqual(self.window._parameter_plot_data("CD")["Source row"].tolist(), [0, 1, 2])
        self.assertEqual(self.window.result.card("CD"), card_before)
        pd.testing.assert_frame_equal(self.window.raw_model.document_frame(), raw_before)
        pd.testing.assert_frame_equal(self.window.reference_model.document_frame(), ref_before)
        dialog = Mark2Dialog(state)
        try:
            item = dialog.fields.takeItem(0)
            dialog.fields.addItem(item)
            self.assertEqual(dialog.settings()["selected"], ["Slot", "Die", "Product"])
            for i in range(dialog.fields.count()):
                dialog.fields.item(i).setCheckState(Qt.CheckState.Unchecked)
            self.assertFalse(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled())
        finally:
            dialog.deleteLater()

    def test_manage_mark2_ok_applies_and_refreshes_existing_plots_without_apply(self):
        from PyQt6.QtCore import QTimer, Qt
        from PyQt6.QtWidgets import QDialogButtonBox
        from metrology_app.mark2_ui import Mark2Dialog
        from metrology_app.mark2_plotting import HierarchyAxis
        raw_before = self.window.raw_model.document_frame().copy()
        self.window._wafer_checked("CD", 0, True)
        child = self.window.open_correlation_workspace()
        page = child.sequence_page
        page.draw_plot()
        errors = []

        def accept_settings():
            dialog = self.app.activeModalWidget()
            try:
                self.assertIsInstance(dialog, Mark2Dialog)
                dialog.fields.item(0).setCheckState(Qt.CheckState.Unchecked)
                dialog.order.setCurrentIndex(dialog.order.findData("source"))
                dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).click()
            except Exception as error:
                errors.append(error)
                dialog.reject()

        QTimer.singleShot(0, accept_settings)
        self.window.group_controls.manage_mark2()
        self.assertEqual(errors, [])
        self.window.finish_linked_updates()
        page.finish_background_draw()
        self.app.processEvents()
        self.assertFalse(self.window.group_controls.pending)
        self.assertEqual(self.window._parameter_plot_data("CD")["Source row"].tolist(), [0, 1, 2])
        main = self.window.plot_groups["CD"]
        detail = next(iter(main["wafer_details"].values()))
        for block in (main, detail):
            for name in ("trend", "bias", "bias-percent"):
                axis = block["plots"][name].getAxis("bottom")
                self.assertIsInstance(axis, HierarchyAxis)
                self.assertEqual(axis.columns, ("Slot", "Die"))
        self.assertEqual(page.selection["mark2"]["columns"], ["Slot", "Die"])
        self.assertEqual(page.selection["mark2"]["order"], [0, 1, 2])
        from PyQt6.QtTest import QTest
        QTest.qWait(250)
        self.assertTrue(page.ready, page.status.text())
        self.assertTrue(page.plot_widgets)
        self.assertTrue(all(w.getAxis("bottom").columns == ("Slot", "Die") for w in page.plot_widgets))
        pd.testing.assert_frame_equal(self.window.raw_model.document_frame(), raw_before)

    def test_manage_mark2_cancel_keeps_settings_and_plots(self):
        from PyQt6.QtCore import QTimer
        before = self.window._parameter_plot_data("CD").copy()
        applied = self.window.result.group_plan
        QTimer.singleShot(0, lambda: self.app.activeModalWidget().reject())
        self.window.group_controls.manage_mark2()
        self.assertIs(self.window.result.group_plan, applied)
        self.assertFalse(self.window.group_controls.pending)
        pd.testing.assert_frame_equal(self.window._parameter_plot_data("CD"), before)

    def test_linked_trend_uses_same_mark2_domain_with_missing_reference(self):
        from metrology_app.mark2_plotting import HierarchyAxis
        child = self.window.open_correlation_workspace()
        child.update_plan()
        page = child.sequence_page
        self.assertIn("mark2", page.selection)
        page.draw_plot()
        self.assertTrue(page.ready, page.status.text())
        self.assertEqual(page._mark2_values, [("A", "2", "1"), ("A", "11", "2"), ("B", "03", "1")])
        self.assertTrue(all(isinstance(w.getAxis("bottom"), HierarchyAxis) for w in page.plot_widgets))
        page.build_export_figure(page.display_panel_specs(), page.view_groups)
        self.assertIn("A", [t.get_text() for a in page.figure.axes for t in a.texts])
        self.assertTrue(all("mark2" in plot for plot in page.export_plot_data()))
        from zipfile import ZipFile
        with tempfile.TemporaryDirectory() as folder:
            native = self.window.export_excel(Path(folder) / "linked.xlsx")
            with ZipFile(native) as archive:
                footers = [archive.read(n).decode("utf-8") for n in archive.namelist()
                           if "identity-" in n and n.endswith(".xml")]
            self.assertTrue(any("Correlation and Tre" in xml and "Mark2 caption" in xml for xml in footers))
            image_report = self.window.export_excel(Path(folder) / "images.xlsx", native=False)
            with ZipFile(image_report) as archive:
                self.assertTrue(any(n.startswith("xl/media/") for n in archive.namelist()))

    def test_native_and_matplotlib_export_share_mark2_fields_and_ordinals(self):
        from metrology_app.excel_export import _parameter_data, parameter_figure
        from metrology_app.mark2_export import layout
        from openpyxl import load_workbook
        from zipfile import ZipFile
        data = _parameter_data(self.window.result, "CD", order="original")
        self.assertEqual(data["Source row"].tolist(), [2, 1, 0])
        values = data[["Mark2 · " + c for c in self.state["selected"]]].values.tolist()
        figure = parameter_figure("CD", data, self.window.result.card("CD"), "Preview", "All", panel="Bias %",
                                 sequence=layout(self.state["selected"], values, []))
        self.assertIn("A", [t.get_text() for t in figure.axes[0].texts])
        with tempfile.TemporaryDirectory() as folder:
            path = self.window.export_excel(Path(folder) / "mark2.xlsx")
            book = load_workbook(path)
            charts = [c for s in book for c in s._charts]
            self.assertTrue(charts)
            with ZipFile(path) as archive:
                drawings = [archive.read(n).decode("utf-8") for n in archive.namelist() if "identity-" in n and n.endswith(".xml")]
            self.assertTrue(any("Mark2 caption" in xml and "TxLink" in xml for xml in drawings))
            self.assertTrue(any("Mark2 · Product" == cell.value for sheet in book for row in sheet for cell in row))
            book.close()

    def test_multiple_parameter_export_keeps_label_blocks_and_literal_source_separate(self):
        from metrology_app.matching import MatchWorkbook, ParameterMapping
        from metrology_app.excel_export import write_workbook
        from openpyxl import load_workbook
        raw = self.window.raw_model.document_frame().copy()
        ref = self.window.reference_model.document_frame().copy()
        raw["CD2"] = ["10.000", "20.000", "30.000"]
        ref["CD2"] = ["50.0000", "30.0000"]
        domain = MatchWorkbook(ref, raw, [ParameterMapping("CD", "CD", "CD"), ParameterMapping("CD2", "CD2", "CD2")],
                               workbook_type="type2", matching_keys=self.window.matching_keys,
                               grouping_state=self.window.group_controls.state)
        with tempfile.TemporaryDirectory() as folder:
            path = write_workbook(Path(folder) / "multiple.xlsx", reference=ref,
                                  stages=[(domain, domain.analyze(), raw, ())])
            report = load_workbook(path)
            try:
                sheet = next(s for s in report if s.title.startswith("Match Original"))
                self.assertEqual(sheet.cell(1, 1).value, "CD")
                self.assertEqual(sheet.cell(1, 12).value, "CD2")
                import re
                first_source = re.search(r"!\$(\w+)\$(\d+)", sheet.cell(3, 6).value)
                second_source = re.search(r"!\$(\w+)\$(\d+)", sheet.cell(3, 17).value)
                self.assertEqual(sheet[f"{first_source[1]}{first_source[2]}"].value, "3.000")
                self.assertEqual(sheet[f"{second_source[1]}{second_source[2]}"].value, "30.000")
                self.assertEqual(sheet.cell(3, 3).value, "A")
                self.assertEqual(sheet.cell(3, 14).value, "A")
            finally:
                report.close()


if __name__ == "__main__":
    unittest.main()
