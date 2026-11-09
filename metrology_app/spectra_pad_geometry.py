"""Axis-aligned PAD outlines inferred from measured Field and millimetre pairs."""
from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True)
class PadLayout:
    segments: tuple = ()
    width_mm: float | None = None
    height_mm: float | None = None
    issue: str = ""


def pad_layout(spectra, *, radius_mm=150):
    """Use three reference points for a common size rounded to 0.01 mm.

    Prefer Fields (0,0), (1,0), (0,1); otherwise use an available reference
    and its nearest same-row/column neighbours, dividing by Field intervals.
    PAD Field (0,0) starts at (0,0); measured points retain their absolute XY.
    Draw full grid chords clipped to the wafer circle, including empty cells.
    """
    if not math.isfinite(radius_mm) or radius_mm <= 0:
        raise ValueError("Wafer radius must be positive and finite in mm.")
    records = [(s.identity.field_x, s.identity.field_y, s.x_mm, s.y_mm)
               for s in spectra if s.has_map_point and s.identity.field_x is not None
               and s.identity.field_y is not None]
    if not records:
        return PadLayout(issue="PAD outlines unavailable: missing Field X/Y coordinates.")
    values = np.asarray(records, dtype=float)
    if not np.isfinite(values).all():
        return PadLayout(issue="PAD outlines unavailable: non-finite coordinates.")
    points = {}
    for column, row, x, y in records:
        points.setdefault((column, row), (x, y))
    steps = None
    for column, row in sorted(points, key=lambda p: (abs(p[0]) + abs(p[1]), p)):
        horizontal = [p for p in points if p[1] == row and p[0] != column]
        vertical = [p for p in points if p[0] == column and p[1] != row]
        if not horizontal or not vertical:
            continue
        h = min(horizontal, key=lambda p: (abs(p[0] - column), p[0] < column, p))
        v = min(vertical, key=lambda p: (abs(p[1] - row), p[1] < row, p))
        x, y = points[column, row]
        steps = [round((points[h][0] - x) / (h[0] - column), 2),
                 round((points[v][1] - y) / (v[1] - row), 2)]
        break
    if steps is None or min(steps) <= 0:
        return PadLayout(issue="PAD outlines unavailable: need three reference points with positive width/height.")
    segments = []
    # One chord per grid line: shared cell borders cannot be drawn twice.
    for vertical, step in ((False, steps[1]), (True, steps[0])):
        for index in range(math.ceil(-radius_mm / step), math.floor(radius_mm / step) + 1):
            level = index * step
            extent = math.sqrt(max(0, radius_mm ** 2 - level ** 2))
            if extent > 0:
                segments.append((level, -extent, level, extent) if vertical else
                                (-extent, level, extent, level))
    return PadLayout(tuple(segments), *steps)
