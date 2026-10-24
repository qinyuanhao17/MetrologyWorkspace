"""Dirty checking preserves the existing JSON equality and validation rules."""
import unittest
from copy import deepcopy
from time import perf_counter
import random
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

    def test_large_unchanged_record_identity_state_compares_promptly(self):
        # Representative wide-table row identities contain literal measurement
        # strings, including the JSON quotation marks that must be preserved.
        measurements = ["1.123456789000000"] * 33
        records = [{"key": json_text([f"W{i // 20:06}", f"{i % 20 + 1:02}", measurements]),
                    "id": str(i)} for i in range(20000)]
        current = self.snapshot({"records": records})
        accepted = deepcopy(current)
        times = []
        for _ in range(3):
            start = perf_counter()
            self.assertTrue(same_snapshot(current, accepted))
            times.append(perf_counter() - start)
        self.assertLess(min(times), .06, f"Unchanged record identities blocked dirty checking: {times}")
        accepted.states["ui"]["records"][-1]["id"] = "edited-baseline"
        times = []
        for _ in range(3):
            start = perf_counter()
            self.assertFalse(same_snapshot(current, accepted))
            times.append(perf_counter() - start)
        self.assertLess(min(times), .06, f"A late state edit blocked dirty checking: {times}")

    def test_early_difference_does_not_skip_invalid_later_state(self):
        for value in (float("nan"), float("inf"), object()):
            for valid, invalid in ((1, value), (value, 1)):
                with self.subTest(value=type(value).__name__, left_invalid=valid is value):
                    with self.assertRaises((ValueError, TypeError)):
                        same_snapshot(self.snapshot({"first": "A", "last": valid}),
                                      self.snapshot({"first": "B", "last": invalid}))

    def test_nested_states_keep_encoder_equality_and_errors(self):
        rng = random.Random(420)
        leaves = [None, True, False, 0, 1, 0., -0., .1, 2**64 - 1, 2**64,
                  "001.000", '晶圆\\\n"', "\ud83d\ude00", "\U0001f600",
                  float("nan"), float("inf"), np.int64(1), np.float32(.1)]

        def value(depth):
            kind = rng.randrange(4) if depth else 0
            if kind == 0:
                return rng.choice(leaves)
            items = [value(depth - 1) for _ in range(rng.randrange(4))]
            if kind == 1:
                return items
            if kind == 2:
                return tuple(items)
            return {str(index): item for index, item in enumerate(items)}

        def outcome(compare):
            try:
                return compare()
            except (TypeError, ValueError) as error:
                return type(error)

        for index in range(500):
            left = self.snapshot(value(4))
            right = deepcopy(left) if index % 2 else self.snapshot(value(4))
            with self.subTest(index=index):
                expected = outcome(lambda: json_text(left.states) == json_text(right.states))
                self.assertEqual(outcome(lambda: same_snapshot(left, right)), expected)
        # Respect the runtime's integer-to-text limit rather than accepting a
        # large equal integer that the document encoder may reject.
        for number in (2**64, 1 << 20000):
            left, right = self.snapshot(number), self.snapshot(number)
            self.assertEqual(outcome(lambda: same_snapshot(left, right)),
                             outcome(lambda: json_text(left.states) == json_text(right.states)))
