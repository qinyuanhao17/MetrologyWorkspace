"""Measurement grouping, paired filters and calibration through public interfaces."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from metrology_app.matching import MatchWorkbook, ParameterMapping
from metrology_app.match_groups import GroupPlan, group_state, row_ids


class MatchGroupTests(unittest.TestCase):
    def test_mark_alone_groups_without_test_flags(self):
        """Mark still forms Old/New groups when no TestFlag was entered."""
        raw = pd.DataFrame({"Wafer ID": ["W1"] * 4, "P": [1., 2., 3., 4.]})
        plan = GroupPlan(raw, pd.DataFrame({"TestFlag": [""] * 4}),
                         {"enabled": True, "mark_enabled": True})
        self.assertTrue(plan.enabled)
        self.assertEqual(plan.group_keys, ("Old:",))
        self.assertEqual(plan.rows("Old:"), tuple(range(4)))
        self.assertEqual(plan.label("Old:"), "Old")

        marked = GroupPlan(raw, pd.DataFrame({"TestFlag": [""] * 4}),
                           {"enabled": True, "mark_enabled": True,
                            "new_rows": row_ids(raw)[2:]})
        self.assertEqual(marked.group_keys, ("Old:", "New:"))
        self.assertEqual(marked.rows("New:"), (2, 3))
        self.assertEqual(marked.label("New:"), "New")

    def test_without_test_flags_and_mark_there_are_no_groups(self):
        """Neither TestFlag nor Mark leaves the workbook ungrouped."""
        raw = pd.DataFrame({"Wafer ID": ["W1"] * 3, "P": [1., 2., 3.]})
        plan = GroupPlan(raw, pd.DataFrame({"TestFlag": [""] * 3}),
                         {"enabled": True, "mark_enabled": False})
        self.assertFalse(plan.enabled)
        self.assertEqual(plan.group_keys, ())
        self.assertEqual(plan.plot_group_keys, ())

    def test_order_table_shows_mark_names_in_the_group_column_without_test_flags(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.match_group_ui import GroupControls
        app = QApplication.instance() or QApplication([])
        controls = GroupControls()
        ref, raw, _ = self.frames()
        try:
            controls.restore({"enabled": True, "mark_enabled": True,
                              "mark_values": [{"id": "Old", "name": "Old"},
                                              {"id": "New", "name": "New"}],
                              "mark_rows": {"New": row_ids(raw)[3:]}},
                             pd.DataFrame({"TestFlag": [""] * len(raw)}))
            controls.set_sources(ref, raw)
            model = controls.order_model
            self.assertEqual([model.data(model.index(row, 2)) for row in range(1, 7)],
                             ["Old", "Old", "Old", "New", "New", "New"])
            self.assertEqual([model.data(model.index(row, 3)) for row in range(1, 7)],
                             ["Old", "Old", "Old", "New", "New", "New"])
        finally:
            controls.deleteLater()
            app.processEvents()

    def test_removed_table_trend_order_loads_as_original_row_order(self):
        """Workbooks saved with the removed choice keep a defined order."""
        self.assertEqual(group_state({"enabled": True, "trend_order": "table"})["trend_order"], "original")
        self.assertEqual(group_state({"enabled": True, "trend_order": "nonsense"})["trend_order"], "groups")
        self.assertEqual(group_state({"enabled": True, "trend_order": "original"})["trend_order"], "original")

    def test_tem_supports_head_and_mark_groups(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        window.document.confirm_close = lambda: True
        try:
            ref, raw, flags = self.frames()
            window.match_type.setCurrentText("TEM")
            window.set_reference_frame(ref)
            window.set_raw_frame(raw)
            window.group_controls.restore({"enabled": True, "mark_enabled": True}, flags)
            window.run_analysis()
            self.assertEqual(window.result.group_plan.group_keys, ("Old:0", "Old:1"))
            self.assertTrue(window.group_settings_action.isEnabled())
            self.assertFalse(window.order_card.isHidden())
            # TEM uses the classification but keeps neither result tab.
            self.assertEqual(window.results_tabs.indexOf(window.group_plot_page), -1)
            self.assertEqual(window.results_tabs.indexOf(window.wafer_groups_widget), -1)
            window.match_type.setCurrentText("NOVA")
            self.assertGreaterEqual(window.results_tabs.indexOf(window.group_plot_page), 0)
            self.assertGreaterEqual(window.results_tabs.indexOf(window.wafer_groups_widget), 0)
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_groups_and_mark_start_unchecked_for_every_match_type(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        for match_type in ("KLA", "NOVA", "TEM"):
            window = MatchingWindow()
            window.document.confirm_close = lambda: True
            try:
                ref, raw, _flags = self.frames()
                raw = raw.assign(TestFlag=[0, 0, 0, 1, 1, 1])
                window.match_type.setCurrentText(match_type)
                self.assertFalse(window.group_controls.enabled.isChecked(), match_type)
                self.assertFalse(window.group_controls.mark_enabled.isChecked(), match_type)
                window.set_reference_frame(ref)
                window.set_raw_frame(raw)
                self.assertFalse(window.group_controls.enabled.isChecked(), match_type)
                self.assertFalse(window.group_controls.mark_enabled.isChecked(), match_type)
            finally:
                window.close()
                window.deleteLater()
                app.processEvents()

    def test_group_dialogs_show_controls_without_persistent_usage_prose(self):
        """Explanatory paragraphs are gone; counts and validation stay visible."""
        from PyQt6.QtWidgets import QApplication, QLabel
        from metrology_app.data_selection import DataSelectionDialog
        from metrology_app.match_group_ui import CombinedGroupDialog
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        window.document.confirm_close = lambda: True
        dialogs = []
        try:
            ref, raw, flags = self.frames()
            window.set_reference_frame(ref)
            window.set_raw_frame(raw)
            window.group_controls.restore({"enabled": True, "mark_enabled": True}, flags)
            window.run_analysis()

            settings_text = " ".join(
                label.text() for label in window.group_settings_dialog.findChildren(QLabel))
            self.assertNotIn("Shared by Preview and Final", settings_text)
            self.assertIn("paired rows", settings_text)

            manager = CombinedGroupDialog(window.result.group_plan, window)
            dialogs.append(manager)
            manager_text = " ".join(label.text() for label in manager.findChildren(QLabel))
            self.assertNotIn("Select at least two base Groups", manager_text)
            self.assertNotIn("double-click its name", manager_text)

            selection = DataSelectionDialog(window.result.group_plan, window)
            dialogs.append(selection)
            selection_text = " ".join(label.text() for label in selection.findChildren(QLabel))
            self.assertNotIn("Use controls participation", selection_text)
            self.assertIn("participating", selection_text)
        finally:
            for dialog in dialogs:
                dialog.deleteLater()
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_original_row_order_marks_wafer_boundaries_not_identity_runs(self):
        """Lot changes inside one wafer must not draw extra Trend boundaries."""
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        window.document.confirm_close = lambda: True
        try:
            window.set_reference_frame(pd.DataFrame({"P Reference": [2., 4., 6., 8., 10., 12.]}))
            window.set_raw_frame(pd.DataFrame({
                "Wafer ID": ["W1", "W1", "W1", "W2", "W2", "W2"],
                "Lot ID": ["L1", "L2", "L1", "L3", "L4", "L3"],
                "Die Seq": [1, 2, 3, 1, 2, 3], "P": [1., 2., 3., 4., 5., 6.]}))
            window.group_controls.restore(
                {"enabled": True, "mark_enabled": False,
                 "identity_columns": ["Wafer ID", "Lot ID"], "trend_order": "original"},
                pd.DataFrame({"TestFlag": [0] * 6}))
            window.run_analysis()
            for block in (window.plot_groups["P"], window.group_plot_page.plot_groups[("All:0", "P")]):
                plot = block["plots"]["trend"]
                self.assertEqual([line.value() for line in plot._group_boundaries], [3.5])
                self.assertTrue(all("Wafer boundary" in line.toolTip() for line in plot._group_boundaries))
                self.assertEqual(plot.getAxis("bottom").labelText, "Die Seq")
                self.assertFalse(plot._group_axis.isVisible())
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_mark_names_apply_to_plots_and_disabling_mark_merges_filtered_groups(self):
        import pyqtgraph as pg
        from PyQt6.QtCore import QCoreApplication, QEvent, QTimer
        from PyQt6.QtWidgets import QApplication, QTreeWidget
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        window.document.confirm_close = lambda: True
        ref, raw, flags = self.frames()
        flags.iloc[:, 0] = 0
        errors = []
        try:
            window.set_reference_frame(ref)
            window.set_raw_frame(raw)
            window.group_controls.restore({"enabled": True, "mark_enabled": True,
                "head_names": {"0": "Head A"}, "new_rows": row_ids(raw)[3:], "use_group_card": True,
                "filters": [{"table": "order", "column": "Group", "values": ["Old Head A"]}]}, flags)
            window.run_analysis()
            window.group_settings_action.trigger()
            self.assertTrue(window.group_settings_dialog.isVisible())

            def rename():
                dialog = app.activeModalWidget()
                try:
                    values = dialog.findChild(QTreeWidget, "markValues")
                    values.topLevelItem(0).setText(0, "Previous run")
                    values.topLevelItem(1).setText(0, "Current run")
                    dialog.accept()
                except Exception as error:
                    errors.append(error)
                    dialog.reject()

            QTimer.singleShot(0, rename)
            window.group_controls.new_button.click()
            self.assertEqual(errors, [])
            window.group_controls.apply_button.click()
            app.processEvents()
            self.assertEqual(window.plot_groups["P"]["wafer_model"].frame["Group"].tolist(), ["Previous run Head A"])
            axis = window.plot_groups["P"]["plots"]["trend"]._group_axis
            self.assertEqual(axis._tickLevels[0][0][1], "Previous run\nHead A")
            window.group_controls.mark_enabled.setChecked(False)
            window.group_controls.apply_button.click()
            app.processEvents()
            self.assertFalse(window.group_controls.pending)
            self.assertEqual(window.plot_groups["P"]["wafer_model"].frame["Group"].tolist(), ["Head A", "Head A"])
            page = window.group_plot_page
            self.assertEqual(list(page.scopes), ["All:0"])
            trend = page.plot_groups[("All:0", "P")]["plots"]["trend"]
            values = np.concatenate([curve.yData for curve in trend.listDataItems()
                                     if curve.name() == "PMISH" or curve.name() is None])
            np.testing.assert_allclose(values, [5.5, 8., 10.5, 5.5, 8., 10.5])
            window.group_controls.mark_enabled.setChecked(True)
            window.group_controls.apply_button.click()
            app.processEvents()
            self.assertEqual(window.plot_groups["P"]["wafer_model"].frame["Group"].tolist(), ["Previous run Head A"])
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            trend = page.plot_groups[("Old:0", "P")]["plots"]["trend"]
            values = np.concatenate([curve.yData for curve in trend.listDataItems()
                                     if curve.name() == "PMISH"])
            np.testing.assert_allclose(values, [3., 5., 7.])
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_mark_is_optional_and_custom_names_replace_age_in_the_tables(self):
        from PyQt6.QtCore import Qt, QTimer
        from PyQt6.QtWidgets import QApplication, QComboBox, QLineEdit, QPushButton, QTreeWidget
        from metrology_app.match_group_ui import GroupControls
        app = QApplication.instance() or QApplication([])
        controls = GroupControls()
        ref, raw, flags = self.frames()
        errors = []
        try:
            self.assertFalse(controls.mark_enabled.isChecked())
            controls.restore({"enabled": True, "mark_enabled": False,
                              "head_names": {"0": "Head A", "1": "Head B"}}, flags)
            controls.set_sources(ref, raw)
            self.assertEqual(controls.order_model.data(controls.order_model.index(0, 2)), "Mark")
            self.assertEqual(controls.order_model.data(controls.order_model.index(1, 2)), "")
            self.assertEqual(controls.order_model.data(controls.order_model.index(1, 3)), "Head A")
            self.assertFalse(controls.new_button.isEnabled())
            controls.mark_enabled.setChecked(True)
            self.assertEqual(controls.new_button.text(), "Marks…")
            self.assertTrue(controls.new_button.isEnabled())

            def customize_marks():
                dialog = app.activeModalWidget()
                try:
                    values = dialog.findChild(QTreeWidget, "markValues")
                    self.assertEqual(
                        [values.topLevelItem(i).text(0) for i in range(values.topLevelItemCount())],
                        ["Old", "New"],
                    )
                    self.assertFalse(values.topLevelItem(0).icon(1).isNull())
                    self.assertTrue(values.topLevelItem(1).icon(1).isNull())
                    values.topLevelItem(0).setText(0, "Previous")
                    values.topLevelItem(1).setText(0, "Current")
                    buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
                    self.assertIn("Assign Visible", buttons)
                    dialog.findChild(QLineEdit, "markSearch").setText("L2")
                    dialog.findChild(QComboBox, "markVisible").setCurrentText("Current")
                    buttons["Assign Visible"].click()
                    table = dialog.findChild(QTreeWidget, "markAssignments")
                    self.assertEqual(table.topLevelItemCount(), 2)
                    self.assertTrue(table.topLevelItem(0).isHidden())
                    self.assertEqual(table.itemWidget(table.topLevelItem(1), 1).currentText(), "Current")
                    dialog.accept()
                except Exception as error:
                    errors.append(error)
                    dialog.reject()

            QTimer.singleShot(0, customize_marks)
            controls.new_button.click()
            self.assertEqual(errors, [])
            self.assertEqual(controls.order_model.data(controls.order_model.index(1, 2)), "Previous")
            self.assertEqual(controls.order_model.data(controls.order_model.index(4, 2)), "Current")
            self.assertEqual(controls.order_model.data(controls.order_model.index(4, 3)), "Current Head B")
            marked = controls.state["mark_rows"]["New"][:]
            controls.mark_enabled.setChecked(False)
            self.assertEqual(controls.order_model.data(controls.order_model.index(4, 2)), "")
            self.assertEqual(controls.order_model.data(controls.order_model.index(4, 3)), "Head B")
            controls.mark_enabled.setChecked(True)
            self.assertEqual(controls.order_model.data(controls.order_model.index(4, 2)), "Current")
            self.assertEqual(controls.state["mark_rows"]["New"], marked)
        finally:
            controls.deleteLater()
            app.processEvents()

    def test_order_starts_blank_and_has_only_paired_input_rows(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.match_group_ui import GroupControls
        app = QApplication.instance() or QApplication([])
        controls = GroupControls()
        try:
            self.assertEqual(controls.order_model.rowCount(), 2)
            self.assertFalse(controls.names_button.isEnabled())
            ref, raw, _ = self.frames()
            controls.set_sources(ref, raw)
            model = controls.order_model
            model.replace_matrix([["TestFlag", "", "", ""]] + [["", "", "", ""]] * 100)
            self.assertEqual(model.rowCount(), 7)
            self.assertEqual([model.data(model.index(1, c)) for c in range(4)], ["", "", "", ""])
            self.assertFalse(controls.names_button.isEnabled())
            model.edit({(2, 0): "1"})
            self.assertEqual([model.data(model.index(2, c)) for c in range(4)],
                             ["1", "", "", ""])
            controls.enabled.setChecked(True)
            self.assertEqual([model.data(model.index(2, c)) for c in range(4)],
                             ["1", "TestFlag 1", "", "TestFlag 1"])
            self.assertEqual(model.data(model.index(1, 1)), "")
            model.undo.undo()
            self.assertEqual(model.data(model.index(2, 1)), "")
            self.assertFalse(controls.names_button.isEnabled())
            controls.mark_enabled.setChecked(True)
            self.assertEqual(model.data(model.index(1, 2)), "Old")
        finally:
            controls.deleteLater()
            app.processEvents()

    def test_head_names_dialog_uses_only_entered_flags_and_retains_saved_names(self):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit
        from metrology_app.match_group_ui import GroupControls
        app = QApplication.instance() or QApplication([])
        controls = GroupControls()
        seen = []
        def confirm():
            dialog = app.activeModalWidget()
            seen.append(([label.text() for label in dialog.findChildren(QLabel)],
                         [field.text() for field in dialog.findChildren(QLineEdit)]))
            dialog.findChildren(QLineEdit)[0].setText("Renamed head")
            dialog.accept()
        try:
            ref, raw, _ = self.frames()
            controls.set_sources(ref, raw)
            controls.restore({"head_names": {"0": "Saved zero", "1": "Saved one", "-1": "Saved unknown"}},
                             pd.DataFrame({"TestFlag": [1, "", 1]}))
            QTimer.singleShot(0, confirm)
            controls.names_button.click()
            self.assertEqual(seen, [(["TestFlag 1"], ["Saved one"])])
            self.assertEqual(controls.state["head_names"],
                             {"0": "Saved zero", "1": "Renamed head", "-1": "Saved unknown"})
            controls.order_model.edit({(4, 0): "-1"})
            QTimer.singleShot(0, confirm)
            controls.names_button.click()
            self.assertEqual(seen[-1], (["TestFlag 1", "TestFlag -1"], ["Renamed head", "Saved unknown"]))
            controls.restore({"head_names": {"2": "Head two", "25": "Head twenty-five"}},
                             pd.DataFrame({"TestFlag": ["2", "25"]}))
            QTimer.singleShot(0, confirm)
            controls.names_button.click()
            self.assertEqual(seen[-1], (["TestFlag 2", "TestFlag 25"], ["Head two", "Head twenty-five"]))
        finally:
            controls.deleteLater()
            app.processEvents()

    def test_user_can_fix_name_collision_after_a_flag_reappears(self):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication, QLineEdit
        from metrology_app.match_group_ui import GroupControls
        app = QApplication.instance() or QApplication([])
        controls = GroupControls()
        def confirm():
            dialog = app.activeModalWidget()
            for field, name in zip(dialog.findChildren(QLineEdit), ["Head A", "Head B"]):
                field.setText(name)
            dialog.accept()
        try:
            ref, raw, _ = self.frames()
            controls.set_sources(ref, raw)
            controls.restore({"head_names": {"0": "Same", "1": "Same"}},
                             pd.DataFrame({"TestFlag": [1]}))
            controls.order_model.edit({(2, 0): "0"})
            self.assertFalse(controls.apply_button.isEnabled())
            self.assertTrue(controls.names_button.isEnabled())
            QTimer.singleShot(0, confirm)
            controls.names_button.click()
            self.assertTrue(controls.apply_button.isEnabled())
        finally:
            controls.deleteLater()
            app.processEvents()

    def frames(self):
        raw = pd.DataFrame({"Wafer ID": ["W1"] * 3 + ["W1"] * 3,
                            "Lot ID": ["L1"] * 3 + ["L2"] * 3,
                            "PAD Name": ["ARRAY"] * 6,
                            "Die Seq": [1, 2, 3, 1, 2, 3],
                            "P": [1., 2., 3., 1., 2., 3.]})
        ref = pd.DataFrame({"P Reference": [3., 5., 7., 8., 11., 14.]})
        flags = pd.DataFrame({"TestFlag": [0, 0, 0, 1, 1, 1]})
        return ref, raw, flags

    def test_named_heads_filter_the_same_reference_and_raw_records(self):
        ref, raw, flags = self.frames()
        state = {"enabled": True, "head_names": {"0": "Head A", "1": "Head B", "-1": "Unknown"},
                 "filters": [{"table": "order", "column": "TestFlag", "values": ["1"]}],
                 "sort": [{"table": "raw", "column": "P", "descending": True}]}
        book = MatchWorkbook(ref, raw, [ParameterMapping("P", "P Reference", "P")],
                             test_flags=flags, grouping_state=state)
        result = book.analyze()
        self.assertAlmostEqual(result.card("P").slope, 3.)
        self.assertAlmostEqual(result.card("P").intercept, 5.)
        self.assertEqual(result.series("P")["Reference"].tolist(), [8., 11., 14.])
        self.assertEqual(result.group_plan.display_rows, (5, 4, 3))
        self.assertEqual(result.group_summary("P")["Group"].tolist(), ["Head B"])

    def test_group_card_never_changes_sources_and_survives_save(self):
        ref, raw, flags = self.frames()
        book = MatchWorkbook(ref, raw, [ParameterMapping("P", "P Reference", "P")],
                             test_flags=flags, grouping_state={"enabled": True,
                             "new_rows": list(row_ids(raw)[3:]), "use_group_card": True})
        result = book.analyze()
        self.assertAlmostEqual(result.group_card("P", "Old:0").slope, 2.)
        self.assertAlmostEqual(result.group_card("P", "New:1").slope, 3.)
        np.testing.assert_allclose(result.group_series("P", trend=True, card_mode="group")["Trend value"], ref.iloc[:, 0])
        pd.testing.assert_frame_equal(book.raw, raw)
        with tempfile.TemporaryDirectory() as directory:
            book.save(Path(directory) / "groups.wkb")
            restored = MatchWorkbook.load(Path(directory) / "groups.wkb")
            pd.testing.assert_frame_equal(restored.raw, raw)
            self.assertEqual(restored.analyze().group_plan.group_keys, ("Old:0", "New:1"))

    def test_unavailable_group_card_leaves_a_gap_without_overall_fallback(self):
        ref, raw, flags = self.frames()
        flags.loc[5, "TestFlag"] = -1
        result = MatchWorkbook(ref, raw, [ParameterMapping("P", "P Reference", "P")],
                               test_flags=flags, grouping_state={"enabled": True}).analyze()
        self.assertIsNone(result.group_card("P", "Old:-1"))
        self.assertTrue(result.group_series("P", "Old:-1", card_mode="group")["Trend value"].isna().all())
        self.assertEqual(result.group_summary("P").iloc[-1]["Valid pairs"], 1)

    def test_invalid_flag_is_rejected_but_blank_is_not_unknown(self):
        ref, raw, flags = self.frames()
        flags.loc[0, "TestFlag"] = ""
        plan = GroupPlan(raw, flags, {"enabled": True}, ref)
        self.assertEqual(plan.head(plan.flags[0]), "Not provided")
        flags.loc[0, "TestFlag"] = "not a number"
        with self.assertRaisesRegex(ValueError, "Invalid TestFlag"):
            GroupPlan(raw, flags, {"enabled": True}, ref)

    def test_arbitrary_numeric_flags_form_named_groups_and_survive_save(self):
        ref, raw, _ = self.frames()
        flags = pd.DataFrame({"TestFlag": ["2", "2.0", "2", "-3", "-3.0", "-3"]})
        book = MatchWorkbook(ref, raw, [ParameterMapping("P", "P Reference", "P")],
                             test_flags=flags, grouping_state={"enabled": True,
                             "head_names": {"2": "Head C", "-3": "Head D"},
                             "group_order": ["Old:0", "Old:1", "Old:-1", "Old:",
                                             "New:0", "New:1", "New:-1", "New:"],
                             "new_rows": list(row_ids(raw)[3:])})
        result = book.analyze()
        self.assertEqual(result.group_plan.group_keys, ("Old:2", "New:-3"))
        self.assertEqual(result.group_summary("P")["Group"].tolist(), ["Old Head C", "New Head D"])
        self.assertAlmostEqual(result.group_card("P", "Old:2").slope, 2.)
        self.assertAlmostEqual(result.group_card("P", "New:-3").slope, 3.)
        with tempfile.TemporaryDirectory() as directory:
            book.save(Path(directory) / "numeric-flags.wkb")
            loaded = MatchWorkbook.load(Path(directory) / "numeric-flags.wkb").analyze()
            self.assertEqual(loaded.group_plan.label("New:-3"), "New Head D")
        from metrology_app.match_groups import flag_value
        self.assertEqual(flag_value("9007199254740993"), "9007199254740993")
        for value in ("2.5", "-3.2", "NaN", "inf", "-Infinity"):
            with self.assertRaises(ValueError):
                flag_value(value)

    def test_final_does_not_share_flags_by_equal_row_count(self):
        ref, raw, flags = self.frames()
        final = raw.copy()
        final.loc[0, "Lot ID"] = "other"
        book = MatchWorkbook(ref, raw, [ParameterMapping("P", "P Reference", "P")],
                             final_match_raw=final, result_mode="final", test_flags=flags,
                             grouping_state={"enabled": True})
        with self.assertRaisesRegex(ValueError, "identities differ"):
            book.analyze()

    def test_regrouping_does_not_split_repeated_die_or_lose_missing_identity(self):
        ref, raw, flags = self.frames()
        raw.loc[5, "Wafer ID"] = ""
        plan = GroupPlan(raw, flags, {"enabled": True, "identity_columns": ["Wafer ID"]}, ref)
        self.assertEqual([len(m.rows) for m in plan.measurements], [5, 1])
        self.assertEqual(sum(len(s["rows"]) for s in plan.trend_spans()), 6)

    def test_filtered_table_edits_and_undo_map_to_source(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.sheet import SheetModel
        from metrology_app.match_group_ui import ProjectedSheetModel
        app = QApplication.instance() or QApplication([])
        source = SheetModel()
        source.load(pd.DataFrame({"P": [1, 2, 3, 4, 5, 6]}))
        proxy = ProjectedSheetModel(source)
        proxy.set_rows((5, 4, 3))
        proxy.edit({(1, 0): "99"})
        self.assertEqual(source.cells[(6, 0)], "99")
        source.undo.undo()
        self.assertEqual(proxy.data(proxy.index(1, 0)), "6")
        app.processEvents()

    def test_projected_value_edit_preserves_table_scroll(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.sheet import SheetModel, SheetView
        from metrology_app.match_group_ui import ProjectedSheetModel
        app = QApplication.instance() or QApplication([])
        source = SheetModel()
        source.load(pd.DataFrame({"P": list(range(300))}))
        proxy = ProjectedSheetModel(source)
        proxy.set_rows(tuple(range(299, -1, -1)))
        view = SheetView(source)
        view.setModel(proxy)
        view.resize(500, 250)
        view.show()
        app.processEvents()
        view.verticalScrollBar().setValue(100)
        source.edit({(150, 0): "150.01"})
        app.processEvents()
        self.assertEqual(view.verticalScrollBar().value(), 100)
        view.close()
        view.deleteLater()
        app.processEvents()

    def test_new_marks_survive_collapsed_grouping_as_partial(self):
        from PyQt6.QtCore import Qt, QTimer
        from PyQt6.QtWidgets import QApplication, QMenu, QTreeWidget
        from metrology_app.match_group_ui import GroupControls
        app = QApplication.instance() or QApplication([])
        controls = GroupControls()
        ref, raw, flags = self.frames()
        controls.restore({"enabled": True}, flags)
        controls.set_sources(ref, raw)
        errors = []

        def choose_new():
            try:
                dialog = app.activeModalWidget()
                table = dialog.findChild(QTreeWidget, "markAssignments")
                self.assertEqual(table.topLevelItemCount(), 2)
                table.itemWidget(table.topLevelItem(1), 1).setCurrentText("New")
                dialog.accept()
            except Exception as error:
                errors.append(error)
                app.activeModalWidget().reject()

        QTimer.singleShot(0, choose_new)
        controls.mark_new()
        self.assertEqual(errors, [])
        assignments = list(controls.state["mark_rows"]["New"])
        self.assertEqual(len(assignments), 3)

        def collapse():
            try:
                dialog = app.activeModalWidget()
                menu = dialog.findChild(QMenu)
                next(action for action in menu.actions() if action.text() == "Lot ID").setChecked(False)
                table = dialog.findChild(QTreeWidget, "markAssignments")
                self.assertEqual(table.topLevelItemCount(), 1)
                dialog.accept()
            except Exception as error:
                errors.append(error)
                app.activeModalWidget().reject()

        QTimer.singleShot(0, collapse)
        controls.mark_new()
        self.assertEqual(errors, [])
        self.assertEqual(controls.state["mark_rows"]["New"], assignments)
        controls.deleteLater()
        app.processEvents()

    def test_mark_assignment_rows_stay_separated_and_the_picker_marks_wafers(self):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication, QTreeWidget
        from metrology_app.match_group_ui import GroupControls
        from metrology_app.settings import theme_stylesheet
        app = QApplication.instance() or QApplication([])
        controls = GroupControls()
        ref, raw, flags = self.frames()
        controls.restore({"enabled": True}, flags)
        controls.set_sources(ref, raw)
        errors = []
        def select_mark():
            dialog = app.activeModalWidget()
            try:
                table = dialog.findChild(QTreeWidget, "markAssignments")
                app.processEvents()
                first = table.visualItemRect(table.topLevelItem(0))
                second = table.visualItemRect(table.topLevelItem(1))
                self.assertGreater(second.top(), first.top())
                self.assertGreaterEqual(second.height(), 22)
                combo = table.itemWidget(table.topLevelItem(1), 1)
                self.assertEqual(combo.currentText(), "Old")
                combo.setCurrentText("New")
                dialog.accept()
            except Exception as error:
                errors.append(error)
                dialog.reject()
        try:
            for theme in ("light", "dark"):
                controls.setStyleSheet(theme_stylesheet(theme))
                controls.change("mark_rows", {})
                QTimer.singleShot(0, select_mark)
                controls.mark_new()
                self.assertEqual(errors, [])
                self.assertEqual(len(controls.state["mark_rows"]["New"]), 3)
        finally:
            controls.deleteLater()
            app.processEvents()

    def test_mark_new_whole_row_and_shift_range_skip_filtered_rows(self):
        from PyQt6.QtCore import Qt, QTimer
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication, QLineEdit, QTreeWidget
        from metrology_app.match_group_ui import GroupControls
        app = QApplication.instance() or QApplication([])
        controls = GroupControls()
        ref, raw, flags = self.frames()
        raw["Wafer ID"] = ["Keep1", "Hidden", "Keep2", "Keep3", "Keep4", "Keep5"]
        controls.restore({"enabled": True, "identity_columns": ["Wafer ID"]}, flags)
        controls.set_sources(ref, raw)
        errors = []
        def select_range():
            dialog = app.activeModalWidget()
            try:
                table = dialog.findChild(QTreeWidget, "markAssignments")
                def picker(row):
                    return table.itemWidget(table.topLevelItem(row), 1)
                def chosen():
                    return [picker(i).currentText() for i in range(table.topLevelItemCount())]
                def click(row, modifiers=Qt.KeyboardModifier.NoModifier):
                    item = table.topLevelItem(row)
                    table.scrollToItem(item)
                    app.processEvents()
                    rect = table.visualItemRect(item)
                    QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, modifiers,
                                     rect.center())
                picker(0).setCurrentText("New")
                click(0)
                click(3, Qt.KeyboardModifier.ShiftModifier)
                self.assertEqual(chosen(), ["New", "New", "New", "New", "Old", "Old"])
                dialog.findChild(QLineEdit, "markSearch").setText("Keep")
                picker(0).setCurrentText("Old")
                click(0)
                click(5, Qt.KeyboardModifier.ShiftModifier)
                self.assertEqual(chosen(), ["Old", "New", "Old", "Old", "Old", "Old"])
                dialog.accept()
            except Exception as error:
                errors.append(error)
                dialog.reject()
        try:
            QTimer.singleShot(0, select_range)
            controls.mark_new()
            self.assertEqual(errors, [])
            self.assertEqual(controls.state["mark_rows"]["New"], [row_ids(raw)[1]])
        finally:
            controls.deleteLater()
            app.processEvents()

    def test_deleting_a_used_mark_moves_its_wafers_to_the_first_mark(self):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication, QPushButton, QTreeWidget
        from metrology_app.match_group_ui import GroupControls
        app = QApplication.instance() or QApplication([])
        controls = GroupControls()
        ref, raw, flags = self.frames()
        errors = []

        def drop_new():
            dialog = app.activeModalWidget()
            try:
                values = dialog.findChild(QTreeWidget, "markValues")
                values.setCurrentItem(values.topLevelItem(1))
                buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
                self.assertIn("Delete Mark", buttons)
                buttons["Delete Mark"].click()
                dialog.accept()
            except Exception as error:
                errors.append(error)
                dialog.reject()

        try:
            controls.restore({"enabled": True,
                              "mark_values": [{"id": "Old", "name": "Old"},
                                              {"id": "New", "name": "New"}],
                              "mark_rows": {"New": row_ids(raw)[3:]}}, flags)
            controls.set_sources(ref, raw)
            QTimer.singleShot(0, drop_new)
            controls.mark_new()
            self.assertEqual(errors, [])
            self.assertEqual(controls.state["mark_values"], [{"id": "Old", "name": "Old"}])
            self.assertEqual(controls.state["mark_rows"], {})
            self.assertEqual([controls.order_model.data(controls.order_model.index(row, 2))
                              for row in (1, 2)], ["Old", "Old"])
        finally:
            controls.deleteLater()
            app.processEvents()

    def test_renaming_an_assigned_mark_follows_in_the_assignment_picker(self):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication, QTreeWidget
        from metrology_app.match_group_ui import GroupControls
        app = QApplication.instance() or QApplication([])
        controls = GroupControls()
        ref, raw, flags = self.frames()
        errors = []

        def rename_new():
            dialog = app.activeModalWidget()
            try:
                values = dialog.findChild(QTreeWidget, "markValues")
                table = dialog.findChild(QTreeWidget, "markAssignments")
                self.assertEqual(table.itemWidget(table.topLevelItem(1), 1).currentText(), "New")
                values.topLevelItem(1).setText(0, "Current")
                self.assertEqual(table.itemWidget(table.topLevelItem(1), 1).currentText(), "Current")
                dialog.accept()
            except Exception as error:
                errors.append(error)
                dialog.reject()

        try:
            controls.restore({"enabled": True,
                              "mark_values": [{"id": "Old", "name": "Old"},
                                              {"id": "New", "name": "New"}],
                              "mark_rows": {"New": row_ids(raw)[3:]}}, flags)
            controls.set_sources(ref, raw)
            QTimer.singleShot(0, rename_new)
            controls.mark_new()
            self.assertEqual(errors, [])
            self.assertEqual(controls.state["mark_values"][1]["name"], "Current")
            self.assertEqual(controls.state["mark_rows"]["New"], list(row_ids(raw)[3:]))
        finally:
            controls.deleteLater()
            app.processEvents()

    def test_groups_menu_opens_reusable_shared_settings_without_an_inline_toolbar(self):
        from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QPushButton
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        try:
            ref, raw, flags = self.frames()
            window.set_reference_frame(ref)
            window.set_raw_frame(raw)
            window.group_controls.restore({"enabled": True, "mark_enabled": True}, flags)
            window.show()
            self.assertIn("Groups", [action.text() for action in window.menuBar().actions()])
            window.group_settings_action.trigger()
            app.processEvents()
            dialog = window.findChild(QDialog, "groupSettingsDialog")
            self.assertIsNotNone(dialog)
            self.assertTrue(dialog.isVisible())
            self.assertFalse(dialog.isModal())
            labels = [button.text() for button in dialog.findChildren(QPushButton)]
            self.assertNotIn("Import combined…", labels)
            self.assertNotIn("Clear filters / sort", labels)
            controls = window.group_controls
            self.assertLess(dialog.width(), 650)
            self.assertLess(dialog.height(), 520)
            self.assertLess(controls.names_button.y(), controls.new_button.y())
            self.assertLess(controls.new_button.y(), controls.order.y())
            self.assertLess(controls.order.y(), controls.group_order_button.y())
            self.assertEqual(controls.names_button.x(), controls.new_button.x())
            self.assertEqual(controls.names_button.x(), controls.order.x())
            self.assertEqual(controls.order.x(), controls.group_order_button.x())
            buttons = dialog.findChild(QDialogButtonBox)
            self.assertIsNotNone(buttons.button(QDialogButtonBox.StandardButton.Cancel))
            self.assertIs(window.group_controls.apply_button.parentWidget(), buttons)
            self.assertGreater(window.group_controls.apply_button.mapTo(dialog, window.group_controls.apply_button.rect().center()).y(),
                               window.group_controls.order.mapTo(dialog, window.group_controls.order.rect().center()).y())
            self.assertTrue(dialog.isAncestorOf(window.group_controls))
            self.assertFalse(window.setup_page.isAncestorOf(window.group_controls))
            window.group_controls.card.setChecked(True)
            self.assertFalse(window.group_controls.pending)
            self.assertTrue(window.group_plot_page.isAncestorOf(window.group_controls.card))
            self.assertFalse(dialog.isAncestorOf(window.group_controls.card))
            dialog.close()
            self.assertFalse(dialog.isVisible())
            self.assertTrue(window.group_controls.state["use_group_card"])
            window.result_mode.setCurrentText("Final")
            window.set_raw_frame(raw)
            window.group_settings_action.trigger()
            app.processEvents()
            self.assertIs(window.findChild(QDialog, "groupSettingsDialog"), dialog)
            self.assertTrue(window.group_controls.card.isChecked())
            window.group_controls.apply_button.click()
            self.assertFalse(window.group_controls.pending)
            # Hidden plots keep their latest logical result; opening the tab
            # materializes every Group automatically, without Select/Draw.
            window.results_tabs.setCurrentWidget(window.group_plot_page)
            app.processEvents()
            self.assertEqual(set(window.group_plot_page.plot_groups), {("Old:0", "P"), ("Old:1", "P")})
            window.match_type.setCurrentText("TEM")
            self.assertTrue(window.group_settings_action.isEnabled())
            self.assertEqual(window.results_tabs.indexOf(window.group_plot_page), -1)
            self.assertEqual(window.results_tabs.indexOf(window.wafer_groups_widget), -1)
            window.group_settings_action.trigger()
            app.processEvents()
            self.assertTrue(dialog.isVisible())
            window.match_type.setCurrentText("NOVA")
            self.assertTrue(window.group_settings_action.isEnabled())
            window.group_settings_action.trigger()
            self.assertTrue(dialog.isVisible())
            window.close()
            self.assertFalse(dialog.isVisible())
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_group_card_changes_only_group_trends_not_all_parameter_plots(self):
        import pyqtgraph as pg
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window, restored = MatchingWindow(), MatchingWindow()

        def trend_values(plots):
            return np.concatenate([
                curve.yData for plot in plots for curve in plot.listDataItems()
                if any(item.name() == "PMISH" for item in plot.listDataItems())
                and curve.name() == "PMISH"
            ])

        try:
            ref, raw, flags = self.frames()
            window.set_reference_frame(ref)
            window.set_raw_frame(raw)
            for mode in ("Preview", "Final"):
                with self.subTest(mode=mode):
                    window.result_mode.setCurrentText(mode)
                    if mode == "Final":
                        window.set_raw_frame(raw)
                    window.group_controls.restore({"enabled": True}, flags)
                    window.run_analysis()
                    window.plot_groups["P"]["plots"]["trend"].card_checkbox.setChecked(True)
                    window.group_plot_page.card.setChecked(True)
                    overall = [5.5, 8., 10.5, 5.5, 8., 10.5]
                    np.testing.assert_allclose(
                        trend_values([window.plot_groups["P"]["plots"]["trend"]]), overall,
                    )
                    np.testing.assert_allclose(
                        trend_values([block["plots"]["trend"] for block in window.group_plot_page.plot_groups.values()]), overall,
                    )
                    bias = window.plot_groups["P"]["plots"]["bias"].listDataItems()[0].yData.copy()
                    window.group_plot_page.use_group_card.setChecked(True)
                    window.group_controls.apply_button.click()
                    app.processEvents()
                    np.testing.assert_allclose(
                        trend_values([window.plot_groups["P"]["plots"]["trend"]]), overall,
                    )
                    np.testing.assert_allclose(
                        trend_values([block["plots"]["trend"] for block in window.group_plot_page.plot_groups.values()]),
                        [3., 5., 7., 8., 11., 14.],
                    )
                    np.testing.assert_allclose(
                        window.plot_groups["P"]["plots"]["bias"].listDataItems()[0].yData, bias,
                    )
                    restored.restore_workspace(window.workspace_snapshot())
                    app.processEvents()
                    self.assertTrue(restored.group_controls.card.isChecked())
                    self.assertFalse(restored.group_settings_dialog.isVisible())
                    np.testing.assert_allclose(
                        trend_values([restored.plot_groups["P"]["plots"]["trend"]]), overall,
                    )
                    np.testing.assert_allclose(
                        trend_values([block["plots"]["trend"] for block in restored.group_plot_page.plot_groups.values()]),
                        [3., 5., 7., 8., 11., 14.],
                    )
        finally:
            for item in (window, restored):
                item.close()
                item.deleteLater()
            app.processEvents()

    def test_apply_group_settings_automatically_updates_all_group_plots(self):
        from unittest.mock import patch
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        try:
            ref, raw, flags = self.frames()
            window.set_reference_frame(ref)
            window.set_raw_frame(raw)
            window.group_controls.restore({"enabled": True, "mark_enabled": True}, flags)
            window.run_analysis()
            page = window.group_plot_page
            self.assertEqual(set(page.plot_groups), {("Old:0", "P"), ("Old:1", "P")})
            window.group_settings_action.trigger()
            buttons = window.group_settings_dialog.findChildren(QPushButton)
            self.assertNotIn("Draw selected", [button.text() for button in buttons])
            apply = next((button for button in buttons if button.text() == "Apply"), None)
            self.assertIsNotNone(apply)
            window.group_controls.card.setChecked(True)
            apply.click()
            app.processEvents()
            self.assertFalse(window.group_settings_dialog.isVisible())
            window.group_settings_action.trigger()
            self.assertTrue(window.group_settings_dialog.isVisible())
            self.assertFalse(window.group_controls.pending)
            self.assertTrue(window.result.group_plan.state["use_group_card"])
            self.assertEqual(set(page.plot_groups), {("Old:0", "P"), ("Old:1", "P")})
            window.group_controls.change("filters", [{"table": "order", "column": "TestFlag", "values": ["1"]}])
            self.assertEqual(set(page.plot_groups), {("Old:0", "P"), ("Old:1", "P")})
            apply.click()
            app.processEvents()
            self.assertEqual(set(page.plot_groups), {("Old:1", "P")})
            self.assertFalse(window.group_settings_dialog.isVisible())
            window.group_settings_action.trigger()
            window.mapping_table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
            with patch.object(QMessageBox, "warning") as warning:
                apply.click()
                self.assertTrue(window.group_settings_dialog.isVisible())
                self.assertIn("Select at least one", warning.call_args.args[2])
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_all_parameter_group_axes_align_bias_and_keep_reference_above_raw(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        window.document.confirm_close = lambda: True
        try:
            ref, raw, flags = self.frames()
            window.set_reference_frame(ref)
            window.set_raw_frame(raw)
            window.percent_bias.setChecked(True)
            window.group_controls.restore({"enabled": True, "group_order": ["Old:1", "Old:0"],
                                           "mark_enabled": True,
                                           "head_names": {"0": "A", "1": "B"}}, flags)
            window.run_analysis()
            window.resize(1180, 760)
            window.show()
            app.processEvents()
            plots = window.plot_groups["P"]["plots"]
            curves = plots["trend"].listDataItems()
            reference = next(curve for curve in curves if curve.name() != "PMISH")
            raw_curves = [curve for curve in curves if curve.name() == "PMISH"]
            self.assertTrue(all(reference.zValue() > curve.zValue() for curve in raw_curves))
            np.testing.assert_allclose(reference.yData, [8., 11., 14., 3., 5., 7.])
            ordered = window.result.group_series("P", trend=True)
            for name, column in (("bias", "Bias"), ("bias-percent", "Bias %")):
                curve = plots[name].listDataItems()[0]
                np.testing.assert_allclose(curve.yData, ordered[column])
            for name in ("trend", "bias", "bias-percent"):
                plot = plots[name]
                self.assertEqual([line.value() for line in plot._group_boundaries], [3.5])
                self.assertTrue(all(line.pen.widthF() == 2 and line.zValue() > 0
                                    and line.pen.style() == Qt.PenStyle.DashLine
                                    for line in plot._group_boundaries))
                self.assertTrue(all(line.pen.color().name() == "#000000" for line in plot._group_boundaries))
                self.assertEqual(plot._group_axis.boundaries, [.5, 3.5, 6.5])
                plot.getViewBox().autoRange()
                np.testing.assert_allclose(plot.getViewBox().viewRange()[0], [.5, 6.5])
                self.assertEqual(plot._group_axis._tickLevels,
                                 [[(2., "Old\nB"), (5., "Old\nA")]])
                labels = [text for _, text in plot.getAxis("bottom")._tickLevels[0]]
                self.assertTrue(labels)
                self.assertTrue(set(labels) <= {"1", "2", "3"})
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_dense_group_axis_labels_do_not_overlap_after_resize_or_zoom(self):
        from PyQt6.QtGui import QPainter, QPicture
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        window.document.confirm_close = lambda: True
        count = 2400
        raw = pd.DataFrame({"Wafer ID": [f"W{i // 20:03}" for i in range(count)],
                            "Lot ID": ["L1"] * count, "PAD Name": ["ARRAY"] * count,
                            "Die Seq": np.arange(count) % 20 + 1,
                            "P": 60 + np.sin(np.arange(count) / 20)})
        ref = pd.DataFrame({"P Reference": raw["P"] * 1.05 + 2})
        flags = pd.DataFrame({"TestFlag": np.arange(count) // 20 % 3 - 1})
        try:
            window.set_reference_frame(ref)
            window.set_raw_frame(raw)
            window.percent_bias.setChecked(True)
            window.group_controls.restore({"enabled": True, "new_rows": row_ids(raw)[1200:],
                                           "head_names": {"0": "MM1", "1": "MM2", "-1": "Unknown"}}, flags)
            window.run_analysis()
            window.show()
            for width in (1180, 1900):
                window.resize(width, 760)
                app.processEvents()
                for name in ("trend", "bias", "bias-percent"):
                    plot = window.plot_groups["P"]["plots"][name]
                    for zoom in ((.5, count + .5), (201., 401.)):
                        plot.setXRange(*zoom, padding=0)
                        app.processEvents()
                        for axis in (plot.getAxis("bottom"), plot._group_axis):
                            picture = QPicture()
                            painter = QPainter(picture)
                            try:
                                specs = axis.generateDrawSpecs(painter)
                            finally:
                                painter.end()
                            self.assertIsNotNone(specs)
                            labels = specs[2]
                            self.assertTrue(labels, (name, width, zoom, axis._tickLevels,
                                                     plot.getViewBox().sceneBoundingRect()))
                            for rect, _, label in labels:
                                self.assertNotIn("W00", label)
                                self.assertNotIn("PAD", label)
                                self.assertNotIn("L1", label)
                            for first, second in zip(labels, labels[1:]):
                                self.assertFalse(first[0].intersects(second[0]), (name, width, labels))
                    plot.setXRange(.5, count + .5, padding=0)
            self.assertEqual(len(window.plot_groups["P"]["plots"]["trend"].listDataItems()[0].xData), count)
            window.group_controls.enabled.setChecked(False)
            window.group_controls.mark_enabled.setChecked(False)
            window.run_analysis()
            self.assertTrue(all(not hasattr(window.plot_groups["P"]["plots"][name], "_group_axis")
                                for name in ("trend", "bias", "bias-percent")))
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_data_only_edit_and_undo_reuse_unaffected_plots(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        try:
            ref, raw, flags = self.frames()
            ref["Q Reference"] = raw["P"] * 4 + 1
            raw["Q"] = raw["P"] * 2
            window.set_reference_frame(ref)
            window.set_raw_frame(raw)
            window.group_controls.restore({"enabled": True, "mark_enabled": True}, flags)
            window.run_analysis()
            unchanged = window.plot_groups["Q"]["plots"]["match"].listDataItems()[0]
            groups = window.group_plot_page.plot_groups
            unaffected = {key: block["plots"]["match"].listDataItems()[0]
                          for key, block in groups.items() if key[1] == "Q"}
            column = raw.columns.get_loc("P")
            window.raw_model.edit({(1, column): "1.01"})
            app.processEvents()
            self.assertAlmostEqual(groups[("Old:0", "P")]["plots"]["match"].listDataItems()[0].xData[0], 1.01)
            window.raw_model.undo.undo()
            app.processEvents()
            self.assertAlmostEqual(groups[("Old:0", "P")]["plots"]["match"].listDataItems()[0].xData[0], 1.)
            self.assertIs(window.plot_groups["Q"]["plots"]["match"].listDataItems()[0], unchanged)
            for key, curve in unaffected.items():
                self.assertIs(groups[key]["plots"]["match"].listDataItems()[0], curve)
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_window_applies_groups_only_on_apply_and_restores_full_source(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window, restored = MatchingWindow(), MatchingWindow()
        try:
            ref, raw, flags = self.frames()
            window.set_reference_frame(ref)
            window.set_raw_frame(raw)
            window.group_controls.restore({"enabled": True}, flags)
            window.run_analysis()
            window.group_controls.change("filters", [{"table": "order", "column": "TestFlag", "values": ["1"]}])
            app.processEvents()
            self.assertEqual(len(window.result.series("P")), 6)
            restored.restore_workspace(window.workspace_snapshot())
            self.assertEqual(len(restored.result.series("P")), 6)
            self.assertTrue(restored.group_controls.pending)
            window.group_controls.apply_button.click()
            self.assertEqual(len(window.result.series("P")), 3)
            self.assertEqual(window.raw_view.model().rowCount(), 4)
            snapshot = window.workspace_snapshot()
            restored.restore_workspace(snapshot)
            self.assertEqual(len(restored.raw_frame), 6)
            self.assertEqual(len(restored.result.series("P")), 3)
            self.assertEqual(restored.group_controls.order_model.flags_frame(6).iloc[:, 0].tolist(), ["0", "0", "0", "1", "1", "1"])
            window.results_tabs.setCurrentWidget(window.group_plot_page)
            app.processEvents()
            self.assertFalse(window.group_plot_page.page_image().isNull())
            with tempfile.TemporaryDirectory() as directory:
                path = window.export_excel(Path(directory) / "groups.xlsx")
                output = pd.read_excel(path, sheet_name="Group Fits")
                self.assertEqual(output["Group"].tolist(), ["TestFlag 1"])
                self.assertEqual(output["Valid pairs"].tolist(), [3])
        finally:
            window.close()
            restored.close()
            window.deleteLater()
            restored.deleteLater()
            app.processEvents()

    def test_grouped_correlation_windows_keep_only_the_four_standard_tabs(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        app = QApplication.instance() or QApplication([])
        window = MatchingWindow()
        children = []
        try:
            ref, raw, flags = self.frames()
            window.set_reference_frame(ref)
            window.set_raw_frame(raw)
            window.group_controls.restore({"enabled": True}, flags)
            for mode in ("Preview", "Final"):
                with self.subTest(mode=mode):
                    window.result_mode.setCurrentText(mode)
                    if mode == "Final":
                        window.set_raw_frame(raw)
                    window.run_analysis()
                    child = window.open_correlation_workspace()
                    children.append(child)
                    self.assertEqual(
                        [child.tabs.tabText(i) for i in range(child.tabs.count())],
                        ["1. Ref Data", "2. Raw Data", "3. Correlation", "4. Trend"],
                    )
                    self.assertGreaterEqual(
                        window.results_tabs.indexOf(window.group_plot_page), 0,
                    )
        finally:
            for child in children:
                child.close()
                child.deleteLater()
            window.close()
            window.deleteLater()
            app.processEvents()

    def test_linked_trend_uses_group_order_and_standalone_snapshot(self):
        from PyQt6.QtWidgets import QApplication
        from metrology_app.matching_window import MatchingWindow
        from metrology_app.correlation_window import CorrelationWindow
        app = QApplication.instance() or QApplication([])
        window, loaded, copy = MatchingWindow(), MatchingWindow(), CorrelationWindow()
        child = None
        reopened = None
        try:
            ref, raw, flags = self.frames()
            raw["FIELD X"], raw["FIELD Y"] = [0, 1, 2] * 2, [0] * 6
            window.set_reference_frame(ref)
            window.set_raw_frame(raw)
            window.group_controls.restore({"enabled": True, "mark_enabled": True,
                                           "group_order": ["Old:1", "Old:0"]}, flags)
            window.run_analysis()
            child = window.open_correlation_workspace()
            child.sequence_page.selector.selectAll()
            child.sequence_page.draw_plot()
            self.assertTrue(child.sequence_page.ready, child.sequence_page.status.text())
            self.assertEqual(pd.to_numeric(child.sequence_page.groups[0]["frame"]["P"]).tolist(), [8., 11., 14.])
            drawn = child.sequence_page.draw_state()
            snapshot = child.workspace_snapshot()
            self.assertNotIn("group_plots", snapshot.states)
            self.assertNotIn("group_plots", child.selection_state())
            # Old files may still contain the deleted page's state and tab index.
            snapshot.states["group_plots"] = {"drawn": [["Old:1", "P"]], "has_drawn": True}
            snapshot.states["ui"]["selection"]["group_plots"] = snapshot.states["group_plots"]
            snapshot.states["ui"]["tab"] = 4
            copy.restore_workspace(snapshot)
            app.processEvents()
            self.assertEqual(copy.tabs.count(), 4)
            self.assertEqual(copy.tabs.currentIndex(), 3)
            self.assertEqual(copy.sequence_page.draw_state(), drawn)
            self.assertTrue(copy.sequence_page.ready, copy.sequence_page.status.text())
            self.assertEqual(pd.to_numeric(copy.sequence_page.groups[0]["frame"]["P"]).tolist(), [8., 11., 14.])
            with tempfile.TemporaryDirectory() as directory:
                from metrology_app.workspace_store import load_workspace
                path = window.save_workbook(Path(directory) / "parent.wkb")
                loaded.restore_workspace(load_workspace(path))
                reopened = loaded.open_correlation_workspace()
                app.processEvents()
                self.assertEqual(reopened.tabs.count(), 4)
                self.assertEqual(reopened.sequence_page.draw_state(), drawn)
                self.assertTrue(reopened.sequence_page.ready, reopened.sequence_page.status.text())
                self.assertEqual(pd.to_numeric(reopened.sequence_page.groups[0]["frame"]["P"]).tolist(), [8., 11., 14.])
        finally:
            if child is not None:
                child.close()
                child.deleteLater()
            if reopened is not None:
                reopened.close()
                reopened.deleteLater()
            copy.close()
            loaded.close()
            window.close()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
