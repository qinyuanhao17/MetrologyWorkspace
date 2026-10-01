"""Pure decisions for optional two-parameter Trend overlays."""

import re

import numpy as np
import pandas as pd


UNIT_SUFFIX = re.compile(r"[\[(]\s*([^\]()]+?)\s*[\])]\s*$")


def parse_unit(column_name):
    """Return an explicit trailing unit without guessing from the name."""
    match = UNIT_SUFFIX.search(str(column_name))
    if match is None:
        return None
    unit = match.group(1).strip()
    return unit or None


def _magnitude(values):
    numeric = pd.to_numeric(pd.Series(values, dtype=object), errors="coerce")
    finite = np.abs(numeric.to_numpy(float))
    finite = finite[np.isfinite(finite)]
    return float(np.median(finite)) if finite.size else None


def overlay_spec(primary, secondary, primary_values=(), secondary_values=()):
    """Choose a shared or second Y axis from explicit units and magnitudes."""
    unit = parse_unit(primary)
    secondary_unit = parse_unit(secondary)
    shared = unit is not None and secondary_unit is not None and unit == secondary_unit
    warning = False
    if not shared:
        first, second = _magnitude(primary_values), _magnitude(secondary_values)
        if first is not None and second is not None:
            low, high = sorted((first, second))
            warning = high > 0 and (low == 0 or high / low > 10)
    return {
        "kind": "shared" if shared else "second-axis",
        "unit": unit,
        "secondary_unit": secondary_unit,
        "magnitude_warning": warning,
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
