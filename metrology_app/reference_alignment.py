"""Literal-row wafer alignment, explicit coordinate units and paired Bias trends."""
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .reference_merge import compact
from .file_paths import filesystem_path


@dataclass(frozen=True)
class AlignmentColumns:
    wafer: str | None = None
    lot: str | None = None
    pad: str | None = None
    field_x: str | None = None
    field_y: str | None = None
    x: str | None = None
    y: str | None = None
    unit: str = ""


def infer_alignment_columns(frame, vendor="Raw"):
    names = {compact(c).replace('µ', 'u').replace('μ', 'u'): c for c in frame}
    def find(*aliases):
        return next((names[a] for a in aliases if a in names), None)
    x = find("xmm", "xum", "xnm", "mpointx", "epointx", "waferx", "x")
    y = find("ymm", "yum", "ynm", "mpointy", "epointy", "wafery", "y")
    unit = next((unit for unit, suffix in (("mm", "mm"), ("µm", "um"), ("nm", "nm"))
                 if x and y and compact(x).replace('µ','u').replace('μ','u') == "x" + suffix
                 and compact(y).replace('µ','u').replace('μ','u') == "y" + suffix), "")
    pad = find("padname", "pad", "sitename")
    if pad is None and vendor == "KLA":
        pad = find("slot")
    return AlignmentColumns(find("waferid", "wafer", "waferno"), find("lotid", "lot"), pad,
                            find("fieldx", "refdiecol", "colx", "chipx", "diecol"),
                            find("fieldy", "refdierow", "rowy", "chipy", "dierow"), x, y, unit)


def wafer_groups(frame, columns):
    if frame.empty:
        return {}
    if not frame.columns.is_unique:
        raise ValueError('Column names must be unique before linking wafers.')
    if not columns.wafer or columns.wafer not in frame:
        raise ValueError("Choose the Wafer ID column.")
    for name in (columns.lot, columns.pad):
        if name and name not in frame:
            raise ValueError(f"Missing identity column: {name}")
    groups = {}
    values = [frame[name].fillna('').astype(str).str.strip().to_numpy() if name else [''] * len(frame)
              for name in (columns.wafer, columns.lot, columns.pad)]
    for row, key in enumerate(zip(*values)):
        if not key[0]:
            raise ValueError(f"Source row {row + 2} has no Wafer ID.")
        groups.setdefault(key, []).append(row)
    return {key: tuple(rows) for key, rows in groups.items()}


def wafer_row_order(frame, columns, keys):
    groups = wafer_groups(frame, columns)
    if len(keys) != len(set(keys)) or set(keys) != set(groups):
        raise ValueError("Wafer order must retain each existing wafer exactly once.")
    return [row for key in keys for row in groups[key]]


def coordinate_row_order(frame, columns, basis="field", primary="x", ascending=(True, True)):
    x, y = (columns.field_x, columns.field_y) if basis == "field" else (columns.x, columns.y)
    if not x or not y or x == y or x not in frame or y not in frame:
        raise ValueError("Choose distinct X and Y columns for sorting.")
    numeric = frame[[x, y]].apply(pd.to_numeric, errors="coerce").reset_index(drop=True)
    if not np.isfinite(numeric.to_numpy(float)).all():
        raise ValueError("Sorting coordinates must all be finite numbers; no rows were removed.")
    sort_columns = [x, y] if primary == "x" else [y, x]
    return [int(row) for rows in wafer_groups(frame, columns).values()
            for row in numeric.iloc[list(rows)].sort_values(sort_columns, ascending=list(ascending), kind="stable").index]


def coordinate_bias(ref, raw, ref_columns, raw_columns, links, *, ref_source_rows=None, raw_source_rows=None):
    """Compare explicit one-to-one links in Raw units; reject dropped points."""
    scales = {"mm": 1., "µm": .001, "um": .001, "nm": .000001}
    for label, frame, columns in (("Ref", ref, ref_columns), ("Raw", raw, raw_columns)):
        if columns.unit not in scales:
            raise ValueError(f"{label}: choose the coordinate unit (mm, µm or nm).")
        if not columns.x or not columns.y or columns.x == columns.y or columns.x not in frame or columns.y not in frame:
            raise ValueError(f"{label}: choose distinct absolute X/Y coordinate columns; Field indices are not physical coordinates.")
    if len(set(links.values())) != len(links):
        raise ValueError("Wafer links must be one-to-one.")
    ref_groups, raw_groups = wafer_groups(ref, ref_columns), wafer_groups(raw, raw_columns)
    ref_source_rows = list(range(2, len(ref) + 2)) if ref_source_rows is None else ref_source_rows
    raw_source_rows = list(range(2, len(raw) + 2)) if raw_source_rows is None else raw_source_rows
    results = []
    for ref_key, raw_key in links.items():
        if ref_key not in ref_groups or raw_key not in raw_groups:
            raise ValueError("A linked wafer no longer exists; rebuild the link.")
    reverse_links = {raw_key: ref_key for ref_key, raw_key in links.items()}
    unit = 'µm' if raw_columns.unit == 'um' else raw_columns.unit
    for raw_key in raw_groups:
        if raw_key not in reverse_links:
            continue
        ref_key = reverse_links[raw_key]
        rr, dr = ref_groups[ref_key], raw_groups[raw_key]
        if len(rr) != len(dr):
            raise ValueError(f"{' / '.join(ref_key)} ↔ {' / '.join(raw_key)}: Ref {len(rr)} rows, Raw {len(dr)} rows. Counts must match.")
        coords = []
        for label,frame,rows,columns,source_rows in (("Ref",ref,rr,ref_columns,ref_source_rows), ("Raw",raw,dr,raw_columns,raw_source_rows)):
            data = frame[[columns.x, columns.y]].iloc[list(rows)].apply(pd.to_numeric, errors="coerce").to_numpy(float)
            if not np.isfinite(data).all():
                invalid = np.flatnonzero(~np.isfinite(data).all(axis=1))
                lines = ', '.join(str(source_rows[rows[i]]) for i in invalid[:5])
                raise ValueError(f"{label}: missing/non-finite {columns.x} / {columns.y} at source rows {lines}. Field indices cannot replace absolute XY; no points were dropped.")
            coords.append(data * (scales[columns.unit] / scales[raw_columns.unit]))
        result = pd.DataFrame({
            "Point": np.arange(1, len(rr) + 1), "Ref source row": [ref_source_rows[r] for r in rr],
            "Raw source row": [raw_source_rows[r] for r in dr], f"Ref X ({unit})": coords[0][:, 0],
            f"Raw X ({unit})": coords[1][:, 0], f"Bias X ({unit})": coords[1][:, 0] - coords[0][:, 0],
            f"Ref Y ({unit})": coords[0][:, 1], f"Raw Y ({unit})": coords[1][:, 1],
            f"Bias Y ({unit})": coords[1][:, 1] - coords[0][:, 1]})
        result.attrs['unit'] = unit
        results.append((ref_key,raw_key,result))
    return results


def load_alignment_output(path):
    """Read Tab1's literal CSV or CDSEM1's two-row CD Pivot, retaining MP names."""
    path = filesystem_path(Path(path).resolve())
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    from .cdsem1 import iter_first_sheet
    rows = iter(iter_first_sheet(path))
    _sheet, _line, first = next(rows)
    _sheet, _line, second = next(rows)
    width = max(second) + 1
    columns, group = [], ""
    for column in range(width):
        group = first.get(column, "") or group
        name = second.get(column, "")
        columns.append(name if group == "COMMON" else f"{group} / {name}")
    if not all(columns) or len(set(columns)) != len(columns):
        raise ValueError("Invalid CD Pivot column headers.")
    return pd.DataFrame([[values.get(i, "") for i in range(width)] for _, _, values in rows], columns=columns)
