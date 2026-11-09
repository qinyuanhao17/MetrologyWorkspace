"""Source-row-aligned absolute-Bias points; no spectral sample decoding."""
from dataclasses import dataclass
import json
import math

import numpy as np
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
        return (self.identity.die_seq or 0, self.key)


def out_of_range_rows(result, parameter):
    bias = result.series(parameter)["Bias"].to_numpy(float)
    rows = result.source_rows
    if len(rows) != len(bias):
        raise ValueError("Analysis source-row identities do not match the Bias values.")
    return {row for row, value in zip(rows, bias)
            if np.isfinite(value) and abs(value) > result.bias_limits[parameter]}


def die_map_points(raw, source_rows, metadata=()):
    """Join Wafer/Lot/PAD/Die to embedded XY; prefer explicitly labelled mm columns."""
    columns = {normalized(name): name for name in raw}
    def column(*aliases):
        return next((columns[a] for a in aliases if a in columns), None)
    identities = [column("waferid", "wafer", "waferno"), column("lotid", "lot"),
                  column("padname", "pad"), column("dieseq", "dieid", "dieorder", "die")]
    if identities[0] is None or identities[3] is None:
        raise ValueError("Die Map requires Wafer ID and Die Seq columns.")
    xy = column("xmm"), column("ymm")
    fields = column("fieldx", "colx", "refdiecol"), column("fieldy", "rowy", "refdierow")
    tool = column("toolsn")
    lookup = {}
    for record in metadata:
        data = json.loads(record) if isinstance(record, str) else record
        identity = data.get("identity", {})
        if not identity:
            continue  # Paths-only drafts contain no cached coordinates.
        try:
            pos = float(data["x_mm"]), float(data["y_mm"])
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(v) for v in pos):
            continue
        key = tuple(str(identity.get(k, "")).strip() for k in ("wafer", "lot", "pad")) + (canonical_die(identity.get("die_seq", "")),)
        lookup.setdefault(key, set()).add(pos)
    points, issues = [], []
    for row in source_rows:
        values = raw.iloc[row]
        def text(name):
            return "" if name is None or pd.isna(values[name]) else str(values[name]).strip()
        key = tuple(text(name) for name in identities[:3]) + (canonical_die(text(identities[3])),)
        try:
            if all(xy):
                pos = tuple(float(text(name)) for name in xy)
            else:
                candidates = lookup.get(key, set())
                if len(candidates) != 1:
                    raise ValueError("missing or ambiguous spectral XY")
                pos = next(iter(candidates))
            if not all(math.isfinite(v) for v in pos):
                raise ValueError("non-finite XY")
            die = int(key[3])
            field_values = [int(canonical_die(text(name))) if name and text(name) else None for name in fields]
        except (TypeError, ValueError) as error:
            issues.append(f"Source row {row + 1}: {error}")
            continue
        identity = SpectrumIdentity(key[0], key[1], key[2], die, "", tool_sn=text(tool),
                                    field_x=field_values[0], field_y=field_values[1])
        points.append(DieMapPoint(f"source-row:{row}", identity, *pos))
    return tuple(points), tuple(issues)


def refresh_bias_map(owner, window, parameter):
    result = owner.result
    selected_rows = out_of_range_rows(result, parameter)
    signature = (id(owner._active_raw_frame()), id(result), tuple(result.source_rows),
                 tuple((name, id(frame)) for name, frame in owner._workspace_frames.items() if name.endswith(".spectra")),
                 tuple((name, id(viewer.catalog.spectra)) for name, viewer in owner._spectra_windows.items()))
    if getattr(window, "_bias_points_signature", None) != signature:
        metadata = []
        for name, frame in owner._workspace_frames.items():
            if name.endswith(".spectra") and name[:-8] not in owner._spectra_windows and "metadata" in frame:
                metadata.extend(frame["metadata"])
        for viewer in owner._spectra_windows.values():
            metadata.extend({"identity": {name: getattr(s.identity, name) for name in ("wafer", "lot", "pad", "die_seq")},
                             "x_mm": s.x_mm, "y_mm": s.y_mm} for s in viewer.catalog.spectra)
        window._bias_points, window._bias_issues = die_map_points(owner._active_raw_frame(), result.source_rows, metadata)
        window._bias_points_signature = signature
    points = window._bias_points
    selected = {f"source-row:{row}" for row in selected_rows}
    wafers = {(p.identity.wafer, p.identity.lot, p.identity.pad) for p in points if p.key in selected}
    context = tuple(p for p in points if (p.identity.wafer, p.identity.lot, p.identity.pad) in wafers)
    window.set_data(context, checked_keys=selected)
    window.setWindowTitle(f"{parameter} — Out-of-range Die Map")
    window.empty.setText("No out-of-range points." if not selected else "No matching XY coordinates in mm. Load spectra or supply X (mm) / Y (mm).")
    missing = len(selected - {p.key for p in points})
    window.statusBar().showMessage(f"{len(selected_rows)} out-of-range rows · {missing} missing XY · Red: out of range · Gray: other points")
    window.statusBar().setToolTip("\n".join(window._bias_issues))


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
