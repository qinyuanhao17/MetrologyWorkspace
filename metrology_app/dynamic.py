"""Cycle inference and per-die repeatability statistics for Dynamic tests."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd


_DYNAMIC_RUN = re.compile(r"(?:^|[\\/])dynamic[\\/]([^\\/]+)", re.IGNORECASE)


def _is_report_separator(column):
    text = "" if column is None else str(column).strip()
    return not text or text.lower() == "nan" or text.lower().startswith("unnamed:")


def _cycle_from_run_paths(frame, path_column):
    if path_column not in frame or frame.empty:
        return None
    tokens = frame[path_column].fillna("").astype(str).map(
        lambda value: (_DYNAMIC_RUN.search(value).group(1)
                       if _DYNAMIC_RUN.search(value) else "")
    )
    if not tokens.ne("").all():
        return None
    order = {}
    return tokens.map(lambda token: order.setdefault(token, len(order) + 1)).astype(int)


def _cycle_from_die_order(frame, die_column):
    if die_column not in frame:
        raise ValueError(f"Dynamic data requires a {die_column!r} column.")
    cycle = 1
    seen = set()
    result = []
    for position, value in enumerate(frame[die_column]):
        key = str(value).strip() if not pd.isna(value) else f"<missing:{position}>"
        if key in seen:
            cycle += 1
            seen.clear()
        seen.add(key)
        result.append(cycle)
    return pd.Series(result, index=frame.index, dtype=int)


def prepare_dynamic_frame(
    frame,
    *,
    die_column="Die Seq",
    path_column="Cur SME File Path",
    cycle_column="Cycle",
):
    """Return source measurement columns plus an inferred one-based Cycle.

    Old pasted pivot reports are commonly separated from the raw columns by an
    empty Excel column. Everything from that separator onward is deliberately
    discarded so report values cannot be selected as fresh measurements.
    """
    prepared = pd.DataFrame(frame).copy()
    if prepared.empty and not len(prepared.columns):
        return prepared.reset_index(drop=True)
    separator = next(
        (index for index, column in enumerate(prepared.columns)
         if _is_report_separator(column)),
        len(prepared.columns),
    )
    prepared = prepared.iloc[:, :separator].copy()
    if cycle_column in prepared:
        prepared = prepared.drop(columns=[cycle_column])
    cycles = _cycle_from_run_paths(prepared, path_column)
    if cycles is None:
        cycles = _cycle_from_die_order(prepared, die_column)
    die_position = prepared.columns.get_loc(die_column)
    prepared.insert(die_position + 1, cycle_column, cycles.to_numpy())
    return prepared.reset_index(drop=True)


def _sort_measurement_labels(values):
    def key(value):
        try:
            return (0, float(value), str(value))
        except (TypeError, ValueError):
            return (1, 0.0, str(value))
    return sorted(values, key=key)


def dynamic_pivot(
    frame,
    parameter,
    *,
    die_column="Die Seq",
    cycle_column="Cycle",
):
    """Build Cycle × Die values and append per-die sample 3σ as the last row."""
    required = (cycle_column, die_column, parameter)
    missing = [column for column in required if column not in frame]
    if missing:
        raise ValueError(f"Dynamic data is missing: {', '.join(missing)}")
    values = frame.loc[:, required].copy()
    values[parameter] = pd.to_numeric(values[parameter], errors="coerce")
    values = values.dropna(subset=[cycle_column, die_column, parameter])
    if values.duplicated([cycle_column, die_column]).any():
        raise ValueError(
            "Dynamic data contains a duplicate Cycle / Die Seq pair; "
            "split the measurement set instead of averaging it."
        )
    if values.empty:
        raise ValueError(f"{parameter} has no numeric Dynamic values.")
    pivot = values.pivot(index=cycle_column, columns=die_column, values=parameter)
    pivot = pivot.reindex(
        index=_sort_measurement_labels(pivot.index),
        columns=_sort_measurement_labels(pivot.columns),
    )
    pivot.loc["3 Sigma"] = pivot.std(axis=0, ddof=1) * 3.0
    pivot.index.name = cycle_column
    pivot.columns.name = die_column
    return pivot


__all__ = ["dynamic_pivot", "prepare_dynamic_frame"]
