"""Pure, positional Trend preparation shared by GUI and worker paths."""
import numpy as np
import pandas as pd
from .data import number

def prepare_sequence_groups(frame, selection, cells, wafer_column, die_column):
    """Append every measurement set to one axis; nothing is split off."""
    groups, cursor = [], 0
    spans = {}
    labels = selection.get("labels", {})
    sources = selection.get("sources", ())
    source_by_key = {key: source for source in sources for key in source.get("keys", ())}
    drawn_keys = {key for key, _metric in cells}
    if 'groups' in selection:
        parts = [(key, np.asarray(selection['groups'].get(key, ()), dtype=int))
                 for key in selection.get('wafers', ()) if key in drawn_keys]
    else:
        ids = frame[selection['wafer_column']].astype(str).str.strip().to_numpy()
        parts = [(key, np.flatnonzero(ids == key))
                 for key in selection.get('wafers', ()) if key in drawn_keys]
    parts = [(key, positions) for key, positions in parts if len(positions)]
    mark2 = selection.get("mark2")
    if mark2:
        # Both sources share the Raw ordinal domain. A missing Reference value
        # leaves a gap at its Raw position, never compresses the X coordinates.
        offsets = {key: min(source_by_key.get(key, {}).get("rows") or (0,)) for key, _ in parts}
        allowed = set(mark2["order"])
        selected_rows = {int(p) - offsets[key] for key, positions in parts for p in positions} & allowed
        domain = [row for row in mark2["order"] if row in selected_rows]
        ranks = {row: i for i, row in enumerate(domain)}
        groups = []
        for key, positions in parts:
            source = source_by_key.get(key)
            positions = sorted((int(p) for p in positions if int(p) - offsets[key] in ranks),
                               key=lambda p: ranks[p - offsets[key]])
            if not positions:
                continue
            ordered = frame.iloc[positions].copy(deep=False)
            die_name = (source or {}).get("die_column", die_column)
            ordered["__die"] = (number(ordered[die_name]).to_numpy() if die_name in frame
                                else np.asarray(positions, dtype=float) - offsets[key] + 2)
            xs = np.asarray([ranks[p - offsets[key]] for p in positions], dtype=float)
            groups.append({"key": key, "wafer": str(labels.get(key, key)), "frame": ordered,
                           "coordinate_label": "Mark2", "source_positions": np.asarray(positions),
                           "group_label": "Mark2", "positions": xs, "center": float(xs.mean()),
                           "start": float(xs.min()), "stop": float(xs.max()), "source": source,
                           "mark2_values": [mark2["labels"][p - offsets[key]] for p in positions]})
        return groups, len(domain)
    # A missing column falls back to the visible sheet row, not the
    # concatenated analysis row or a renumbered selection. Explicit blank
    # Die Seq cells keep their existing missing-value semantics.
    die = np.arange(len(frame), dtype=float) + 2
    coordinate_labels = {}
    if sources:
        for source in sources:
            rows = np.asarray(source["rows"], dtype=int)
            column = source.get("die_column", die_column)
            if column is None:
                die[rows] = np.arange(len(rows), dtype=float) + 2
            else:
                die[rows] = number(frame[column].iloc[rows]).to_numpy()
            coordinate_labels[source["name"]] = "Die Seq" if column is not None else "Row Number"
    elif die_column is not None:
        die = number(frame[die_column]).to_numpy()
    if sources and not selection.get("preserve_group_order"):
        # Keep table order even when the two tabs select different wafers.
        parts.sort(key=lambda pair: frame.index.take(pair[1]).min() - min(
            source_by_key.get(pair[0], {}).get("rows") or (0,)
        ))
    ordered_parts = []
    for key, source_positions in parts:
        values = die[source_positions]
        # Select/sort positional indices first; avoid copying a wide source
        # table for assign, dropna and sort separately for every wafer.
        positions_in_part = np.flatnonzero(~pd.isna(values))
        if not selection.get("preserve_group_order"):
            order = np.argsort(values[positions_in_part], kind="stable")
            positions_in_part = positions_in_part[order]
        if not len(positions_in_part):
            continue
        ordered_parts.append((key, source_positions[positions_in_part]))
    if not ordered_parts:
        return groups, cursor
    # Detach all selected literal rows once, then slice this owned result.
    # Hundreds of small wide-frame takes otherwise repeat the same copying.
    all_positions = np.concatenate([positions for _key, positions in ordered_parts])
    ordered_frame = frame.iloc[all_positions].copy(deep=False)
    ordered_frame["__die"] = die[all_positions]
    wafer_values = frame[wafer_column].fillna("").astype(str).str.strip().to_numpy()
    offset = 0
    for key, source_positions in ordered_parts:
        ordered = ordered_frame.iloc[offset:offset + len(source_positions)].copy(deep=False)
        offset += len(source_positions)
        source = source_by_key.get(key)
        # Ref and Raw are row-aligned tables. The same measurement must
        # occupy the same span in both sources, not overlap other wafers.
        span_key = key[1] if source is not None else key
        if span_key not in spans:
            spans[span_key] = cursor
            cursor += len(ordered)
        start = spans[span_key]
        positions = np.arange(start, start + len(ordered), dtype=float)
        wafer_id = next((wafer_values[row] for row in source_positions if wafer_values[row]), "")
        if not wafer_id:
            wafer_id = str(labels.get(key, key)).splitlines()[0]
        groups.append({"key": key, "wafer": wafer_id, "frame": ordered,
                       "coordinate_label": coordinate_labels.get(
                           (source or {}).get("name"),
                           "Die Seq" if die_column is not None else "Row Number"),
                       "source_positions": source_positions,
                       "group_label": selection.get("group_labels", {}).get(
                           key, str(labels.get(key, wafer_id)).split(" · ", 1)[-1]),
                       "positions": positions, "center": float(positions.mean()),
                       "start": float(np.min(positions)),
                       "stop": float(np.max(positions)),
                       "source": source})
    return groups, cursor



def prepare_sequence_values(request, cancelled):
    frame, selection = request["frame"], request["selection"]
    if cancelled():
        return None
    groups, extent = prepare_sequence_groups(frame, selection, request["cells"],
                                              request["wafer_column"], request["die_column"])
    numeric = {}
    for name in request["metrics"]:
        if cancelled():
            return None
        if name in frame:
            numeric[name] = number(frame[name]).to_numpy(float)
    return {"groups": groups, "extent": extent, "numeric": numeric}
