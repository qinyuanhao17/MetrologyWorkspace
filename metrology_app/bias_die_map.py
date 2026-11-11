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

    points, issues = [], []
    for row in source_rows:
        record = raw.iloc[row]

        def text(name):
            return "" if name is None or pd.isna(record[name]) else str(record[name]).strip()

        source_wafer = text(wafer)
        display_wafer = source_wafer if effective_raw is None else str(effective_raw.iloc[row][wafer]).strip()
        lot_id, pad_name, die_text = text(lot), text(pad), canonical_die(text(die))
        die_number = _field_index(die_text)
        position = _coordinates(text(x_mm), text(y_mm))
        if position is None:
            candidates = (lookup.get((source_wafer, lot_id, pad_name, die_text), set())
                          | lookup.get((display_wafer, lot_id, pad_name, die_text), set()))
            if len(candidates) == 1:
                position = next(iter(candidates))
        if not display_wafer or die_number is None or position is None:
            issues.append(f"Source row {row + 1}: missing identity or missing/ambiguous XY in mm.")
            continue
        identity = SpectrumIdentity(display_wafer, lot_id, pad_name, die_number, "",
                                    field_x=_field_index(text(field_x)), field_y=_field_index(text(field_y)))
        points.append(DieMapPoint(f"source-row:{row}", identity, *position))
    return tuple(points), tuple(issues)


def _saved_coordinates(frames):
    for frame in frames:
        for record in frame["metadata"]:
            data = json.loads(record)
            if data.get("identity"):
                yield SpectrumIdentity(**data["identity"]), data.get("x_mm"), data.get("y_mm")


def refresh_bias_map(owner, window, parameter):
    result = owner.result
    mode = result.result_mode
    workbook = owner.workbook
    raw = workbook.final_match_raw if mode == "final" else workbook.raw
    if raw is None:
        raw = workbook.raw
    effective = result.group_plan.raw
    rows = result.source_rows
    values = result.series(parameter)["Bias"].to_numpy(float)
    limit = result.bias_limits[parameter]
    selected = {f"source-row:{row}" for row, value in zip(rows, values, strict=True)
                if math.isfinite(value) and abs(value) > limit}

    prefix = f"spectra.{mode}"

    def same_stage(scope):
        return scope == prefix or scope.startswith(prefix + ".")

    live = tuple(viewer.catalog.spectra for scope, viewer in owner._spectra_windows.items()
                 if same_stage(scope))
    saved = tuple(frame for name, frame in owner._workspace_frames.items()
                  if name.endswith(".spectra") and same_stage(name[:-8])
                  and name[:-8] not in owner._spectra_windows and "metadata" in frame)
    inputs = (raw, effective, *live, *saved)
    previous, previous_rows = getattr(window, "_bias_map_inputs", ((), ()))
    if (rows != previous_rows or len(inputs) != len(previous)
            or any(a is not b for a, b in zip(inputs, previous))):
        metadata = [(s.identity, s.x_mm, s.y_mm) for spectra in live for s in spectra]
        metadata.extend(_saved_coordinates(saved))
        window._bias_points, window._bias_issues = die_map_points(raw, rows, metadata, effective_raw=effective)
        window._bias_map_inputs = inputs, rows
    points = window._bias_points

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
    window.statusBar().setToolTip("\n".join(window._bias_issues[:20]))


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
