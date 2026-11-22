"""Pure, positional Trend preparation shared by GUI and worker paths."""
from itertools import chain

import numpy as np
import pandas as pd
import json
from .data import number


def _source_span_key(key, source, identity_values, positions):
    """Match current physical identities across vendor headers; keep UI keys stable."""
    original = key[1]
    values = identity_values.get(source['name'])
    if values is None:
        return original
    try:
        columns, _values, run = json.loads(original)
    except (TypeError, ValueError):
        return original  # Classified Group spans keep their explicit order/identity.
    aliases = {'waferid', 'wafer', 'waferno', 'lotid', 'lot', 'lotno', 'padname', 'pad'}
    if any(''.join(c.lower() for c in str(column) if c.isalnum()) not in aliases for column in columns):
        return original
    identities = tuple(sorted({tuple(field[row] for field in values) for row in positions}))
    return ('current-source-identity', identities, run)

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
    # A missing column falls back to the visible sheet row, not the
    # concatenated analysis row or a renumbered selection. Explicit blank
    # Die Seq cells keep their existing missing-value semantics.
    die = np.arange(len(frame), dtype=float) + 2
    coordinate_labels = {}
    identity_values = {}
    if sources:
        for source in sources:
            rows = np.asarray(source["rows"], dtype=int)
            column = source.get("die_column", die_column)
            if column is None:
                die[rows] = np.arange(len(rows), dtype=float) + 2
            else:
                die[rows] = number(frame[column].iloc[rows]).to_numpy()
            coordinate_labels[source["name"]] = "Die Seq" if column is not None else "Row Number"
            if source.get('identity_columns'):
                identity_columns = source['identity_columns']
                identity_values[source['name']] = tuple(
                    frame[column].fillna('').astype(str).str.strip().to_numpy()
                    if column is not None else np.full(len(frame), '', dtype=object)
                    for column in (identity_columns.get(field) for field in ('waferid', 'lotid', 'padname')))
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
    span_lengths = {}
    span_keys = []
    source_spans = {source["name"]: {} for source in sources}
    for key, source_positions in ordered_parts:
        source = source_by_key.get(key)
        span_key = (_source_span_key(key, source, identity_values, source_positions)
                    if source is not None and not selection.get('preserve_group_order') else
                    key[1] if source is not None else key)
        span_lengths[span_key] = max(span_lengths.get(span_key, 0), len(source_positions))
        span_keys.append(span_key)
        if source is not None:
            source_spans[source["name"]][span_key] = None
    # A short Ref series may share a wafer with a much longer Raw series.
    # Reserve the full span before positioning either series or the next wafer.
    span_order = span_lengths
    if len(source_spans) == 2 and not selection.get("preserve_group_order"):
        first, second = source_spans.values()
        shared = first.keys() & second.keys()
        if [span for span in first if span in shared] != [span for span in second if span in shared]:
            # Resolve conflicting source orders using the first source's axis.
            span_order = dict.fromkeys(chain(first, second))
    for span_key in span_order:
        spans[span_key] = cursor
        cursor += span_lengths[span_key]
    offset = 0
    for (key, source_positions), span_key in zip(ordered_parts, span_keys):
        ordered = ordered_frame.iloc[offset:offset + len(source_positions)].copy(deep=False)
        offset += len(source_positions)
        source = source_by_key.get(key)
        start = spans[span_key]
        positions = np.arange(start, start + len(ordered), dtype=float)
        current_wafer = identity_values[source['name']][0] if source and source['name'] in identity_values else wafer_values
        wafer_id = next((current_wafer[row] for row in source_positions if current_wafer[row]), "")
        if not wafer_id:
            wafer_id = str(labels.get(key, key)).splitlines()[0]
        groups.append({"key": key, "span_key": span_key, "wafer": wafer_id, "frame": ordered,
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
    # All curves, point mappings and exports traverse the shared axis in order.
    groups.sort(key=lambda group: group["start"])
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
