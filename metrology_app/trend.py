"""Pure decisions for optional two-parameter Trend overlays."""

import re

import numpy as np
import pandas as pd


UNIT_SUFFIX = re.compile(r"[\[(]\s*([^\]()]+?)\s*[\])]\s*$")
RATIO_NAME = re.compile(r"ratio", re.IGNORECASE)
SIDEWALL_ANGLE_NAME = re.compile(r"swa", re.IGNORECASE)
# OCD model parameters are lengths unless their name says otherwise: sidewall
# angles are measured in degrees and *_ratio columns are dimensionless. Columns
# that are not model parameters never reach this module; `data.inspect_table`
# keeps the fit-quality and bookkeeping columns out of the parameter list.
LENGTH_UNIT = "nm"
RATIO_UNIT = "1"
ANGLE_UNIT = "degree"
# Two curves whose median magnitudes differ by more than this are unreadable on
# one axis even when they share a unit, so they get a linked second axis.
MAGNITUDE_RATIO_LIMIT = 10


def parse_unit(column_name):
    """Return the unit a Trend axis uses for an OCD parameter column.

    An explicit trailing unit such as ``EW (V)`` or ``Si_SWA [rad]`` always wins
    over the name rule, so a file that states its own unit stays authoritative.
    """
    name = str(column_name)
    match = UNIT_SUFFIX.search(name)
    if match is not None:
        unit = match.group(1).strip()
        return unit or None
    if not name.strip():
        return None
    if RATIO_NAME.search(name):
        return RATIO_UNIT
    if SIDEWALL_ANGLE_NAME.search(name):
        return ANGLE_UNIT
    return LENGTH_UNIT


def _magnitude(values):
    numeric = pd.to_numeric(pd.Series(values, dtype=object), errors="coerce")
    finite = np.abs(numeric.to_numpy(float))
    finite = finite[np.isfinite(finite)]
    return float(np.median(finite)) if finite.size else None


def overlay_spec(primary, secondary, primary_values=(), secondary_values=(),
                 ratio_limit=MAGNITUDE_RATIO_LIMIT, axis_mode="auto"):
    """Choose a shared or second Y axis from the requested policy.

    Auto separates different units and same-unit curves whose median absolute
    magnitudes exceed the editable ratio. Forced modes override that decision;
    mixed units on a forced single axis are marked for explicit plot labeling.
    """
    if axis_mode not in {"auto", "dual", "single"}:
        raise ValueError(f"Unknown Trend Y-axis mode: {axis_mode}")
    unit = parse_unit(primary)
    secondary_unit = parse_unit(secondary)
    warning = False
    first, second = _magnitude(primary_values), _magnitude(secondary_values)
    if first is not None and second is not None:
        low, high = sorted((first, second))
        warning = high > 0 and (low == 0 or high / low > ratio_limit)
    same_unit = unit is not None and unit == secondary_unit
    kind = ("shared" if axis_mode == "single" or
            (axis_mode == "auto" and same_unit and not warning)
            else "second-axis")
    return {
        "kind": kind,
        "unit": unit,
        "secondary_unit": secondary_unit,
        "magnitude_warning": warning,
        "mixed_units": kind == "shared" and not same_unit,
    }


def overlay_series(frame, groups, metric, keys):
    """Return one untouched numeric series per requested measurement set."""
    result = []
    for key in keys:
        rows = tuple(groups.get(key, ()))
        values = pd.to_numeric(frame.iloc[list(rows)][metric], errors="coerce")
        result.append({
            "key": key,
            "x": np.asarray(rows, dtype=float),
            "y": values.to_numpy(float),
        })
    return tuple(result)


__all__ = ["UNIT_SUFFIX", "overlay_series", "overlay_spec", "parse_unit"]
