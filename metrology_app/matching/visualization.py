"""Truthful bounded sampling for interactive matching plots."""

import numpy as np


def extrema_sample_indices(*series, limit):
    """Return source-order indices that retain local minima and maxima per bucket."""
    if not series:
        return np.array([], dtype=np.int64)
    arrays = [np.asarray(values, dtype=float) for values in series]
    size = len(arrays[0])
    if any(len(values) != size for values in arrays):
        raise ValueError("Plot series must have the same length.")
    if size <= limit:
        return np.arange(size, dtype=np.int64)
    if limit < 2:
        raise ValueError("Plot sample limit must be at least 2.")
    bucket_count = max(1, (limit - 2) // (2 * len(arrays)))
    edges = np.linspace(0, size, bucket_count + 1, dtype=np.int64)
    chosen = {0, size - 1}
    for start, stop in zip(edges[:-1], edges[1:]):
        if stop <= start:
            continue
        for values in arrays:
            segment = values[start:stop]
            finite = np.flatnonzero(np.isfinite(segment))
            if not len(finite):
                continue
            finite_values = segment[finite]
            chosen.add(start + int(finite[np.argmin(finite_values)]))
            chosen.add(start + int(finite[np.argmax(finite_values)]))
    return np.asarray(sorted(chosen), dtype=np.int64)


__all__ = ["extrema_sample_indices"]