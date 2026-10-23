"""Recovery may share identical stored tables, never editable recovered frames."""
import unittest
import pandas as pd
from metrology_app.workspace_document import pack_snapshot, unpack_snapshot
from metrology_app.workspace_store import WorkspaceSnapshot


class RecoveryFrameSharingTests(unittest.TestCase):
    def test_equal_tables_share_storage_but_unpack_as_independent_copies(self):
        frame = pd.DataFrame({"CD": ["001.000", " 2.500 ", "-0.000"]})
        container = WorkspaceSnapshot("wafer_map", {"input_data": frame.copy()})
        accepted = WorkspaceSnapshot("wafer_map", {"input_data": frame.copy()}, {"ui": {"values": True}})
        description = pack_snapshot(container, "baseline", accepted)
        self.assertEqual(len(container.frames), 1)
        restored = unpack_snapshot(container, description)
        pd.testing.assert_frame_equal(restored.frames["input_data"], frame)
        restored.frames["input_data"].iloc[0, 0] = "changed"
        self.assertEqual(container.frames["input_data"].iloc[0, 0], "001.000")

    def test_different_literal_values_or_column_order_are_never_shared(self):
        first = pd.DataFrame({"A": ["1.00"], "B": ["02"]})
        for other in (pd.DataFrame({"A": ["1.0"], "B": ["02"]}), first[["B", "A"]]):
            with self.subTest(other=list(other)):
                container = WorkspaceSnapshot("wafer_map", {"input_data": first.copy()})
                description = pack_snapshot(container, "baseline", WorkspaceSnapshot("wafer_map", {"input_data": other}))
                self.assertEqual(len(container.frames), 2)
                pd.testing.assert_frame_equal(unpack_snapshot(container, description).frames["input_data"], other)
