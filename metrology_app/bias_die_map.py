"""Plot absolute Bias exceedances at their original measurement positions."""
from collections import defaultdict
from dataclasses import dataclass
import json
import math

import pandas as pd

from .match_groups import normalized
from .selection_script import canonical_die
from .sme_spectra import SpectrumIdentity


@dataclass(frozen=True)
class DieMapPoint:
    key: str
    identity: SpectrumIdentity
    x_mm: float
    y_mm: float

    @property
    def has_map_point(self):
        return True

    @property
    def sort_key(self):
        return self.identity.die_seq, self.key


def _coordinates(x, y):
    try:
        pair = float(x), float(y)
    except (TypeError, ValueError):
        return None
    return pair if all(math.isfinite(value) for value in pair) else None


def _field_index(value):
    try:
        return int(canonical_die(value))
    except ValueError:
        return None


def _text(value):
    return "" if pd.isna(value) else str(value).strip()


def _missing_point(row):
    return f"Source row {row + 1}: missing identity or missing/ambiguous XY in mm."


def die_map_points(raw, source_rows, metadata=(), *, effective_raw=None):
    """Resolve coordinates by source row and accept either Wafer ID for SME lookup."""
    columns = {normalized(name): name for name in raw}

    def column(*aliases):
        return next((columns[alias] for alias in aliases if alias in columns), None)

    wafer = column("waferid", "wafer", "waferno")
    die = column("dieseq", "dieid", "dieorder", "die")
    if wafer is None or die is None:
        raise ValueError("Die Map requires Wafer ID and Die Seq columns.")
    lot, pad = column("lotid", "lot"), column("padname", "pad")
    x_mm, y_mm = column("xmm"), column("ymm")
    field_x = column("fieldx", "colx", "refdiecol")
    field_y = column("fieldy", "rowy", "refdierow")
    lookup = defaultdict(set)
    for identity, x, y in metadata:
        position = _coordinates(x, y)
        if position is not None:
            key = (identity.wafer.strip(), identity.lot.strip(), identity.pad.strip(),
                   canonical_die(identity.die_seq))
            lookup[key].add(position)

    if (x_mm is None or y_mm is None) and not lookup:
        return (), tuple(_missing_point(row) for row in source_rows)

    # Row Series inherit a deep copy of the DataFrame's attrs, including the
    # entire Wafer ID mapping. Read the required columns once instead.
    values = {name: raw[name].to_numpy(copy=False)
              for name in {wafer, die, lot, pad, x_mm, y_mm, field_x, field_y} if name is not None}
    mapped_wafer = (effective_raw[wafer].to_numpy(copy=False)
                    if effective_raw is not None and effective_raw is not raw else values[wafer])

    def text(name, row):
        return "" if name is None else _text(values[name][row])

    points, issues = [], []
    for row in source_rows:
        source_wafer, display_wafer = text(wafer, row), _text(mapped_wafer[row])
        lot_id, pad_name, die_text = text(lot, row), text(pad, row), canonical_die(text(die, row))
        die_number = _field_index(die_text)
        position = _coordinates(text(x_mm, row), text(y_mm, row))
        if position is None:
            candidates = (lookup.get((source_wafer, lot_id, pad_name, die_text), set())
                          | lookup.get((display_wafer, lot_id, pad_name, die_text), set()))
            if len(candidates) == 1:
                position = next(iter(candidates))
        if not display_wafer or die_number is None or position is None:
            issues.append(_missing_point(row))
            continue
        identity = SpectrumIdentity(display_wafer, lot_id, pad_name, die_number, "",
                                    field_x=_field_index(text(field_x, row)), field_y=_field_index(text(field_y, row)))
        points.append(DieMapPoint(f"source-row:{row}", identity, *position))
    return tuple(points), tuple(issues)


def _saved_coordinates(frames):
    for frame in frames:
        for record in frame["metadata"]:
            data = json.loads(record)
            if data.get("identity"):
                yield SpectrumIdentity(**data["identity"]), data.get("x_mm"), data.get("y_mm")


def bias_map_points(owner):
    """Share resolved coordinates across the current stage's parameter maps."""
    result = owner.result
    mode = result.result_mode
    workbook = owner.workbook
    raw = workbook.final_match_raw if mode == "final" else workbook.raw
    if raw is None:
        raw = workbook.raw
    effective = result.group_plan.raw
    rows = result.source_rows
    prefix = f"spectra.{mode}"

    def same_stage(scope):
        return scope == prefix or scope.startswith(prefix + ".")

    live = tuple(viewer.catalog.spectra for scope, viewer in owner._spectra_windows.items()
                 if same_stage(scope))
    saved = tuple(frame for name, frame in owner._workspace_frames.items()
                  if name.endswith(".spectra") and same_stage(name[:-8])
                  and name[:-8] not in owner._spectra_windows and "metadata" in frame)
    inputs = (raw, effective, *live, *saved)
    cached = owner._bias_map_cache
    if cached is not None:
        previous, previous_rows, coordinates = cached
        if rows == previous_rows and len(inputs) == len(previous) and all(a is b for a, b in zip(inputs, previous)):
            return coordinates
    metadata = [(s.identity, s.x_mm, s.y_mm) for spectra in live for s in spectra]
    metadata.extend(_saved_coordinates(saved))
    coordinates = die_map_points(raw, rows, metadata, effective_raw=effective)
    owner._bias_map_cache = inputs, rows, coordinates
    return coordinates


def refresh_bias_map(owner, window, parameter):
    result = owner.result
    values = result.series(parameter)["Bias"].to_numpy(float)
    limit = result.bias_limits[parameter]
    selected = {f"source-row:{row}" for row, value in zip(result.source_rows, values, strict=True)
                if math.isfinite(value) and abs(value) > limit}
    points, issues = bias_map_points(owner)

    def wafer_key(point):
        identity = point.identity
        return identity.wafer, identity.lot, identity.pad

    wafers = {wafer_key(point) for point in points if point.key in selected}
    context = tuple(point for point in points if wafer_key(point) in wafers)
    located = selected.intersection(point.key for point in points)
    window.set_data(context, checked_keys=located)
    window.setWindowTitle(f"{parameter} — Out-of-range Die Map")
    window.empty.setText("No matching XY coordinates in mm." if selected else "No out-of-range points.")
    window.statusBar().showMessage(
        f"{len(selected)} out-of-range rows · {len(selected - located)} missing XY · Red: out of range · Gray: other points")
    window.statusBar().setToolTip("\n".join(issues[:20]))


def open_bias_map(owner, parameter):
    from PyQt6 import sip
    from .spectra_map import SpectraMapWindow
    window = owner._bias_die_maps.get(parameter)
    if window is None or sip.isdeleted(window):
        window = SpectraMapWindow(owner, read_only=True)
        owner._bias_die_maps[parameter] = window
    refresh_bias_map(owner, window, parameter)
    window.show()
    window.raise_()
    return window
