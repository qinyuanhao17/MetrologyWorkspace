"""Composite keys retain Raw order and never guess ambiguous matches."""
import unittest
import pandas as pd
from metrology_app.id_matching import align_by_id


KEYS = {"reference": ["WaferID", "Col/X", "Row/Y"], "raw": ["Wafer ID", "FIELD X", "FIELD Y"]}


class IDMatchingTests(unittest.TestCase):
    def test_shuffled_unequal_sources_keep_raw_rows_and_literal_reference(self):
        ref = pd.DataFrame({"WaferID": ["001"]*3, "Col/X": ["2", "1", "9"], "Row/Y": ["0"]*3,
                            "Value": ["4.1000", "2.1000", "99.000"]})
        raw = pd.DataFrame({"Wafer ID": ["001"]*4, "FIELD X": ["1.0", "3", "2", "4"], "FIELD Y": ["-0"]*4})
        before = ref.copy(deep=True)
        result = align_by_id(ref, raw, KEYS)
        self.assertEqual(result.reference_rows, (1, None, 0, None))
        self.assertEqual(result.reference["Value"].tolist(), ["2.1000", "", "4.1000", ""])
        self.assertEqual(result.unused_reference, 1)
        pd.testing.assert_frame_equal(ref, before)

    def test_duplicate_and_blank_ids_are_reported_and_excluded_on_both_sides(self):
        ref = pd.DataFrame({"id": ["a", "a", "b", "c", ""], "Value": [1,2,3,4,5]})
        raw = pd.DataFrame({"key": ["a", "b", "b", "c", "", "unknown"]})
        result = align_by_id(ref, raw, {"reference": ["id"], "raw": ["key"]})
        self.assertEqual(result.reference_rows, (None, None, None, 3, None, None))
        self.assertEqual(result.duplicate_reference, (0,1))
        self.assertEqual(result.duplicate_raw, (1,2))
        self.assertEqual(result.blank_reference, (4,))
        self.assertEqual(result.blank_raw, (4,))

    def test_key_order_and_boundaries_are_explicit_and_leading_zeros_stay_literal(self):
        ref = pd.DataFrame({"a": ["ab", "a", "001"], "b": ["c", "bc", "0"]})
        raw = pd.DataFrame({"x": ["a", "ab", "1"], "y": ["bc", "c", "0"]})
        result = align_by_id(ref, raw, {"reference": ["a", "b"], "raw": ["x", "y"]})
        self.assertEqual(result.reference_rows, (1,0,None))
        for keys in ({}, {"reference":["a"], "raw":["x","y"]}, {"reference":["gone"],"raw":["x"]}):
            with self.assertRaises(ValueError):
                align_by_id(ref, raw, keys)
