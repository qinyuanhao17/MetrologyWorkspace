"""Observable plotting and file-opening requests, without a live desktop."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd
import numpy as np
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QApplication, QPushButton

from metrology_app.dynamic_window import DynamicWindow
from metrology_app.window import MainWindow
from metrology_app.workspace_store import EXTENSIONS
from metrology_app.workspace_store import WorkspaceSnapshot, load_workspace, save_workspace, workspace_path
from metrology_app.matching_window import MatchingWindow
from metrology_app.correlation_window import CorrelationWindow
from metrology_app.dynamic_trend import DynamicTrendPage
from metrology_app.plotting.annotations import statistics_text, point_tip

APP = QApplication.instance() or QApplication([])


def dynamic_frame():
    return pd.DataFrame({
        "Wafer ID": ["W1"] * 6, "Die Seq": [1, 2, 1, 2, 1, 2],
        "DP": ["0.010", "0.020", "0.011", "0.022", "0.012", "0.024"],
        "EW": ["10", "20", "11", "22", "12", "24"],
    })


class RequestedPlotControlsTests(unittest.TestCase):
    def close_window(self, window):
        window.document.timer.stop()
        window.document.confirm_close = lambda: True
        if hasattr(window, "model"):
            window.model.undo.setClean()
        window.close()
        window.deleteLater()
        APP.processEvents()

    def test_dynamic_no_longer_offers_restore(self):
        window = DynamicWindow()
        self.addCleanup(self.close_window, window)
        window.set_table(dynamic_frame(), "dynamic.csv")
        for index in range(window.parameter_list.topLevelItemCount()):
            item = window.parameter_list.topLevelItem(index)
            if item.text(0) == "DP":
                item.setCheckState(0, Qt.CheckState.Checked)
        window.update_plan()
        self.assertTrue(window.dynamic_page.parameter_sections)
        self.assertNotIn("Restore", [button.text() for button in
                                    window.dynamic_page.findChildren(QPushButton)])

    def test_open_dialog_offers_backups(self):
        window = MainWindow()
        self.addCleanup(self.close_window, window)
        with patch("metrology_app.window.QFileDialog.getOpenFileName", return_value=("", "")) as dialog:
            window.open_file()
        self.assertIn("*.bak", dialog.call_args.args[3])

    def test_backup_routes_to_workspace_loader_not_table_import(self):
        window = MainWindow()
        self.addCleanup(self.close_window, window)
        with patch.object(window, "load_workspace", return_value=True) as load:
            window.load_path(Path("example.wmap.bak"))
        load.assert_called_once_with(Path("example.wmap.bak"))

    def test_new_match_extension_is_mwkb(self):
        self.assertEqual(EXTENSIONS["match_workbook"], ".mwkb")

    def test_statistics_ignore_missing_values_and_use_sample_sigma(self):
        self.assertEqual(statistics_text([1, np.nan, 3, np.inf]),
                         "Mean: 2 · σ: 1.41421 · Min: 1 · Max: 3")
        self.assertIn("σ: N/A", statistics_text([1]))
        self.assertIn("Mean: N/A", statistics_text([]))

    def test_dynamic_comparisons_follow_the_same_die_and_export_every_curve(self):
        page = DynamicTrendPage()
        self.addCleanup(page.deleteLater)
        tables = {"DP": pd.DataFrame({1: [.01, .02], 2: [.03, .04]}, index=[1, 2]),
                  "EW": pd.DataFrame({1: [1., 2.], 2: [3., 4.]}, index=[1, 2])}
        page.render_interactive(tables)
        page.add_compare("DP")
        self.assertEqual(len(page.data_curves(page.panel_widgets["DP"])), 2)
        page.select_die("DP", 2)
        np.testing.assert_equal(page.data_curves(page.panel_widgets["DP"])[1].yData, [3., 4.])
        self.assertEqual(page.selected_dies["EW"], 1)
        page.ensure_export_figure()
        self.assertEqual(len(page.figure.axes[0].lines), 1)
        self.assertEqual(len(page.figure.axes[-1].lines), 1)
        self.assertEqual(page.figure.axes[-1].get_ylabel(), 'EW')
        self.assertFalse(page.panel_widgets["DP"].getAxis("left").autoSIPrefix)
        item = page.panel_widgets["DP"].listDataItems()[0]
        self.assertEqual(list(item.scatter.data["data"]), [2, 2])
        self.assertEqual(item.scatter.opts["tip"](.01, .03, 2), "Die: 2\nX: 0.01\nY: 0.03")
        page.change_compare("DP", 0, None)
        self.assertEqual(len(page.panel_widgets["DP"].listDataItems()), 1)

    def test_match_points_and_sequence_curves_keep_die_metadata_and_full_statistics(self):
        window = MatchingWindow()
        self.addCleanup(self.close_window, window)
        raw = pd.DataFrame({"Wafer ID": ["W1", "W1", "W2"],
                            "Die Seq": ["10", "20", "30"], "DP": ["0.0100", "0.0200", "0.0300"]})
        reference = pd.DataFrame({"DP Reference": ["0.011", "0.019", "0.032"]})
        window.set_reference_frame(reference)
        window.set_raw_frame(raw)
        window.run_analysis()
        group = window.plot_groups["DP"]
        plots = group["plots"]
        self.assertEqual(list(plots["match"].listDataItems()[0].scatter.data["data"]), ["10", "20", "30"])
        for name in ("trend", "bias"):
            item = plots[name].listDataItems()[0]
            self.assertEqual(list(item.scatter.data["data"]), ["10", "20", "30"])
            self.assertTrue(item.scatter.opts["hoverable"])
            self.assertFalse(plots[name].getAxis("left").autoSIPrefix)
            self.assertEqual(plots[name].wafer_boundaries.pen.widthF(), 1.)
            self.assertIsNone(plots[name].wafer_boundaries.halo)
        self.assertIsNone(group["statistics"])
        self.assertIn("Mean:", plots["trend"].getViewBox().toolTip())
        self.assertIn("σ:", plots["bias"].getViewBox().toolTip())
        self.assertFalse(hasattr(plots["trend"], "statistics_label"))
        window.resize(1400, 900)
        window.show()
        APP.processEvents()
        points = plots["match"].listDataItems()[0]
        points.scatter.hoverEvent(SimpleNamespace(exit=False, pos=lambda: QPointF(points.xData[0], points.yData[0])))
        self.assertIn("Die: 10\nX: 0.01\nY: 0.011", plots["match"].getViewBox().toolTip())
        plots["trend"].card_checkbox.setChecked(False)
        self.assertIn("Mean: 0.02", plots["trend"].getViewBox().toolTip())
        pd.testing.assert_frame_equal(window.raw_model.document_frame(), raw)

    def test_new_match_paths_migrate_but_old_wkb_and_backup_contents_remain_readable(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "old.wkb"
            snapshot = WorkspaceSnapshot("match_workbook", {"raw": pd.DataFrame({"DP": ["0.0100"]}),
                                                           "reference": pd.DataFrame({"DP": ["0.0101"]})},
                                         {"match": {"draft": True}})
            saved = save_workspace(target, snapshot)
            self.assertEqual(saved.suffix, ".mwkb")
            legacy = saved.rename(target)
            original = legacy.read_bytes()
            self.assertEqual(load_workspace(legacy).frames["raw"].iloc[0, 0], "0.0100")
            backup = Path(str(legacy) + ".bak")
            backup.write_bytes(original)
            self.assertEqual(load_workspace(backup).workspace_type, "match_workbook")
            with self.assertRaises(ValueError):
                workspace_path(backup, "match_workbook")
            self.assertEqual(backup.read_bytes(), original)
            self.assertEqual(legacy.read_bytes(), original)

    def test_dynamic_mode_comparisons_and_statistics_round_trip(self):
        window = DynamicWindow()
        self.addCleanup(self.close_window, window)
        window.set_table(dynamic_frame(), "dynamic.csv")
        for index in range(window.parameter_list.topLevelItemCount()):
            item = window.parameter_list.topLevelItem(index)
            if item.text(0) in ("DP", "EW"):
                item.setCheckState(0, Qt.CheckState.Checked)
        window.update_plan()
        page = window.dynamic_trend
        page.add_compare("DP")
        snapshot = window.workspace_snapshot()
        window.restore_workspace(snapshot)
        self.assertEqual(page.comparisons, {"DP": ["EW"]})
        self.assertFalse(hasattr(page, "show_statistics"))
        self.assertEqual([item.dynamic_series for item in page.panel_widgets["DP"].listDataItems()],
                         [("DP", "1")])
        self.assertEqual(len(page.data_curves(page.panel_widgets["DP"])), 2)

    def test_row_number_fallback_does_not_invent_die_metadata(self):
        window = CorrelationWindow()
        self.addCleanup(self.close_window, window)
        window.set_table(pd.DataFrame({"Wafer ID": ["W1", "W1"], "CD": ["1.00", "2.00"]}), "Raw")
        page = window.sequence_page
        page.selector.selectAll()
        page.draw_plot()
        self.assertTrue(page.ready, page.status.text())
        item = page.plot_widgets[0].listDataItems()[0]
        self.assertEqual(list(item.scatter.data["data"]), [None, None])
        self.assertEqual(point_tip(2, 1, None), "Die: N/A\nX: 2\nY: 1")
