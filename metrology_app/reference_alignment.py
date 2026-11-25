"""Literal-row wafer alignment, explicit coordinate units and paired Bias trends."""
from dataclasses import dataclass
import os
from pathlib import Path

import numpy as np
import pandas as pd

from .data import combined_xy_column, combined_xy_unit, coordinates, die_sequence_column
from .reference_merge import compact
from .file_paths import filesystem_path


MM_PER_COORDINATE_UNIT = {"mm": 1., "µm": .001, "um": .001, "nm": .000001}


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
    if x is None or y is None:
        combined = combined_xy_column(frame.columns)
        if combined is not None:
            x = y = combined
            unit = combined_xy_unit(combined)
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
    if not x or not y or (x == y and combined_xy_unit(x) is None) or x not in frame or y not in frame:
        raise ValueError("Choose distinct X and Y columns for sorting.")
    numeric = coordinates(frame, x, y).reset_index(drop=True)
    if not np.isfinite(numeric.to_numpy(dtype=float, na_value=np.nan)).all():
        raise ValueError("Sorting coordinates must all be finite numbers; no rows were removed.")
    sort_columns = ["x", "y"] if primary == "x" else ["y", "x"]
    return [int(row) for rows in wafer_groups(frame, columns).values()
            for row in numeric.iloc[list(rows)].sort_values(sort_columns, ascending=list(ascending), kind="stable").index]


def _field_positions(frame, columns, rows):
    x, y = columns.field_x, columns.field_y
    if not x or not y or x == y or x not in frame or y not in frame:
        return {}
    coordinates = frame[[x, y]].iloc[list(rows)].apply(pd.to_numeric, errors="coerce")
    values = coordinates.to_numpy(float)
    unique = np.isfinite(values).all(axis=1) & ~coordinates.duplicated(keep=False).to_numpy()
    return {tuple(pair): row for pair, row, valid in zip(values, rows, unique) if valid}


def linked_row_order(target, anchor, target_columns, anchor_columns, links, *, anchor_order=None):
    """Pair the current rows and project them into the requested anchor order."""
    if not links:
        raise ValueError('Link at least one Ref/Raw wafer pair first.')
    target_groups = wafer_groups(target, target_columns)
    anchor_groups = wafer_groups(anchor, anchor_columns)
    by_anchor = {anchor_key: target_key for target_key, anchor_key in links.items()}
    if len(by_anchor) != len(links) or not links.keys() <= target_groups.keys() or not by_anchor.keys() <= anchor_groups.keys():
        raise ValueError('Rebuild the one-to-one wafer links before reordering.')

    if anchor_order is None:
        anchor_order = range(len(anchor))
    position = {row: index for index, row in enumerate(anchor_order)}
    at_anchor = {}
    for anchor_key, anchor_rows in anchor_groups.items():
        if anchor_key not in by_anchor:
            continue
        target_key = by_anchor[anchor_key]
        target_rows = target_groups[target_key]
        target_fields = _field_positions(target, target_columns, target_rows)
        anchor_fields = _field_positions(anchor, anchor_columns, anchor_rows)
        matched = {row: target_fields[field] for field, row in anchor_fields.items() if field in target_fields}
        # Preserve current positional pairs when equal-length wafers cannot all match uniquely.
        if len(target_rows) == len(anchor_rows) and len(matched) < len(target_rows):
            matched = dict(zip(anchor_rows, target_rows))
        at_anchor.update({row: [target_row] for row, target_row in matched.items()})
        matched_rows = set(matched.values())
        last = max(anchor_rows, key=position.__getitem__)
        at_anchor.setdefault(last, []).extend(row for row in target_rows if row not in matched_rows)

    order = [target_row for row in anchor_order for target_row in at_anchor.get(row, ())]
    order.extend(row for key, rows in target_groups.items() if key not in links for row in rows)
    key_by_row = {row: key for key, rows in target_groups.items() for row in rows}
    return order, list(dict.fromkeys(key_by_row[row] for row in order))


def _absolute_xy(label, frame, columns, rows, source_rows):
    data = coordinates(frame.iloc[list(rows)], columns.x, columns.y).to_numpy(dtype=float, na_value=np.nan)
    invalid = np.flatnonzero(~np.isfinite(data).all(axis=1))
    if len(invalid):
        lines = ', '.join(str(source_rows[rows[i]]) for i in invalid[:5])
        raise ValueError(f"{label}: missing/non-finite {columns.x} / {columns.y} at source rows {lines}. "
                         "Field indices cannot replace absolute XY.")
    return data


def paired_wafer_rows(ref, raw, ref_columns, raw_columns, links, *, notes=None):
    if len(set(links.values())) != len(links):
        raise ValueError("Wafer links must be one-to-one.")
    ref_groups, raw_groups = wafer_groups(ref, ref_columns), wafer_groups(raw, raw_columns)
    for ref_key, raw_key in links.items():
        if ref_key not in ref_groups or raw_key not in raw_groups:
            raise ValueError("A linked wafer no longer exists; rebuild the link.")
    reverse_links = {raw_key: ref_key for ref_key, raw_key in links.items()}
    for raw_key in raw_groups:
        if raw_key not in reverse_links:
            continue
        ref_key = reverse_links[raw_key]
        rr, dr = ref_groups[ref_key], raw_groups[raw_key]
        pair_label = f"{' / '.join(filter(None, ref_key))} ↔ {' / '.join(filter(None, raw_key))}"
        if len(rr) != len(dr):
            mismatch = f"{pair_label}: Ref {len(rr)} rows, Raw {len(dr)} rows."
            if notes is None:
                raise ValueError(f"{mismatch} Counts must match.")
            ref_fields = _field_positions(ref, ref_columns, rr)
            raw_fields = _field_positions(raw, raw_columns, dr)
            pairs = [(ref_fields[field], row) for field, row in raw_fields.items() if field in ref_fields]
            if not pairs:
                notes.append(f"{mismatch} No unique matching Field X/Y points.")
                continue
            notes.append(f"{mismatch} Comparing {len(pairs)} uniquely matched Field X/Y points.")
            rr, dr = zip(*pairs)
        yield ref_key, raw_key, rr, dr


def coordinate_bias(ref, raw, ref_columns, raw_columns, links, *,
                    ref_source_rows=None, raw_source_rows=None, notes=None):
    """Compare explicit wafer links; with notes, retain independently comparable pairs."""
    scales = MM_PER_COORDINATE_UNIT
    for label, frame, columns in (("Ref", ref, ref_columns), ("Raw", raw, raw_columns)):
        if columns.unit not in scales:
            raise ValueError(f"{label}: choose the coordinate unit (mm, µm or nm).")
        if (not columns.x or not columns.y or (columns.x == columns.y and combined_xy_unit(columns.x) is None)
                or columns.x not in frame or columns.y not in frame):
            raise ValueError(f"{label}: choose distinct absolute X/Y coordinate columns; Field indices are not physical coordinates.")
    ref_source_rows = list(range(2, len(ref) + 2)) if ref_source_rows is None else ref_source_rows
    raw_source_rows = list(range(2, len(raw) + 2)) if raw_source_rows is None else raw_source_rows
    unit = 'µm' if raw_columns.unit == 'um' else raw_columns.unit
    map_columns = {"Raw Die Seq": die_sequence_column(raw.columns),
                   "Raw Field X": raw_columns.field_x, "Raw Field Y": raw_columns.field_y}
    results = []
    for ref_key, raw_key, rr, dr in paired_wafer_rows(ref, raw, ref_columns, raw_columns, links, notes=notes):
        try:
            ref_xy = _absolute_xy("Ref", ref, ref_columns, rr, ref_source_rows)
            raw_xy = _absolute_xy("Raw", raw, raw_columns, dr, raw_source_rows)
        except ValueError as error:
            if notes is None:
                raise
            notes.append(f"{' / '.join(filter(None, ref_key))} ↔ {' / '.join(filter(None, raw_key))}: {error}")
            continue
        ref_xy = ref_xy * (scales[ref_columns.unit] / scales[raw_columns.unit])
        result = pd.DataFrame({
            "Point": np.arange(1, len(rr) + 1), "Ref source row": [ref_source_rows[r] for r in rr],
            "Raw source row": [raw_source_rows[r] for r in dr], f"Ref X ({unit})": ref_xy[:, 0],
            f"Raw X ({unit})": raw_xy[:, 0], f"Bias X ({unit})": raw_xy[:, 0] - ref_xy[:, 0],
            f"Ref Y ({unit})": ref_xy[:, 1], f"Raw Y ({unit})": raw_xy[:, 1],
            f"Bias Y ({unit})": raw_xy[:, 1] - ref_xy[:, 1]})
        for label, column in map_columns.items():
            if column in raw:
                result[label] = raw[column].iloc[list(dr)].to_numpy()
        result.attrs['unit'] = unit
        results.append((ref_key,raw_key,result))
    return results


def ordered_source_pairs(results):
    return sorted(
        (raw, ref) for _, _, result in results
        for raw, ref in zip(result['Raw source row'], result['Ref source row'])
    )


def aligned_reference_data(ref, raw, raw_columns, results, ref_source_rows, raw_source_rows):
    """Build both paired tables and a full-length, Raw-indexed Ref clipboard table."""
    ref_positions = {source: index for index, source in enumerate(ref_source_rows)}
    raw_positions = {source: index for index, source in enumerate(raw_source_rows)}
    pairs = ordered_source_pairs(results)
    source_rows = [raw for raw, _ in pairs]
    raw_values = raw.iloc[[raw_positions[raw] for raw in source_rows]].reset_index(drop=True)
    ref_values = ref.iloc[[ref_positions[ref] for _, ref in pairs]].reset_index(drop=True)
    names = {compact(column): column for column in raw}
    unit = raw_columns.unit
    axes = tuple(f'{axis}({unit})' if unit else f'Absolute {axis}' for axis in ('X', 'Y'))
    metadata = {
        'Wafer ID': raw_columns.wafer, 'Lot ID': raw_columns.lot or names.get('lotno'),
        'Tool SN': names.get('toolsn', names.get('toolserialnumber')),
        'PAD Name': raw_columns.pad,
        'Die Seq': die_sequence_column(raw.columns),
        'FIELD X': raw_columns.field_x, 'FIELD Y': raw_columns.field_y,
        axes[0]: raw_columns.x, axes[1]: raw_columns.y,
    }
    prefix = _raw_metadata_frame(raw_values, metadata)
    clipboard = ref_values.set_axis(list(source_rows)).reindex(sorted(raw_source_rows), fill_value='')
    return _reference_with_raw_metadata(ref_values, prefix), raw_values, clipboard, axes, metadata


def _raw_metadata_frame(raw, metadata):
    return pd.DataFrame({label: raw[source] if source in raw else ''
                         for label, source in metadata.items()}, index=raw.index)


def aligned_raw_analysis_frame(raw, metadata):
    """Normalize mapped fields for analysis while keeping the Raw worksheet literal."""
    if not metadata or raw.empty:
        return raw
    prefix = _raw_metadata_frame(raw, metadata)
    columns = [column for column in raw if column not in prefix and column not in metadata.values()]
    return pd.concat([prefix, raw.loc[:, columns]], axis=1)


def _reference_with_raw_metadata(ref_values, prefix):
    reserved = set(prefix) | set(ref_values)
    identity_aliases = {compact(label) for label in prefix} | {
        'wafer', 'waferno', 'lot', 'lotno', 'pad', 'diesequence', 'diesequenceno', 'dieid', 'seq',
    }
    display_names = {}
    for column in ref_values:
        name = column
        if compact(name) in identity_aliases:
            while name in reserved or name in display_names.values():
                name = f'Ref {name}'
        display_names[column] = name
    return pd.concat([prefix, ref_values.rename(columns=display_names)], axis=1)


def scan_alignment_outputs(folders):
    """Find measurement CSVs, omitting generated reports and unfinished runs."""
    paths = set()
    for folder in folders:
        source = Path(folder).resolve()
        root = filesystem_path(source)
        for directory, subfolders, names in os.walk(root):
            subfolders[:] = [name for name in subfolders if not name.startswith('.')]
            parent = source / Path(directory).relative_to(root)
            paths.update(parent / name for name in names
                         if not name.startswith(('_', '.')) and Path(name).suffix.casefold() == '.csv')
    return sorted(paths, key=lambda path: str(path).casefold())


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
