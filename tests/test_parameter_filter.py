"""Parameter navigation filters presentation, not the fitted source population."""
import os
import unittest
from copy import deepcopy
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pandas as pd
from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget
from metrology_app.plotting.parameter_filter import ParameterFilterBar
from metrology_app.correlation_page import CorrelationPage
from metrology_app.sequence_page import SequencePage
from metrology_app import settings as settings_module
from metrology_app.matching_window import MatchingWindow
from metrology_app.workspace_store import load_workspace, save_workspace

APP = QApplication.instance() or QApplication([])


class ParameterFilterTests(unittest.TestCase):
    def test_multi_selection_prunes_removed_names_and_keyboard_and_restoration_keep_the_same_contract(self):
        bar = ParameterFilterBar()
        bar.set_parameters(["DP", "TG", "EW"])
        try:
            bar.show()
            APP.processEvents()
            QTest.mouseClick(bar.buttons["DP"], Qt.MouseButton.LeftButton)
            bar.buttons["EW"].setFocus()
            QTest.keyClick(bar.buttons["EW"], Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(bar.parameter, ["DP", "EW"])
            self.assertTrue(bar.matches(("DP", "TG")))
            self.assertFalse(bar.matches(("TG", "UC")))
            saved = bar.parameter
            saved.append("TG")
            self.assertEqual(bar.parameter, ["DP", "EW"])
            bar.set_parameters(["TG", "EW"])
            self.assertEqual(bar.parameter, "EW")
            self.assertTrue(bar.buttons["EW"].isChecked())
            bar.set_parameters(["TG"])
            self.assertIsNone(bar.parameter)
            self.assertTrue(bar.buttons[None].isChecked())
            bar.set_selection(["removed", {}, "TG"])
            self.assertEqual(bar.parameter, "TG")
            QTest.keyPress(bar.buttons["TG"], Qt.Key.Key_Control)
            bar.set_selection(None)
            QTest.keyRelease(bar.buttons["TG"], Qt.Key.Key_Control)
            self.assertIsNone(bar.parameter)
            self.assertTrue(bar.buttons[None].isChecked())
            bar.set_parameters(())
            self.assertIsNone(bar.parameter)
            self.assertEqual(bar.buttons, {})
        finally:
            bar.close()
            bar.deleteLater()
            APP.processEvents()

    def setUp(self):
        settings = settings_module.get_settings()
        self._saved_overlay = deepcopy(settings.get("trend_overlay", {}))
        self._saved_source_overlay = deepcopy(settings.get("trend_source_overlay"))
        settings_module._current["trend_overlay"] = {}
        settings_module._current.pop("trend_source_overlay", None)
        self._settings_patch = patch("metrology_app.sequence_page.save_settings")
        self._settings_patch.start()

    def tearDown(self):
        self._settings_patch.stop()
        settings_module._current["trend_overlay"] = self._saved_overlay
        if self._saved_source_overlay is None:
            settings_module._current.pop("trend_source_overlay", None)
        else:
            settings_module._current["trend_source_overlay"] = self._saved_source_overlay

    def test_multi_parameter_choices_survive_owned_wkb_reopen_and_old_single_choices_still_load(self):
        def close(window):
            if sip.isdeleted(window):
                return
            window.document.force_close = True
            window.close()
            window.deleteLater()
            APP.processEvents()

        parent = MatchingWindow()
        self.addCleanup(close, parent)
        frame, _selection = self.data()
        parent.match_type.setCurrentText("NOVA")
        parent.set_reference_frame(frame[["DP", "TG", "EW"]].rename(
            columns={name: f"{name} Reference" for name in ("DP", "TG", "EW")}))
        parent.set_raw_frame(frame)
        parent.run_analysis()
        child = parent.open_correlation_workspace()
        self.addCleanup(close, child)
        source = child.model.document_frame().copy()
        for page in (child.correlation_page, child.sequence_page):
            page.selector.selectAll()
            page.draw_plot()
            QTest.mouseClick(page.parameter_filter.buttons["DP"], Qt.MouseButton.LeftButton)
            QTest.mouseClick(page.parameter_filter.buttons["EW"], Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(page.parameter_filter.parameter, ["DP", "EW"])
        with TemporaryDirectory() as folder:
            path = Path(folder) / "multi-parameter.wkb"
            parent.save_workbook(path)
            saved = load_workspace(path)
            for page_name in ("correlation_page", "sequence_page"):
                self.assertEqual(saved.states["correlation.preview"]["ui"]["pages"][page_name]["parameter_filter"],
                                 ["DP", "EW"])
            legacy = Path(folder) / "single-parameter.wkb"
            for page_name in ("correlation_page", "sequence_page"):
                saved.states["correlation.preview"]["ui"]["pages"][page_name]["parameter_filter"] = "DP"
            save_workspace(legacy, saved)
            for file, expected in ((path, ["DP", "EW"]), (legacy, "DP")):
                with self.subTest(file=file.name):
                    restored = MatchingWindow()
                    self.addCleanup(close, restored)
                    restored.load_workbook(file)
                    reopened = restored.open_correlation_workspace()
                    self.addCleanup(close, reopened)
                    for page in (reopened.correlation_page, reopened.sequence_page):
                        self.assertEqual(page.parameter_filter.parameter, expected)
                        self.assertTrue(page.parameter_filter.buttons["DP"].isChecked())
                        self.assertEqual(page.parameter_filter.buttons["EW"].isChecked(), isinstance(expected, list))
                        self.assertFalse(page.parameter_filter.buttons[None].isChecked())
                    pd.testing.assert_frame_equal(reopened.model.document_frame(), source)
                    close(reopened)
                    close(restored)

    def test_ctrl_multi_select_displays_the_union_and_exports_it_without_replacing_curves_or_zoom(self):
        frame, selection = self.data()
        frame["UC"] = [4., 8., 12., 16., 20.]
        selection["metrics"] = ["DP", "TG", "EW", "UC"]
        for kind in (CorrelationPage, SequencePage):
            with self.subTest(page=kind.__name__):
                page = kind()
                try:
                    page.set_input(frame, selection)
                    page.selector.selectAll()
                    page.draw_plot()
                    if kind is SequencePage:
                        page.set_overlay("TG", "EW")
                    page.resize(1100, 760)
                    page.show()
                    APP.processEvents()
                    original = list(page.plot_widgets)
                    values = {widget: [item.getData()[1].copy() for item in widget.listDataItems()]
                              for widget in original}
                    for widget in original:
                        widget.getViewBox().setRange(xRange=(2, 4), yRange=(4, 8), padding=0)
                    zoom = {widget: widget.getViewBox().viewRange() for widget in original}
                    fits = list(page.all_fits) if kind is CorrelationPage else None
                    QTest.mouseClick(page.parameter_filter.buttons["DP"], Qt.MouseButton.LeftButton)
                    QTest.mouseClick(page.parameter_filter.buttons["EW"], Qt.MouseButton.LeftButton,
                                     Qt.KeyboardModifier.ControlModifier)
                    if kind is CorrelationPage:
                        expected = {frozenset(pair) for pair in (("DP", "TG"), ("DP", "EW"),
                                                               ("DP", "UC"), ("TG", "EW"), ("EW", "UC"))}
                        self.assertEqual({frozenset((fit.x_name, fit.y_name)) for fit in page.display_fits()}, expected)
                        self.assertEqual(page.all_fits, fits)
                        self.assertEqual(len(page.plot_widgets), 5)
                    else:
                        self.assertEqual([panel["metric"] for panel in page.display_panel_specs()], ["DP", "TG", "EW"])
                        self.assertEqual(len(page.plot_host.panels), 3)
                    for widget in page.plot_widgets:
                        self.assertIn(widget, original)
                        np.testing.assert_allclose(widget.getViewBox().viewRange(), zoom[widget])
                        for item, expected_values in zip(widget.listDataItems(), values[widget]):
                            np.testing.assert_array_equal(item.getData()[1], expected_values)
                    page.ensure_export_figure()
                    if kind is CorrelationPage:
                        visible_axes = [axis for axis in page.figure.axes if axis.axison]
                        self.assertEqual(len(visible_axes), 5)
                        self.assertEqual({frozenset((axis.get_xlabel(), axis.get_ylabel()))
                                          for axis in visible_axes}, expected)
                    else:
                        self.assertEqual(len(page.figure.axes), 3)
                        self.assertFalse(any("UC" in axis.get_title() for axis in page.figure.axes))
                    page.parameter_filter.buttons[None].click()
                    self.assertEqual(page.plot_widgets, original)
                    pd.testing.assert_frame_equal(page.frame, frame)
                finally:
                    page.close()
                    page.deleteLater()
                    APP.processEvents()

    def test_ctrl_click_adds_and_removes_parameters_while_plain_click_and_all_reset(self):
        bar = ParameterFilterBar()
        bar.set_parameters(["DP", "TG", "EW"])
        try:
            bar.show()
            APP.processEvents()
            QTest.mouseClick(bar.buttons["DP"], Qt.MouseButton.LeftButton)
            QTest.mouseClick(bar.buttons["EW"], Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(bar.parameter, ["DP", "EW"])
            self.assertTrue(bar.buttons["DP"].isChecked())
            self.assertTrue(bar.buttons["EW"].isChecked())
            self.assertFalse(bar.buttons[None].isChecked())
            QTest.mouseClick(bar.buttons["DP"], Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(bar.parameter, "EW")
            self.assertFalse(bar.buttons["DP"].isChecked())
            QTest.mouseClick(bar.buttons["TG"], Qt.MouseButton.LeftButton)
            self.assertEqual(bar.parameter, "TG")
            self.assertFalse(bar.buttons["EW"].isChecked())
            QTest.mouseClick(bar.buttons["TG"], Qt.MouseButton.LeftButton)
            self.assertTrue(bar.buttons["TG"].isChecked())
            QTest.mouseClick(bar.buttons["TG"], Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.ControlModifier)
            self.assertIsNone(bar.parameter)
            self.assertTrue(bar.buttons[None].isChecked())
            QTest.mouseClick(bar.buttons["DP"], Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(bar.parameter, "DP")
            QTest.mouseClick(bar.buttons[None], Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.ControlModifier)
            self.assertIsNone(bar.parameter)
            self.assertFalse(bar.buttons["DP"].isChecked())
        finally:
            bar.close()
            bar.deleteLater()
            APP.processEvents()

    def test_parameter_buttons_wrap_to_multiple_rows_and_reflow_when_widened(self):
        host = QWidget()
        layout = QVBoxLayout(host)
        bar = ParameterFilterBar()
        layout.addWidget(bar)
        layout.addStretch()
        bar.set_parameters([f"Parameter_{index:02}" for index in range(20)])
        try:
            host.resize(480, 500)
            host.show()
            APP.processEvents()
            positions = [button.mapTo(bar, button.rect().topLeft()) for button in bar.buttons.values()]
            self.assertGreaterEqual(len({position.y() for position in positions}), 3)
            for button, position in zip(bar.buttons.values(), positions):
                self.assertGreaterEqual(position.x(), 0)
                self.assertLessEqual(position.x() + button.width(), bar.width())
                self.assertLessEqual(position.y() + button.height(), bar.height())
            narrow_height = bar.height()
            bar.buttons["Parameter_19"].click()
            host.resize(4000, 500)
            APP.processEvents()
            self.assertEqual(len({button.mapTo(bar, button.rect().topLeft()).y()
                                  for button in bar.buttons.values()}), 1)
            self.assertEqual(bar.parameter, "Parameter_19")
            self.assertLess(bar.height(), narrow_height)
        finally:
            host.close()
            host.deleteLater()
            APP.processEvents()

    def data(self):
        frame = pd.DataFrame({"Wafer ID": ["W1"] * 5, "Die Seq": [2, 36, 85, 101, 105],
                              "DP": [1., 2., 3., 4., 5.], "TG": [2., 4., 6., 8., 10.],
                              "EW": [3., 6., 9., 12., 15.]})
        return frame, {"wafer_column": "Wafer ID", "wafers": ["W1"],
                       "metrics": ["DP", "TG", "EW"], "groups": {"W1": range(5)}}

    def test_clearing_data_removes_old_buttons_and_new_drawing_starts_with_all(self):
        frame, selection = self.data()
        for kind in (CorrelationPage, SequencePage):
            with self.subTest(page=kind.__name__):
                page = kind()
                try:
                    page.set_input(frame, selection)
                    page.selector.selectAll()
                    page.draw_plot()
                    page.resize(1100, 760)
                    page.show()
                    APP.processEvents()
                    page.parameter_filter.buttons["DP"].click()
                    old = page.parameter_filter.buttons["DP"]
                    page.set_input(pd.DataFrame(), {"wafers": [], "metrics": [], "groups": {}})
                    self.assertEqual(page.parameter_filter.names, ())
                    self.assertEqual(page.parameter_filter.buttons, {})
                    self.assertIsNone(page.parameter_filter.parameter)
                    self.assertTrue(page.parameter_filter.isHidden())
                    self.assertFalse(any(button.isVisible()
                                         for button in page.parameter_filter.findChildren(QPushButton)))
                    old.click()  # A stale queued choice cannot bring the old parameter back.
                    self.assertIsNone(page.parameter_filter.parameter)
                    page.set_input(frame, selection)
                    page.selector.selectAll()
                    page.draw_plot()
                    self.assertEqual(set(page.parameter_filter.names), {"DP", "TG", "EW"})
                    self.assertTrue(page.parameter_filter.buttons[None].isChecked())
                finally:
                    page.close()
                    page.deleteLater()
                    APP.processEvents()

    def test_correlation_parameter_and_all_keep_fits_curves_and_zoom(self):
        page = CorrelationPage()
        frame, selection = self.data()
        try:
            page.set_input(frame, selection)
            page.selector.selectAll()
            page.start_draw()
            APP.processEvents()

            original = list(page.plot_widgets)
            self.assertEqual(len(original), 3, page.status.text())
            fits = list(page.all_fits)
            self.assertEqual(len(original), 3)
            original[0].getViewBox().setRange(xRange=(2, 4), yRange=(4, 8), padding=0)
            zoom = original[0].getViewBox().viewRange()
            page.parameter_filter.buttons["DP"].click()
            self.assertEqual(len(page.page_fits()), 2)
            self.assertTrue(all("DP" in (fit.x_name, fit.y_name) for fit in page.page_fits()))
            self.assertEqual(page.all_fits, fits)
            page.parameter_filter.buttons[None].click()
            self.assertEqual(page.plot_widgets, original)
            np.testing.assert_allclose(original[0].getViewBox().viewRange(), zoom)
            pd.testing.assert_frame_equal(page.frame, frame)
        finally:
            page.close()
            page.deleteLater()
            APP.processEvents()

    def test_removed_parameter_buttons_disappear_without_resetting_a_surviving_filter(self):
        frame, selection = self.data()
        for kind in (CorrelationPage, SequencePage):
            with self.subTest(page=kind.__name__):
                page = kind()
                try:
                    page.set_input(frame, selection)
                    page.selector.selectAll()
                    page.draw_plot()
                    page.parameter_filter.buttons["DP"].click()
                    page.set_input(frame.drop(columns="EW"), {**selection, "metrics": ["DP", "TG"]})
                    self.assertEqual(set(page.parameter_filter.names), {"DP", "TG"})
                    self.assertEqual(page.parameter_filter.parameter, "DP")
                    self.assertNotIn("EW", page.parameter_filter.buttons)
                finally:
                    page.close()
                    page.deleteLater()
                    APP.processEvents()

    def test_filtered_cached_headings_and_exports_use_current_rank(self):
        page = CorrelationPage()
        frame, selection = self.data()
        try:
            page.set_input(frame, selection)
            page.selector.selectAll()
            page.start_draw()
            APP.processEvents()
            first = page.fits[0]
            parameter = next(name for name in selection["metrics"] if name not in (first.x_name, first.y_name))
            page.parameter_filter.buttons[parameter].click()
            for rank, panel in enumerate(page.panel_hosts, 1):
                self.assertIn(f"rank {rank}", panel.findChildren(QLabel)[0].text())
            page.ensure_export_figure()
            self.assertEqual(len(page.figure.axes), 2)
            self.assertTrue(all(parameter in (ax.get_xlabel(), ax.get_ylabel()) for ax in page.figure.axes))
        finally:
            page.deleteLater()
            APP.processEvents()

    def test_trend_filter_includes_comparison_parameter_and_export(self):
        page = SequencePage()
        frame, selection = self.data()
        try:
            page.set_input(frame, selection)
            page.selector.selectAll()
            page.draw_plot()
            page.set_overlay("DP", "EW")
            APP.processEvents()
            original = list(page.plot_widgets)
            page.parameter_filter.buttons["EW"].click()
            self.assertEqual([panel["metric"] for panel in page.display_panel_specs()], ["DP", "EW"])
            page.ensure_export_figure()
            self.assertTrue(any("DP" in ax.get_title() for ax in page.figure.axes))
            self.assertFalse(any("TG" == ax.get_ylabel() for ax in page.figure.axes))
            page.parameter_filter.buttons[None].click()
            self.assertEqual(page.plot_widgets, original)
        finally:
            page.deleteLater()
            APP.processEvents()

    def test_trend_parameter_and_all_reuse_every_panel_and_keep_full_curve_values(self):
        page = SequencePage()
        frame, selection = self.data()
        try:
            page.set_input(frame, selection)
            page.selector.selectAll()
            page.draw_plot()
            APP.processEvents()
            original = list(page.plot_widgets)
            curves = [widget.listDataItems()[0] for widget in original]
            values = [curve.getData()[1].copy() for curve in curves]
            page.parameter_filter.buttons["DP"].click()
            self.assertEqual(len(page.plot_host.panels), 1)
            self.assertIs(page.plot_widgets[0], original[0])
            page.parameter_filter.buttons[None].click()
            self.assertEqual(page.plot_widgets, original)
            for curve, expected in zip(curves, values):
                np.testing.assert_array_equal(curve.getData()[1], expected)
        finally:
            page.close()
            page.deleteLater()
            APP.processEvents()


if __name__ == "__main__":
    unittest.main()
