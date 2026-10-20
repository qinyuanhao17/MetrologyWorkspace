"""Stage participation and point-label presentation regression checks."""
import unittest
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from PyQt6.QtCore import QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLineEdit, QPushButton

from metrology_app.array_plot import ArrayOptions, prepare_array
from metrology_app.analysis_export import capture_window
from metrology_app.matching_window import MatchingWindow
from metrology_app.plot import ValueLabels
from metrology_app.window import MainWindow
from metrology_app.workspace_store import load_workspace, save_workspace
from metrology_app.settings import get_settings, save_settings

APP = QApplication.instance() or QApplication([])


class StageSelectionAndPointPrecisionTests(unittest.TestCase):
    def setUp(self):
        saved = get_settings()
        self.addCleanup(save_settings, saved)
        save_settings({"point_value_decimals": 2})

    def close(self, window):
        window.document.force_close = True
        window.close()
        window.deleteLater()
        APP.processEvents()

    def matching_window(self):
        window = MatchingWindow()
        self.addCleanup(self.close, window)
        window.set_reference_frame(pd.DataFrame({"CD Reference": [3., 5., 7., 8., 11., 14.]}))
        window.set_raw_frame(pd.DataFrame({"Wafer ID": ["W1"] * 3 + ["W2"] * 3,
                                           "Die Seq": [1, 2, 3] * 2,
                                           "CD": [1., 2., 3., 4., 5., 6.]}))
        return window

    def exclude_second_wafer(self, window):
        errors = []
        def choose():
            dialog = APP.activeModalWidget()
            try:
                dialog.findChild(QLineEdit, "dataSelectionSearch").setText("W2")
                next(button for button in dialog.findChildren(QPushButton)
                     if button.text() == "Uncheck Visible").click()
                dialog.accept()
            except Exception as error:
                errors.append(error)
                dialog.reject()
        QTimer.singleShot(0, choose)
        window.data_selection_action.trigger()
        self.assertEqual(errors, [])
        self.assertEqual(window.result.source_rows, (0, 1, 2))

    def test_preview_selection_survives_switch_to_empty_final_and_back(self):
        window = self.matching_window()
        window.run_analysis()
        self.exclude_second_wafer(window)
        before = window.workspace_snapshot()
        window.mode_tabs.setCurrentIndex(1)
        window.mode_tabs.setCurrentIndex(0)
        APP.processEvents()
        self.assertEqual(window.result.source_rows, (0, 1, 2))
        self.assertEqual(window.group_controls.state["data_selection"],
                         before.states["match"]["grouping_state"]["data_selection"])

    def test_selection_survives_ready_stage_switches_without_setting_it_again(self):
        window = self.matching_window()
        raw = window.raw_frame.copy()
        window.mode_tabs.setCurrentIndex(1)
        window.set_raw_frame(raw.assign(CD=raw.CD * 2))
        window.mode_tabs.setCurrentIndex(0)
        window.run_analysis()
        self.exclude_second_wafer(window)
        for index in (1, 0, 1, 0):
            window.mode_tabs.setCurrentIndex(index)
            APP.processEvents()
            self.assertEqual(window.workbook.result_mode, ("preview", "final")[index], window.status.text())
            self.assertEqual(window.result.source_rows, (0, 1, 2))
            self.assertEqual(window.result.summary["Valid pairs"].tolist(), [3])

    def test_loading_final_after_preview_selection_keeps_shared_participation(self):
        window = self.matching_window()
        raw = window.raw_frame.copy()
        window.run_analysis()
        self.exclude_second_wafer(window)
        window.mode_tabs.setCurrentIndex(1)
        selected = window.group_controls.state["data_selection"]
        excluded = list(selected["excluded"])
        window.set_raw_frame(raw.assign(CD=raw.CD * 2))
        self.assertEqual(window.group_controls.state["data_selection"]["excluded"], excluded)
        self.assertEqual(window.group_controls.state["applied"]["data_selection"]["excluded"], excluded)
        window.run_analysis()
        self.assertEqual(window.result.source_rows, (0, 1, 2))
        window.mode_tabs.setCurrentIndex(0)
        self.assertEqual(window.result.source_rows, (0, 1, 2))

    def test_temporarily_empty_final_does_not_reset_preview_participation(self):
        window = self.matching_window()
        raw = window.raw_frame.copy()
        window.mode_tabs.setCurrentIndex(1)
        window.set_raw_frame(raw.assign(CD=raw.CD * 2))
        window.mode_tabs.setCurrentIndex(0)
        window.run_analysis()
        self.exclude_second_wafer(window)
        window.mode_tabs.setCurrentIndex(1)
        window.final_raw_model.load(pd.DataFrame())
        window.mode_tabs.setCurrentIndex(0)
        self.assertEqual(window.result.source_rows, (0, 1, 2))

    def test_restored_head_mark_selection_survives_first_final_paste(self):
        window = self.matching_window()
        window.group_controls.restore({"enabled": True, "mark_enabled": True},
                                      pd.DataFrame({"TestFlag": [0] * 3 + [1] * 3}))
        window.run_analysis()
        self.exclude_second_wafer(window)
        snapshot = window.workspace_snapshot()
        window.restore_workspace(snapshot)
        window.mode_tabs.setCurrentIndex(1)
        window.final_raw_model.load(window.raw_model.document_frame())
        window.run_analysis()
        self.assertEqual(window.result.source_rows, (0, 1, 2))
        self.assertTrue(window.result.group_plan.enabled)
        window.mode_tabs.setCurrentIndex(0)
        self.assertEqual(window.result.source_rows, (0, 1, 2))

    def test_selection_survives_stage_specific_literal_id_representations(self):
        window = self.matching_window()
        raw = window.raw_frame.copy()
        raw["Die Seq"] = raw["Die Seq"].map(lambda value: f"{value:.1f}")
        window.mode_tabs.setCurrentIndex(1)
        window.set_raw_frame(raw.assign(CD=raw.CD * 2))
        window.mode_tabs.setCurrentIndex(0)
        window.run_analysis()
        self.exclude_second_wafer(window)
        for index in (1, 0, 1, 0):
            window.mode_tabs.setCurrentIndex(index)
            APP.processEvents()
            self.assertEqual(window.workbook.result_mode, ("preview", "final")[index], window.status.text())
            self.assertEqual(window.result.source_rows, (0, 1, 2))

    def test_point_values_default_to_two_fixed_decimal_places(self):
        labels = ValueLabels(np.array([[0, 0], [1, 1], [2, 2]]), [1.23456, 2., -0.001], 8)
        self.assertEqual(labels.labels, ["1.23", "2.00", "0.00"])

    def test_changing_precision_never_rounds_the_measurements(self):
        values = [1.23456789, 2., -.001]
        labels = ValueLabels(np.array([[0, 0], [1, 1], [2, 2]]), values, 8)
        for decimals, expected in ((4, ["1.2346", "2.0000", "-0.0010"]),
                                   (0, ["1", "2", "0"]),
                                   (2, ["1.23", "2.00", "0.00"])):
            labels.set_decimals(decimals)
            self.assertEqual(labels.labels, expected)
            self.assertEqual(labels.values, tuple(values))
        for invalid in (-1, 11, 2.5):
            with self.assertRaises(ValueError):
                labels.set_decimals(invalid)

    def rendered_map(self):
        window = MainWindow()
        self.addCleanup(self.close, window)
        frame = pd.DataFrame({"Wafer ID": ["W1"] * 4,
                              "X": [0, 1, 0, 1], "Y": [0, 0, 1, 1],
                              "CD": [1.234567, 2., 3., 4.]})
        window.set_table(frame, "Precision fixture")
        window._set_checked_values(window.parameter_list, ("CD",))
        window.update_plan()
        page = window.plot_page
        cells = {(page.selection["wafers"][0], "CD")}
        selection = dict(page.selection, metrics=["CD"], cells=list(cells))
        result = prepare_array(frame, selection, ArrayOptions("X", "Y", diameter=4))
        self.assertFalse(result["scenes"][0]["error"])
        page.pending_cells = cells
        page.selector.set_selected_cells(cells, notify=False)
        page.render_result(result)
        self.assertEqual(len(page.artists), 1, page.status.text())
        return window, page

    def test_precision_changes_existing_labels_without_reinterpolation(self):
        window, page = self.rendered_map()
        artist, scene = page.artists[0]
        surface = scene["surface"]
        original = window.workspace_snapshot().frames
        with patch("metrology_app.plot_page.prepare_array", side_effect=AssertionError("Reinterpolated")), \
                patch("metrology_app.plot_page.draw_array", side_effect=AssertionError("Rebuilt maps")):
            page.point_decimals.setValue(4)
            page.apply_overlay_visibility()
            self.assertIs(page.artists[0][0], artist)
            self.assertIs(scene["surface"], surface)
            self.assertEqual(artist.value_labels.labels, ["1.2346", "2.0000", "3.0000", "4.0000"])
            self.assertEqual(scene["options"].point_decimals, 4)
            self.assertEqual(page.result["settings"].point_decimals, 4)
        for key, frame in original.items():
            pd.testing.assert_frame_equal(frame, window.workspace_snapshot().frames[key])

    def test_precision_is_an_application_preference_not_restored_from_documents(self):
        window, page = self.rendered_map()
        page.point_decimals.setValue(5)
        snapshot = window.workspace_snapshot()
        with tempfile.TemporaryDirectory() as directory:
            saved = save_workspace(Path(directory) / "precision.wmap", snapshot)
            restored = load_workspace(saved)
        page.point_decimals.setValue(0)
        window.restore_workspace(restored)
        deadline = time.monotonic() + 10
        while (page.worker is not None or page.input_refresh_timer.isActive()) and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertIsNone(page.worker)
        self.assertEqual(page.point_decimals.value(), 0)
        self.assertTrue(page.artists, page.status.text())
        self.assertEqual(page.artists[0][0].value_labels.labels[0], "1")
        self.assertNotIn("point_decimals", restored.states["ui"]["pages"]["plot_page"]["controls"])
        restored.states["ui"]["pages"]["plot_page"]["controls"]["point_decimals"] = 9
        window.restore_workspace(restored)
        self.assertEqual(page.point_decimals.value(), 0)

    def test_immediate_export_and_copy_flush_pending_precision(self):
        _window, page = self.rendered_map()
        page.point_decimals.setValue(4)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "map.png"
            with patch("metrology_app.plot_page.QFileDialog.getSaveFileName",
                       return_value=(str(path), "PNG image (*.png)")):
                page.export_image()
            self.assertTrue(path.is_file(), page.status.text())
            self.assertGreater(path.stat().st_size, 1000)
        self.assertEqual(page.artists[0][0].value_labels.labels[0], "1.2346")
        page.point_decimals.setValue(1)
        page.copy_png()
        self.assertFalse(APP.clipboard().image().isNull(), page.status.text())
        self.assertEqual(page.artists[0][0].value_labels.labels[0], "1.2")

    def test_report_export_flushes_pending_precision(self):
        window, page = self.rendered_map()
        page.point_decimals.setValue(3)
        report = capture_window(window)
        self.assertEqual(page.artists[0][0].value_labels.labels[0], "1.235")
        self.assertEqual(len(report["pictures"]), 1)

    def test_export_uses_precision_even_while_map_selector_is_visible(self):
        window, page = self.rendered_map()
        page.show_selector()
        page.point_decimals.setValue(4)
        capture_window(window)
        self.assertEqual(page.artists[0][0].value_labels.labels[0], "1.2346")
        self.assertIs(page.stack.currentWidget(), page.selector_panel)

    def test_precision_control_is_on_appearance_row_and_defaults_to_two(self):
        window = MainWindow()
        self.addCleanup(self.close, window)
        page = window.plot_page
        self.assertEqual(page.point_decimals.value(), 2)
        self.assertEqual(page.point_decimals.objectName(), "pointValueDecimals")
        rows = page.findChildren(QHBoxLayout)
        self.assertTrue(any(row.indexOf(page.opacity) >= 0 and row.indexOf(page.point_decimals) >= 0
                            for row in rows))
