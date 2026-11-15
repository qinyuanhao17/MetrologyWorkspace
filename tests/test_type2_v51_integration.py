"""Type2/Mark2 workflows retained when adopting v5.1.0 Spectra integration."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import pandas as pd
from openpyxl import Workbook
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QDoubleSpinBox

from metrology_app.mark2 import import_excel
from metrology_app.mark2_plotting import HierarchyAxis
from metrology_app.matching import ParameterMapping
from metrology_app.matching_window import MatchingWindow
from metrology_app.sme_spectra import LoadResult
from tests.test_spectra_viewer import make_spectrum

APP = QApplication.instance() or QApplication([])
IDENTITY = ["Cur SME File Path", "Wafer ID", "Lot ID", "Tool SN", "PAD Name", "Die Seq", "FIELD X", "FIELD Y"]


def sources():
    spectra = tuple(make_spectrum(die, wafer=wafer) for wafer in ("W1", "W2") for die in (1, 2, 3))
    raw = pd.DataFrame([
        [f"C:/fixtures/{s.identity.wafer}_202610311000{s.identity.die_seq:02d}000.sme",
         s.identity.wafer, "L1", "A03-090", "P1", str(s.identity.die_seq), "-1", "5", f"{i + 1}.000"]
        for i, s in enumerate(spectra)], columns=[*IDENTITY, "CD"])
    ref = pd.DataFrame({"Ref Wafer": raw["Wafer ID"], "Ref Die": raw["Die Seq"],
                        "REF CD": [f"{2 * i + 3}.0000" for i in range(6)]}).iloc[[4, 2, 0, 3, 1]].reset_index(drop=True)
    config = {"identity_columns": IDENTITY, "columns": ["Product", "Wafer", "Die"],
              "selected": ["Product", "Die"], "order_mode": "hierarchy",
              "records": [{"identity": raw.iloc[i][IDENTITY].tolist(), "values": [product, label, raw.iloc[i]["Die Seq"]]}
                          for i, (product, label) in enumerate(zip(["A", "B", "A", "A", "B", "A"],
                                                                  ["Pool", "Pool", "Other", "Pool", "Other", "Other"]))]}
    return raw, ref, config, spectra


class Type2V51IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.raw, self.ref, self.config, self.spectra = sources()
        self.window = MatchingWindow()
        self.window.document.force_close = True
        self.addCleanup(self.close_window)
        self.window.apply_analysis_settings({"workbook_type": "type2"}, refresh=False)
        self.window.set_raw_frame(self.raw)
        self.window.set_reference_frame(self.ref)
        self.window.set_matching_keys({"reference": ["Ref Wafer", "Ref Die"], "raw": ["Wafer ID", "Die Seq"]})
        self.window._populate_mappings([ParameterMapping("CD", "REF CD", "CD")])
        self.window.group_controls.change("mark2", self.config)
        self.window.group_controls.mark2_enabled.setChecked(True)
        self.window.percent_bias.setChecked(True)
        self.window.run_analysis()

    def close_window(self):
        for child in tuple(self.window._stage_windows):
            child.document.force_close = True
            child.close()
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def open_spectra(self):
        viewer = self.window.open_spectra_workspace()
        viewer.apply_load_result(LoadResult(self.spectra, ()), replace=True)
        viewer.set_spectrum_checks({s.key: True for s in self.spectra})
        return viewer

    def test_card_source_selects_a_mark2_label_and_restores_stage_manual_coefficients(self):
        from unittest.mock import patch
        from metrology_app.card_source_ui import ManualCardDialog

        window = self.window
        ref = self.ref.copy()
        ref.loc[[0, 1], "REF CD"] = ["35", "25"]
        window.set_reference_frame(ref)
        controls = window.card_source_controls
        controls.mode.setCurrentIndex(controls.mode.findData("group"))
        field = next(i for i in range(controls.scope.count()) if controls.scope.itemText(i) == "Mark2 · Wafer")
        controls.scope.setCurrentIndex(field)  # Wafer is available even though it is not a hierarchy field.
        controls.value.setCurrentIndex(controls.value.findData("Pool"))
        self.assertFalse(window._analysis_current)
        window.run_analysis()
        self.assertEqual(window.result.card("CD").valid_pairs, 3)
        np.testing.assert_allclose(window.result.series("CD")["Bias"], [0, 0, -18, 0, -24, np.nan], atol=1e-12)

        window.result_mode.setCurrentText("Final")
        window.set_raw_frame(self.raw)
        controls.mode.setCurrentIndex(controls.mode.findData("manual"))

        def enter_coefficients(dialog):
            dialog.table.item(0, 1).setText("0.75")
            dialog.table.item(0, 2).setText("-2.5")
            dialog.accept()
            return dialog.result()

        with patch.object(ManualCardDialog, "exec", enter_coefficients):
            controls.edit.click()
        window.run_analysis()
        card = window.result.card("CD")
        self.assertEqual((card.slope, card.intercept, card.valid_pairs), (.75, -2.5, 0))
        self.assertTrue(np.isnan(card.r_squared))
        np.testing.assert_allclose(window.result.series("CD")["Evaluated Value"], [1, 2, 3, 4, 5, 6])
        with TemporaryDirectory() as directory:
            saved = window.save_workbook(Path(directory) / "card-source.mwkb")
            window.load_workbook(saved)
            self.assertEqual(controls.mode.currentData(), "manual")
            self.assertEqual(controls.status.text(), "1 / 1 configured")
            self.assertEqual(window.result.card("CD").intercept, -2.5)
            window.result_mode.setCurrentText("Preview")
            self.assertEqual(controls.mode.currentData(), "group")
            self.assertEqual(controls.value.currentData(), "Pool")
            self.assertAlmostEqual(window.result.card("CD").slope, 2.)
            self.assertEqual(window.workbook.parameter_cards(stage="final")["CD"], (.75, -2.5))

    def test_preview_mark2_offsets_center_valid_pairs_and_keep_raw_correlation(self):
        from unittest.mock import patch

        from openpyxl import load_workbook
        from PyQt6.QtWidgets import QDialogButtonBox

        from metrology_app.card_source_ui import Mark2OffsetsDialog
        from metrology_app.excel_export import _parameter_data, parameter_figure, write_workbook

        window = self.window
        config = deepcopy(self.config)
        config["records"][-1]["values"][1] = "No pair"
        window.group_controls.change("mark2", config)
        controls = window.card_source_controls
        controls._change(mode="manual", manual=[["CD", "REF CD", "CD", 1., 0.]])
        window.run_analysis()
        baseline = window.result.series("CD")
        self.assertFalse(controls.offset_controls.isHidden())
        controls.offset_enabled.setChecked(True)
        controls.offset_field.setCurrentIndex(controls.offset_field.findData("Wafer"))
        self.assertFalse(controls.view_offsets.isEnabled())
        window.run_analysis()
        result = window.result
        series = result.series("CD")
        pd.testing.assert_series_equal(series["Raw"], baseline["Raw"])
        pd.testing.assert_series_equal(series["Reference"], baseline["Reference"])
        self.assertEqual((result.card("CD").slope, result.card("CD").intercept), (1., 0.))
        np.testing.assert_allclose(series["Mark2 Offset"], [10 / 3, 10 / 3, 5., 10 / 3, 5., 0.])
        np.testing.assert_allclose([series["Bias"].iloc[[0, 1, 3]].mean(),
                                    series["Bias"].iloc[[2, 4]].mean()], 0., atol=1e-12)
        self.assertTrue(np.isnan(result.mark2_offset_table().at["No pair", "CD"]))
        preview = window.workbook.stage_frame("preview", analysis_result=result, use_snapshot=False)
        np.testing.assert_allclose(preview["CD"], series["Evaluated Value"])

        def copy_offsets(dialog):
            self.assertEqual(dialog.headers, ["Wafer", "CD"])
            self.assertEqual(dialog.rows[0], ["No pair", "—"])
            buttons = dialog.findChild(QDialogButtonBox)
            next(button for button in buttons.buttons() if button.text() == "Copy All").click()
            self.assertEqual(APP.clipboard().text(), "Wafer\tCD\nNo pair\t—\nOther\t5.00000\nPool\t3.33333\n")
            return dialog.result()

        self.addCleanup(APP.clipboard().setText, APP.clipboard().text())
        with patch.object(Mark2OffsetsDialog, "exec", copy_offsets):
            self.assertTrue(controls.view_offsets.isEnabled())
            controls.view_offsets.click()

        data = _parameter_data(result, "CD", order="original")
        card = result.card("CD")
        scatter = parameter_figure("CD", data, card, "Preview", "All").axes[0].collections[0].get_offsets()
        np.testing.assert_allclose(scatter, data[["Raw", "Reference"]].dropna().to_numpy())
        trend = parameter_figure("CD", data, card, "Preview", "All", panel="Trend").axes[0].lines[0]
        np.testing.assert_allclose(trend.get_ydata(), data["Evaluated Value"])
        bias = parameter_figure("CD", data, card, "Preview", "All", panel="Bias").axes[0].lines[0]
        np.testing.assert_allclose(bias.get_ydata(), data["Bias"])

        with TemporaryDirectory() as directory:
            path = Path(directory) / "mark2-offset.xlsx"
            sheet_name = "Match Original (WO Card)"
            write_workbook(path, **window.excel_export_snapshot(), selected_sheets=[sheet_name])
            book = load_workbook(path)
            try:
                sheet = book[sheet_name]
                headers = {cell.value: cell.column_letter for cell in sheet[2] if cell.value}
                corrected = headers["PMISH+Card"]
                for row, offset in enumerate(data["Mark2 Offset"], 3):
                    if offset:
                        self.assertIn(f"+({offset:.17g})", sheet[f"{corrected}{row}"].value)
                match, trend, bias, *_ = sheet._charts
                self.assertIn(f'${headers["PMISH"]}$3:', match.series[0].xVal.numRef.f)
                self.assertIn(f"${corrected}$3:", trend.series[0].val.numRef.f)
                self.assertIn(f'${headers["Bias"]}$3:', bias.series[0].val.numRef.f)
            finally:
                book.close()
            saved = window.save_workbook(Path(directory) / "mark2-offset.mwkb")
            window.load_workbook(saved)
            self.assertTrue(controls.offset_enabled.isChecked())
            self.assertEqual(controls.offset_field.currentData(), "Wafer")

        window.result_mode.setCurrentText("Final")
        window.set_raw_frame(self.raw)
        window.run_analysis()
        self.assertTrue(controls.offset_controls.isHidden())
        final = window.result.series("CD")
        self.assertNotIn("Mark2 Offset", final)
        np.testing.assert_allclose(final["Evaluated Value"], final["Raw"])

    def test_mean_bias_auto_range_has_a_floor_but_manual_range_can_be_smaller(self):
        from metrology_app.plotting.wafer_metrics import WaferMetricPlot

        plot = WaferMetricPlot()
        self.addCleanup(plot.deleteLater)
        summary = pd.DataFrame({"Wafer": ["A", "B"], "Mean Bias": [-1e-10, 2e-10]})
        plot.set_summary("wafer_mean_bias", summary, "Wafer", "PMISH+Card")
        view = plot.view_box
        low, high = view.viewRange()[1]
        self.assertLessEqual(low, -0.001)
        self.assertGreaterEqual(high, 0.001)

        menu = view.getMenu(None)
        y_axis = menu.ctrl[1]
        y_axis.minText.setText("-0.0001")
        y_axis.maxText.setText("0.0002")
        menu.yRangeTextChanged()
        plot.set_summary("wafer_mean_bias", summary, "Wafer", "PMISH+Card")
        np.testing.assert_allclose(view.viewRange()[1], [-0.0001, 0.0002])

        summary["Mean Bias"] = [-0.02, 0.03]
        plot.set_summary("wafer_mean_bias", summary, "Wafer", "PMISH+Card")
        menu.yAutoClicked()
        low, high = view.viewRange()[1]
        self.assertLessEqual(low, -0.02)
        self.assertGreaterEqual(high, 0.03)

    def test_group_menu_actions_follow_mark2_when_toggled_and_reopened(self):
        window = self.window
        ordinary_actions = (window.plot_labels_menu.menuAction(), window.manage_groups_action)
        mark2 = window.group_controls.mark2_enabled

        def check_actions(enabled):
            for action in ordinary_actions:
                self.assertEqual(action.isEnabled(), enabled, action.text())
            self.assertTrue(window.manage_mark2_action.isEnabled())

        check_actions(False)
        mark2.setChecked(False)
        check_actions(True)
        window.plot_label_checks["trend"]["pad"].setChecked(False)
        mark2.setChecked(True)
        check_actions(False)
        window.run_analysis()

        with TemporaryDirectory() as directory:
            saved = window.save_workbook(Path(directory) / "mark2-labels.mwkb")
            mark2.setChecked(False)
            check_actions(True)
            window.load_workbook(saved)
            check_actions(False)
            mark2.setChecked(False)
            check_actions(True)
            self.assertFalse(window.plot_label_checks["trend"]["pad"].isChecked())

    def test_dynamic_opens_with_valid_cards_when_another_fit_fails(self):
        window = self.window
        window.set_reference_frame(self.ref.assign(Constant="0"))
        window.set_raw_frame(self.raw.assign(Constant="0"))
        window._populate_mappings([
            ParameterMapping("CD", "REF CD", "CD"),
            ParameterMapping("Constant", "Constant", "Constant"),
        ])
        window.run_analysis()
        self.assertTrue(np.isnan(window.result.card("Constant").slope))

        dynamic = window.open_dynamic_workspace("preview")
        self.assertEqual(set(dynamic.parameter_cards), {"CD"})
        self.assertTrue(dynamic.card_check.isEnabled())
        self.assertEqual(set(dynamic.workspace_snapshot().states["ui"]["cards"]), {"CD"})

    def test_type2_bias_has_no_unit_in_plots_limits_or_excel(self):
        from openpyxl import load_workbook

        self.window.set_reference_frame(self.ref.rename(columns={"REF CD": "REF CD (um)"}))
        self.window._populate_mappings([ParameterMapping("CD", "REF CD (um)", "CD", .75, True)])
        self.window.run_analysis()
        plots = self.window.plot_groups["CD"]["plots"]
        self.assertEqual(plots["bias"].getAxis("left").labelText, "Bias")
        self.assertEqual(plots["bias-percent"].getAxis("left").labelText, "Bias (%)")
        self.assertEqual([line.toolTip() for line in plots["bias"]._bias_limit_lines],
                         ["Bias limit: -0.75", "Bias limit: +0.75"])
        spin = self.window.mapping_table.cellWidget(0, 10).findChild(QDoubleSpinBox)
        self.assertEqual(spin.suffix(), "")
        self.assertEqual(spin.value(), .75)

        with TemporaryDirectory() as directory:
            path = self.window.export_excel(Path(directory) / "bias.xlsx")
            exported = load_workbook(path)
            try:
                for sheet in (s for s in exported if s.title.startswith(("Match Original", "Match Wafer"))):
                    y_labels = ["".join(run.t for paragraph in chart.y_axis.title.tx.rich.p for run in paragraph.r)
                                for chart in sheet._charts if chart.y_axis.title is not None]
                    self.assertIn("Bias", y_labels)
                    self.assertIn("Bias %", y_labels)
                    self.assertNotIn("Bias (um)", y_labels)
                units = [value for label, value in exported["_Plot data"].iter_rows(
                    min_col=10, max_col=11, values_only=True) if label == "Unit"]
                self.assertTrue(units)
                self.assertTrue(all(value in (None, "") for value in units))
            finally:
                exported.close()

    def test_single_tag_metrics_fit_across_wafers_draw_and_restore_wafer_choices(self):
        overall = self.window.result.card("CD")
        self.window._wafer_checked("CD", 0, True)
        wafer_choice = deepcopy(self.window._single_wafer_checks)
        combo = self.window.metrics_group_combo
        combo.setCurrentIndex(combo.findData("Product"))
        group = self.window.plot_groups["CD"]
        summary = group["wafer_summary"]
        self.assertEqual(summary["Wafer"].tolist(), ["A", "B"])
        self.assertEqual(summary["Valid pairs"].tolist(), [3, 2])
        np.testing.assert_allclose(summary["Slope"], [2, 2])
        np.testing.assert_allclose(summary["Intercept"], [1, 1])
        np.testing.assert_allclose(summary["R²"], [1, 1])
        self.assertIn("Mark2 · Product", group["wafer_model"].frame)
        self.window._wafer_checked("CD", 0, True)
        detail = group["wafer_details"]["A"]
        self.assertEqual(detail["source_raw"]["Wafer ID"].tolist(), ["W1", "W1", "W2", "W2"])
        self.assertEqual(len(detail["source_raw"]), 4)
        self.assertEqual(detail["result"].card("CD").valid_pairs, 3)
        for name in ("trend", "bias", "bias-percent"):
            self.assertIsInstance(detail["plots"][name].getAxis("bottom"), HierarchyAxis)
        self.assertTrue(detail["result"].series("CD")["Reference"].isna().any())
        self.assertEqual(self.window.result.card("CD"), overall)
        combo.setCurrentIndex(0)
        self.assertEqual(self.window._single_wafer_checks, wafer_choice)
        self.assertEqual(len(group["wafer_summary"]), 2)
        self.assertEqual(len(group["wafer_details"]), 1)
        combo.setCurrentIndex(combo.findData("Product"))
        self.assertTrue(group["wafer_model"].frame["Draw"].iloc[0])
        pd.testing.assert_frame_equal(self.window.raw_model.document_frame(), self.raw)
        pd.testing.assert_frame_equal(self.window.reference_model.document_frame(), self.ref)

    def test_custom_wafer_header_is_separate_and_group_preference_survives_save_recovery(self):
        with TemporaryDirectory() as directory:
            table = Workbook()
            sheet = table.active
            sheet.append([*IDENTITY, None, *self.config["columns"]])
            for record in self.config["records"]:
                sheet.append([*record["identity"], None, *record["values"]])
            path = Path(directory) / "labels.xlsx"
            table.save(path)
            imported = import_excel(path)
            self.window.group_controls.change("mark2", imported)
            self.window.run_analysis()
            combo = self.window.metrics_group_combo
            combo.setCurrentIndex(combo.findData("Wafer"))
            self.assertEqual(combo.currentText(), "Mark2 · Wafer")
            self.assertEqual(self.window.plot_groups["CD"]["wafer_summary"]["Wafer"].tolist(), ["Pool", "Other"])
            self.window._wafer_checked("CD", 0, True)
            saved = self.window.save_workbook(Path(directory) / "grouped.mwkb")
            reopened = MatchingWindow()
            reopened.document.force_close = True
            try:
                reopened.load_workbook(saved)
                self.assertEqual(reopened.metrics_group_combo.currentData(), "Wafer")
                self.assertEqual(reopened.metrics_group_combo.itemData(0), None)
                self.assertEqual(reopened.plot_groups["CD"]["wafer_summary"]["Wafer"].tolist(), ["Pool", "Other"])
                self.assertTrue(reopened.plot_groups["CD"]["wafer_model"].frame["Draw"].iloc[0])
                self.assertFalse(reopened.document.is_dirty())
                self.window.metrics_group_combo.setCurrentIndex(self.window.metrics_group_combo.findData("Product"))
                self.window.document.recovery_path = Path(directory) / "recovery.mwkb"
                self.window.document.write_recovery()
                reopened.document.recover(self.window.document.recovery_path)
                self.assertEqual(reopened.metrics_group_combo.currentData(), "Product")
                reopened.metrics_group_combo.setCurrentIndex(0)
                self.assertTrue(reopened.plot_groups["CD"]["wafer_summary"]["Wafer"].iloc[0].startswith("W1"))
            finally:
                reopened.close()
                reopened.deleteLater()

    def test_spectra_info_uses_id_aligned_reference_and_keeps_unmatched_raw(self):
        viewer = self.open_spectra()
        info = viewer.spectra_info()
        self.assertEqual(info.issues, ())
        self.assertEqual(info.source_rows, tuple(range(6)))
        self.assertEqual(info.with_flags["REF CD"].tolist(), ["3.0000", "5.0000", "7.0000", "9.0000", "11.0000", ""])
        self.assertEqual(info.with_flags["Ref Die"].tolist(), ["1", "2", "3", "1", "2", ""])
        window = viewer.open_spectra_info()
        self.assertEqual(window.problems, ())
        self.assertEqual(window.table_frame()["REF CD"].tolist(), info.with_flags["REF CD"].tolist())
        pd.testing.assert_frame_equal(self.window.reference_model.document_frame(), self.ref)

    def test_selection_script_and_copy_to_spectra_use_aligned_reference_filter_context(self):
        config = deepcopy(self.window.group_controls.state["data_selection"])
        config["excluded"] = [config["records"][i]["id"] for i in (1, 5)]
        config.update(view_filter_groups=[[{"column": "Reference / REF CD", "minimum": 8}]],
                      view_filter_row_bools=[[]], view_filter_group_bools=[], view_show="filtered",
                      view_search="", hide_excluded=True)
        for state in (self.window.group_controls.state, self.window.group_controls.state["applied"]):
            state["data_selection"] = deepcopy(config)
        self.window.group_controls.refresh()
        self.window.run_analysis(apply_groups=False)
        script = json.loads(self.window.selection_script())
        self.assertEqual([r["values"]["Reference / REF CD"] for r in script["records"]],
                         ["3.0000", "5.0000", "7.0000", "9.0000", "11.0000", ""])
        self.assertEqual([r["use"] for r in script["records"]], [True, False, True, True, True, False])
        viewer = self.open_spectra()
        self.assertTrue(viewer.copy_wkb_selection())
        self.assertEqual({s.key for s in viewer.checked_spectra()}, {self.spectra[i].key for i in (0, 2, 3, 4)})
        self.assertEqual(viewer._data_selection_view["filters"], config["view_filter_groups"])
        self.assertEqual(viewer.spectra_info().with_flags["REF CD"].tolist(), ["3.0000", "7.0000", "9.0000", "11.0000"])

    def test_reference_more_rows_than_raw_does_not_extend_flags_or_prevent_selection(self):
        extra = pd.DataFrame({"Ref Wafer": ["unused", "unused", "unused"], "Ref Die": ["7", "8", "9"],
                              "REF CD": ["17.0000", "19.0000", "21.0000"]})
        self.window.set_reference_frame(pd.concat([self.ref, extra], ignore_index=True))
        self.window.run_analysis()
        script = json.loads(self.window.selection_script())
        self.assertEqual(len(script["records"]), len(self.raw))
        errors = []

        def inspect_dialog():
            dialog = APP.activeModalWidget()
            try:
                self.assertEqual(len(dialog.plan.order_frame), len(self.raw))
                self.assertEqual(len(dialog.plan.reference), len(self.raw))
            except Exception as error:
                errors.append(error)
            finally:
                dialog.reject()

        QTimer.singleShot(0, inspect_dialog)
        self.window.select_analysis_data()
        self.assertEqual(errors, [])
        viewer = self.open_spectra()
        self.assertEqual(viewer.spectra_info().with_flags["REF CD"].tolist(),
                         ["3.0000", "5.0000", "7.0000", "9.0000", "11.0000", ""])


if __name__ == "__main__":
    unittest.main()
