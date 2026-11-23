"""Identity preparation remains byte-for-byte compatible with saved workbooks."""
from collections import Counter
import json
import unittest

import numpy as np
import pandas as pd
from metrology_app.match_groups import participation_rows, participation_source_keys, row_identity_columns, row_ids


class IdentityKeyNormalizationTests(unittest.TestCase):
    def test_numeric_die_aliases_match_only_unambiguous_participation_records(self):
        raw = pd.DataFrame({"Wafer ID": ["W1", "W1", "W2"], "Die Seq": ["01", "1", "1"]})
        selection = {"records": [{"id": str(index), "key": key} for index, key in enumerate(row_ids(raw))],
                     "excluded": ["0", "2"]}
        # W1's two original records have distinct literal IDs. An alias may
        # reuse W2's unique record without transferring an ambiguous W1 choice.
        aliases = raw.assign(**{"Die Seq": ["001", "1", "1.0"]})
        self.assertEqual(participation_rows(aliases, selection), (0, 1))
        self.assertEqual(participation_rows(raw, selection), (1,))

    def test_literal_identity_keys_match_original_row_encoding(self):
        fixtures = [
            pd.DataFrame({"Wafer ID": [" 001 ", "001", None, "晶圆"],
                          "Lot ID": [" L "] * 4, "Die Seq": ["01", "01", np.nan, " 3 "],
                          "Cur SME File Path": [" a.sme ", "b.sme", "", "x.sme"],
                          "CD": ["1.0000"] * 4}),
            pd.DataFrame({"Cur SME File Path": ["a", "a", None], "CD": ["1.00"] * 3}),
            pd.DataFrame({"CD": ["1.00", "2.00", "3.00"]}),
            pd.DataFrame({"Wafer ID": pd.Series([], dtype=object)}),
        ]
        fixtures.extend([fixtures[0].iloc[[1, 3]].reset_index(drop=True),
                         fixtures[0].iloc[::-1].reset_index(drop=True)])
        for frame in fixtures:
            columns = row_identity_columns(frame)
            seen, keys = Counter(), []
            for index, row in enumerate(frame[columns].fillna("").astype(str).values):
                values = tuple(str(v).strip() for v in row) if columns else ("row", str(index))
                keys.append(json.dumps([tuple(columns), values, seen[values]], ensure_ascii=False))
                seen[values] += 1
            if "Cur SME File Path" in frame:
                paths = frame["Cur SME File Path"].fillna("").astype(str).str.strip()
                keys = [json.dumps([key, path], ensure_ascii=False) for key, path in zip(keys, paths)]
            original = frame.copy(deep=True)
            self.assertEqual(participation_source_keys(frame.copy()), tuple(keys))
            pd.testing.assert_frame_equal(frame, original)
