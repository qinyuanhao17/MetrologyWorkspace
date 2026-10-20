"""Dirty checking preserves the existing JSON equality and validation rules."""
import unittest
import numpy as np
from metrology_app.workspace_document import same_snapshot
from metrology_app.workspace_store import WorkspaceSnapshot, json_text


class SnapshotEqualityTests(unittest.TestCase):
    @staticmethod
    def snapshot(value):
        return WorkspaceSnapshot("wafer_map", {}, {"ui": value})

    def test_state_comparison_matches_json_for_types_order_and_nested_values(self):
        values = [None, True, False, 0, 1, 0., -0., 1., "1", "晶圆\n\"", [], (),
                  [1, "001"], (1, "001"), {"a": 1, "b": "001"},
                  {"b": "001", "a": 1}, {"nested": [("REF", "DP"), [0., -0.]]},
                  np.int64(1), np.float32(.1), {1: "one"}, {"1": "one"}]
        for first in values:
            for second in values:
                left, right = self.snapshot(first), self.snapshot(second)
                with self.subTest(first=repr(first), second=repr(second)):
                    self.assertEqual(same_snapshot(left, right),
                                     json_text(left.states) == json_text(right.states))

    def test_invalid_equal_and_changed_states_still_use_json_validation(self):
        cyclic = []
        cyclic.append(cyclic)
        for value in (float("nan"), float("inf"), object(), cyclic,
                      {"changed": 1, "bad": float("nan")}):
            for other in (value, {"changed": 2}):
                left, right = self.snapshot(value), self.snapshot(other)
                with self.assertRaises((ValueError, TypeError)):
                    same_snapshot(left, right)

    def test_state_edits_and_accepted_baseline_mutation_are_not_cached(self):
        left = self.snapshot({"records": [{"id": "001", "key": "same"}]})
        right = self.snapshot({"records": [{"id": "001", "key": "same"}]})
        self.assertTrue(same_snapshot(left, right))
        right.states["ui"]["records"][0]["key"] = "changed"
        self.assertFalse(same_snapshot(left, right))
        left.states["ui"]["records"][0]["key"] = "changed"
        self.assertTrue(same_snapshot(left, right))
