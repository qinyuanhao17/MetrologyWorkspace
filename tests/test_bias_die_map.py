"""Out-of-range maps retain analysis row identities and measured millimetres."""
import unittest
from dataclasses import replace

import pandas as pd
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QDoubleSpinBox

from metrology_app.bias_die_map import die_map_points, out_of_range_rows
from metrology_app.matching_window import MatchingWindow
from metrology_app.sme_spectra import LoadResult
from metrology_app.spectra_viewer import SpectraViewerWindow
from tests.test_spectra_viewer import APP, make_spectrum


class BiasDieMapTests(unittest.TestCase):
    def test_tree_headers_sort_numeric_fields_and_double_click_restores_default(self):
        viewer = SpectraViewerWindow()
        viewer.document.force_close = True
        self.addCleanup(viewer.close)
        sources = (replace(make_spectrum(2), identity=replace(make_spectrum(2).identity, field_x=1)),
                   replace(make_spectrum(10), identity=replace(make_spectrum(10).identity, field_x=-2)))
        viewer.apply_load_result(LoadResult(sources, ()), replace=True)
        viewer.set_spectrum_checks({sources[0].key: True})
        viewer.unfold_tree()
        QTest.qWait(50)
        viewer.select_spectrum_keys({sources[1].key})
        viewer.plot_panels["S"].plot.setXRange(230, 350, padding=0)
        limits = viewer.plot_panels["S"].plot.getViewBox().viewRange()[0]
        group = viewer.tree.topLevelItem(0).child(0).child(0)
        viewer.tree.header().sectionClicked.emit(6)
        APP.processEvents()
        self.assertEqual([group.child(i).text(5) for i in range(2)], ["10", "2"])
        viewer.tree.header().sectionClicked.emit(6)
        APP.processEvents()
        self.assertEqual([group.child(i).text(5) for i in range(2)], ["2", "10"])
        viewer.tree.header().sectionDoubleClicked.emit(1)
        APP.processEvents()
        group = viewer.tree.topLevelItem(0).child(0).child(0)
        self.assertEqual([group.child(i).text(5) for i in range(2)], ["2", "10"])
        self.assertEqual(viewer.checked_spectra(), (sources[0],))
        self.assertEqual(viewer._selected_keys, {sources[1].key})
        self.assertFalse(viewer.tree.header().isSortIndicatorShown())
        self.assertEqual(viewer.plot_panels["S"].plot.getViewBox().viewRange()[0], limits)
        viewer.apply_load_result(LoadResult((make_spectrum(1, wafer="W1", lot="Z"),
                                             make_spectrum(1, wafer="W2", lot="A")), ()), replace=True)
        viewer.tree.header().sectionClicked.emit(2)
        APP.processEvents()
        self.assertEqual([viewer.tree.topLevelItem(i).text(0) for i in range(2)], ["W2", "W1"])
        self.assertEqual(viewer.tree.topLevelItem(0).child(0).child(0).childCount(), 0)

    def test_mapping_button_uses_strict_absolute_bias_and_reuses_the_map_on_limit_changes(self):
        owner = MatchingWindow()
        owner.document.force_close = True
        self.addCleanup(owner.close)
        owner.set_reference_frame(pd.DataFrame({"CD Reference": [0, 1, 2, 3]}))
        owner.result_mode.setCurrentText("Final")
        owner.set_raw_frame(pd.DataFrame({"Wafer ID": ["W1"] * 4, "Lot ID": ["L1"] * 4,
            "PAD Name": ["P1"] * 4, "Die Seq": [1, 2, 3, 4], "FIELD X": [0, 1, 0, 1],
            "FIELD Y": [0, 0, 1, 1], "X (mm)": [0, 20, 0, 20], "Y (mm)": [0, 0, 30, 30],
            "CD": [0, 1.5, 3, "NaN"]}))
        button = owner.mapping_table.cellWidget(0, 12)
        self.assertEqual(button.text(), "Show Die Map")
        self.assertFalse(button.isEnabled())
        owner.run_analysis()
        self.assertTrue(button.isEnabled())
        self.assertEqual(out_of_range_rows(owner.result, "CD"), {2})
        button.click()
        window = owner._bias_die_maps["CD"]
        QTest.qWait(80)
        self.assertEqual(window._checked_keys, {"source-row:2"})
        self.assertEqual(window.point_count, 4)
        plot = next(iter(window.wafer_plots.values()))
        self.assertIn("1 out of range", plot.summary_label.text())
        outlier = next(point for point in plot.scatter.points() if 'source-row:2' in point.data()['keys'])
        self.assertEqual(outlier.brush().color().name(),'#dc2626')
        self.assertIn('Red: out of range',window.statusBar().currentMessage())
        self.assertGreaterEqual(owner.mapping_table.rowHeight(0),44)
        self.assertEqual((plot.pad_layout.width_mm, plot.pad_layout.height_mm), (20, 30))
        owner.mapping_table.cellWidget(0, 10).findChild(QDoubleSpinBox).setValue(.6)
        QTest.qWait(20)
        self.assertIs(next(iter(window.wafer_plots.values())), plot)
        self.assertEqual(window._checked_keys, {"source-row:2"})
        owner.mapping_table.cellWidget(0, 10).findChild(QDoubleSpinBox).setValue(1)
        self.assertEqual(window.point_count, 0)

    def test_coordinate_join_uses_identity_not_filename_and_rejects_missing_or_ambiguous_xy(self):
        raw = pd.DataFrame({"Wafer ID": ["W1"], "Lot ID": ["L1"], "PAD Name": ["P1"], "Die Seq": ["2.0"]})
        metadata = {"path": "unrelated-name.sme", "identity": {"wafer": "W1", "lot": "L1", "pad": "P1", "die_seq": 2},
                    "x_mm": 24.17, "y_mm": -28.53}
        points, issues = die_map_points(raw, [0], [metadata])
        self.assertFalse(issues)
        self.assertEqual((points[0].x_mm, points[0].y_mm), (24.17, -28.53))
        self.assertTrue(die_map_points(raw, [0])[1])
        self.assertTrue(die_map_points(raw, [0], [metadata, {**metadata, "x_mm": 50}])[1])
