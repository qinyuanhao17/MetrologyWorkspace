"""Replayed literal sources retain complete classification and fresh source ownership."""
import unittest
import pandas as pd
from PyQt6.QtWidgets import QApplication
from metrology_app.match_group_ui import GroupControls

APP = QApplication.instance() or QApplication([])


class GroupPlanSnapshotReuseTests(unittest.TestCase):
    def test_replayed_and_changed_sources_keep_exact_current_plan(self):
        controls = GroupControls()
        self.addCleanup(controls.deleteLater)
        raw = pd.DataFrame({"Wafer ID": ["001", "001", "002"],
                            "Die Seq": ["01", "02", "01"], "CD": ["1.000", "2.000", "3.000"]})
        ref = pd.DataFrame({"Ref": ["2.000", "4.000", "6.000"]})
        controls.restore({"enabled": True, "mark_enabled": False},
                         pd.DataFrame({"TestFlag": ["0", "0", "1"]}))
        controls.set_sources(ref, raw)
        accepted = controls.plan
        for text in ("9.000", "1.000", "1.00"):
            latest = raw.copy(deep=True)
            latest.iloc[0, 2] = text
            controls.set_sources(ref.copy(deep=True), latest)
            self.assertIs(controls.plan.raw, latest)
            self.assertEqual(controls.plan.raw.iloc[0, 2], text)
            self.assertEqual(controls.plan.included_rows, (0, 1, 2))
            self.assertEqual(controls.plan.flags, ("0", "0", "1"))
            pd.testing.assert_frame_equal(accepted.raw, raw)
        controls.order_model.edit({(1, 0): "1"})
        self.assertEqual(controls.plan.flags, ("1", "0", "1"))
        self.assertEqual(accepted.flags, ("0", "0", "1"))
