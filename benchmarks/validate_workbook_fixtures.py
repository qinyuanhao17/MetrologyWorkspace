"""Validate real WKB/CSV fixtures without changing originals or preferences.

python -m benchmarks.validate_workbook_fixtures --workbooks DIRECTORY
Checks full snapshot round trips, independent finite-pair fits and source hashes.
This supplements, not replaces, GUI workflow and numerical regression tests.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

from metrology_app.data import read_table
from metrology_app.matching import MatchWorkbook
from metrology_app.workspace_document import same_snapshot
from metrology_app.workspace_store import load_workspace, save_workspace


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_fit(card, x, y):
    finite = np.isfinite(x) & np.isfinite(y)
    x, y = x[finite], y[finite]
    if card is None:
        assert len(x) < 2 or np.ptp(x) == 0
        return
    assert card.valid_pairs == len(x)
    if len(x) < 2 or np.ptp(x) == 0:
        assert np.isnan(card.slope) and np.isnan(card.intercept)
        return
    dx, dy = x - x.mean(), y - y.mean()
    slope = float(np.dot(dx, dy) / np.dot(dx, dx))
    intercept = float(y.mean() - slope * x.mean())
    np.testing.assert_allclose([card.slope, card.intercept], [slope, intercept], rtol=1e-8, atol=1e-8)
    if np.dot(dy, dy) > 0:
        residual = y - (x * slope + intercept)
        rsq = 1 - float(np.dot(residual, residual) / np.dot(dy, dy))
        np.testing.assert_allclose(card.r_squared, rsq, rtol=1e-8, atol=1e-8)


def expected_rows(book, raw):
    state = book.grouping_state.get("applied", book.grouping_state)
    # Current real fixtures use participation rather than legacy view filters.
    # Reject unsupported oracle coverage instead of silently asking GroupPlan.
    if state.get("filters"):
        raise ValueError("Fixture oracle does not cover legacy analysis filters")
    selection = state.get("data_selection")
    if selection is None:
        return tuple(range(len(raw)))
    records = selection["records"]
    assert len(records) == len(raw), "Participation records must align with fixture source rows"
    excluded = set(selection["excluded"])
    seen, included = Counter(), []
    for row, record in enumerate(records):
        columns, values, occurrence = json.loads(record["key"])
        actual = tuple("" if pd.isna(raw.iloc[row][column]) else str(raw.iloc[row][column]).strip()
                       for column in columns) if columns else ("row", str(row))
        assert actual == tuple(values), "Persisted identity disagrees with fixture source"
        assert occurrence == seen[(tuple(columns), actual)]
        seen[(tuple(columns), actual)] += 1
        if record["id"] not in excluded:
            included.append(row)
    return tuple(included)


def validate_fits(book):
    result = book.analyze()
    raw = book.final_match_raw if book.result_mode == "final" and book.final_match_raw is not None else book.raw
    rows = expected_rows(book, raw)
    assert result.source_rows == rows, "Wrong analysis participation/order"
    for mapping in book.mappings:
        parameter = mapping.name
        source_x = pd.to_numeric(raw[mapping.raw_column], errors="coerce").to_numpy(float)
        source_y = pd.to_numeric(book.reference[mapping.reference_column], errors="coerce").to_numpy(float)
        x, y = source_x[list(rows)], source_y[list(rows)]
        card = result.card(parameter)
        assert_fit(card, x, y)
        series = result.series(parameter)
        calibrated = x * card.slope + card.intercept
        evaluated = calibrated if book.result_mode == "preview" else x
        bias = evaluated - y
        percent = np.full(len(y), np.nan)
        np.divide(bias * 100, y, out=percent, where=np.isfinite(y) & (y != 0))
        for name, expected in (("Raw", x), ("Reference", y), ("Card Value", calibrated),
                               ("Evaluated Value", evaluated), ("Bias", bias), ("Bias %", percent)):
            np.testing.assert_allclose(series[name], expected, rtol=1e-8, atol=1e-8)
        for key in result.group_plan.plot_group_keys:
            scope_rows = result.group_plan.rows(key)
            assert len(scope_rows) == len(set(scope_rows)), "Group duplicates a source row"
            assert set(scope_rows).issubset(rows), "Group includes an excluded source row"
            scope = result.plot_scope(scope_rows, local_card=True)
            assert_fit(scope.card(parameter), source_x[list(scope_rows)], source_y[list(scope_rows)])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbooks", required=True, type=Path)
    args = parser.parse_args()
    paths = sorted(args.workbooks.glob("*.wkb"))
    if not paths:
        parser.error("No WKB fixtures found")
    with tempfile.TemporaryDirectory(prefix="metrology-fixtures-") as scratch:
        for path in paths:
            before = digest(path)
            snapshot = load_workspace(path, expected_type="match_workbook")
            book = MatchWorkbook.from_snapshot(snapshot)
            result = validate_fits(book)
            copy = Path(scratch) / path.name
            save_workspace(copy, snapshot)
            restored = load_workspace(copy)
            assert same_snapshot(snapshot, restored), path.name
            for name, frame in snapshot.frames.items():
                pd.testing.assert_frame_equal(frame, restored.frames[name])
            validate_fits(MatchWorkbook.from_snapshot(restored))
            assert digest(path) == before, f"Source changed: {path}"
            print(json.dumps({"file": path.name, "type": book.match_type, "rows": len(book.raw),
                              "included": len(result.source_rows), "parameters": len(result.parameter_names),
                              "roundtrip": "pass", "independent_fits": "pass", "sha256": before}), flush=True)
        samples = Path(__file__).resolve().parents[1] / "sample_data"
        for path in sorted(samples.glob("*.csv")):
            before = digest(path)
            frame = read_table(path)
            assert len(frame) and len(frame.columns), path.name
            assert digest(path) == before
            print(json.dumps({"sample": path.name, "rows": len(frame), "columns": len(frame.columns),
                              "import": "pass", "sha256": before}), flush=True)


if __name__ == "__main__":
    main()
