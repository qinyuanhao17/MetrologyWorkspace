"""Identify measurement sets without modifying, dropping or averaging samples."""
from threading import current_thread, main_thread, local
from dataclasses import dataclass, replace
from itertools import groupby
import json

import numpy as np
import pandas as pd

from .data import number


_MEASUREMENT_CACHE = []  # Four owned metadata snapshots, never measurement values.

_COMPARABLE_WAFER_FIELDS = (
    ("Wafer ID", ("waferid", "wafer", "waferno", "wafernumber")),
    ("Lot ID", ("lotid", "lot", "lotno", "lotnumber")),
    ("PAD Name", ("padname", "pad", "sitename")),
    ("Slot", ("slot", "slotno", "slotnumber", "waferslot")),
)


def compare_wafer_inputs(reference, raw):
    """Return a wafer order flag and a description of different identities."""
    if any(frame.empty or not frame.columns.is_unique for frame in (reference, raw)):
        return False, ""

    def headers(frame):
        return {"".join(c.lower() for c in str(column) if c.isalnum()): column
                for column in frame}

    ref_headers, raw_headers = headers(reference), headers(raw)
    fields, ref_values, raw_values = [], [], []
    for field, aliases in _COMPARABLE_WAFER_FIELDS:
        ref_column = next((ref_headers[name] for name in aliases if name in ref_headers), None)
        raw_column = next((raw_headers[name] for name in aliases if name in raw_headers), None)
        if ref_column is not None and raw_column is not None:
            fields.append(field)
            ref_values.append(reference[ref_column].fillna("").astype(str).str.strip())
            raw_values.append(raw[raw_column].fillna("").astype(str).str.strip())
    if "Wafer ID" not in fields and "Slot" not in fields:
        return False, ""

    ref_runs = [key for key, _ in groupby(zip(*ref_values)) if any(key)]
    raw_runs = [key for key, _ in groupby(zip(*raw_values)) if any(key)]

    def order_differs(ref_keys, raw_keys):
        shared = set(ref_keys) & set(raw_keys)
        return ([key for key in ref_keys if key in shared]
                != [key for key in raw_keys if key in shared])

    order_mismatch = order_differs(ref_runs, raw_runs)
    if not order_mismatch and fields[0] == "Wafer ID":
        # Recognize a reversed wafer sequence even if its Lot or PAD changed.
        ref_ids = [key for key, _ in groupby(row[0] for row in ref_runs) if key]
        raw_ids = [key for key, _ in groupby(row[0] for row in raw_runs) if key]
        order_mismatch = order_differs(ref_ids, raw_ids)

    def differences(label, runs, other_runs):
        other = set(other_runs)
        unique = dict.fromkeys(key for key in runs if key not in other)
        if not unique:
            return ""
        details = ", ".join(f"{field} {value or '(blank)'}"
                            for field, value in zip(fields, next(iter(unique))))
        return f"{label} only ({len(unique)}) · {details}."

    difference = " ".join(filter(None, (differences("Ref", ref_runs, raw_runs),
                                        differences("Raw", raw_runs, ref_runs))))
    return order_mismatch, difference


@dataclass
class Measurement:
    key: str
    wafer: str
    lot: str
    pad: str
    rows: tuple
    label: str
    detail: str


def wafer_identity_label(frame, wafer_column=None, *, show_pad=True, show_lot=True):
    """Wafer ID with typed LOT/PAD captions; source strings remain untouched."""
    return wafer_identity_labels(frame, [range(len(frame))], wafer_column,
                                 show_pad=show_pad, show_lot=show_lot)[0]


def wafer_identity_labels(frame, row_ranges, wafer_column=None, *, show_pad=True, show_lot=True):
    """Prepare identity columns once for many contiguous sequence labels.

    Interleaved measurements can have thousands of spans. Normalizing a pandas
    slice for each one makes footer preparation much slower than the fit itself.
    Only label text is normalized; the source frame and row positions are intact.
    """
    names = {"".join(ch.lower() for ch in str(c) if ch.isalnum()): c for c in frame}
    fields = (("waferid", "wafer", "waferno"), ("lotid", "lot", "lotno"), ("padname", "pad"))
    values = []
    for index, aliases in enumerate(fields):
        if (index == 1 and not show_lot) or (index == 2 and not show_pad):
            continue
        column = wafer_column if index == 0 and wafer_column in frame else next(
            (names[name] for name in aliases if name in names), None)
        if column is not None:
            prefix = {1: "LOT: ", 2: "PAD: "}.get(index, "")
            values.append((prefix, frame[column].fillna("").astype(str).str.strip().to_numpy()))
    labels = []
    for rows in row_ranges:
        fields = [(prefix, ", ".join(dict.fromkeys(column[row] for row in rows if column[row])))
                  for prefix, column in values]
        labels.append("\n".join(prefix + value for prefix, value in fields if value))
    return labels


def sequence_runs(values):
    """Infer runs from clear increasing sweeps separated by a restart.

    Missing Die Seq numbers (including the first die of a later run) are allowed.
    A decrease or shuffled sequence alone is not evidence of a new measurement.
    Ambiguous repeats remain together for the downstream duplicate-coordinate check.
    """
    seq = number(values).to_numpy(float)
    whole = [np.arange(len(seq))]
    if len(seq) < 6 or not np.isfinite(seq).all() or not np.equal(seq, np.floor(seq)).all():
        return whole
    cuts = np.flatnonzero(seq[1:] < seq[:-1]) + 1
    runs = np.split(np.arange(len(seq)), cuts)
    if len(runs) < 2 or any(len(run) < 3 or not np.all(np.diff(seq[run]) > 0) for run in runs):
        return whole
    if any(seq[current[0]] > np.median(seq[previous]) for previous, current in zip(runs, runs[1:])):
        return whole
    return runs


def default_identity_columns(frame, wafer_column, lot_column=None, pad_column=None):
    """Pick the identity columns that actually separate measurements.

    The wafer column is always kept. Lot and PAD only join it when they carry more
    than one distinct non-blank value, so a constant PAD such as "CELL" never
    splits one wafer into several sets, while a real PAD or timestamp still does.
    Die Seq is deliberately not part of the identity: missing or non-consecutive
    die numbers belong to the same wafer.
    """
    columns = []
    if wafer_column and wafer_column in frame:
        columns.append(wafer_column)
    for column in (lot_column, pad_column):
        if not column or column in columns or column not in frame:
            continue
        series = frame[column].dropna().astype(str).str.strip()
        values = {value for value in series if value and value.lower() not in {"nan", "none"}}
        if len(values) > 1:
            columns.append(column)
    return columns



_THREAD_CACHE = local()


def _thread_cache():
    # GUI cache behavior stays unchanged. Worker snapshots never reorder or
    # retain entries owned by another thread during pandas/NumPy calls.
    if current_thread() is main_thread():
        return _MEASUREMENT_CACHE
    if not hasattr(_THREAD_CACHE, "entries"):
        _THREAD_CACHE.entries = []
    return _THREAD_CACHE.entries


def detect_measurements(frame, wafer_column, group_columns=None, use_die_seq=True):
    """Group by selected columns; a string wafer column keeps legacy auto Lot/PAD grouping."""
    if wafer_column not in frame:
        return []
    names = {"".join(ch.lower() for ch in str(c) if ch.isalnum()): c for c in frame}
    find = lambda *aliases: next((names[a] for a in aliases if a in names), None)
    lot_col = find("lotid", "lot", "lotno")
    pad_col = find("padname", "pad")
    seq_col = find("dieseq", "diesequence", "diesequenceno", "seq")
    sequence = frame[seq_col] if seq_col else None
    columns = ([c for c in (wafer_column, lot_col, pad_col) if c] if group_columns is None
               else [c for c in group_columns if c in frame])
    if not columns or frame.empty:
        return []
    signature = (wafer_column, tuple(columns), lot_col, pad_col, seq_col, use_die_seq)
    cache = _thread_cache()
    # These are every input used below: normalized grouping strings and parsed
    # Die Seq. Numeric parameter edits do not change measurement membership or
    # labels. Compare owned input values, so in-place caller edits cannot hit an
    # old cache merely because the pandas object has the same identity.
    metadata = pd.DataFrame({index: frame[column].fillna("").astype(str).str.strip().reset_index(drop=True)
                             for index, column in enumerate(columns)})
    exact_die_values = None
    if seq_col:
        parsed = number(sequence).reset_index(drop=True)
        metadata[len(columns)] = parsed
        if isinstance(parsed.dtype, np.dtype) and parsed.dtype.kind in "iu":
            exact_die_values = parsed.to_numpy(copy=False)
    for index, (saved_signature, saved, measurements) in enumerate(cache):
        if signature == saved_signature and metadata.equals(saved):
            cache.insert(0, cache.pop(index))
            return [replace(measurement) for measurement in measurements]
    identity = [metadata[index].tolist() for index in range(len(columns))]
    wafer_index = columns.index(wafer_column)
    buckets = {}
    for position, values in enumerate(zip(*identity)):
        if values[wafer_index]:
            buckets.setdefault(values, []).append(position)
    lots = {}
    for values in buckets:
        fields = dict(zip(columns, values))
        wafer = fields.get(wafer_column, values[0])
        lots.setdefault(wafer, set()).add(fields.get(lot_col, ""))
    result = []
    for values, positions in buckets.items():
        fields = dict(zip(columns, values))
        wafer = fields.get(wafer_column, values[0])
        lot, pad = fields.get(lot_col, ""), fields.get(pad_col, "")
        runs = sequence_runs(sequence.iloc[positions]) if seq_col and use_die_seq else [np.arange(len(positions))]
        for ordinal, run in enumerate(runs, 1):
            rows = tuple(positions[i] for i in run)
            key = json.dumps([columns, values, ordinal], ensure_ascii=False)
            lines = [wafer if columns[0] == wafer_column else f"{columns[0]}: {values[0] or '(blank)'}"]
            if pad_col in columns and pad_col != columns[0]:
                lines.append(f"PAD: {pad or '(blank)'}")
            if lot_col in columns and lot_col != columns[0] and len(lots[wafer]) > 1:
                lines.append(f"Lot: {lot or '(blank)'}")
            for column in columns[1:]:
                if column not in (lot_col, pad_col):
                    lines.append(f"{column}: {fields[column] or '(blank)'}")
            if len(runs) > 1:
                lines.append(f"Run {ordinal} (Die Seq restart)")
            details = [f"{column}: {fields[column] or '(blank)'}" for column in columns]
            details.append(f"Records: {len(rows)}")
            if exact_die_values is not None:
                seq = np.unique(exact_die_values[list(rows)])
                details.append(f"Die Seq: {seq[0]:g}–{seq[-1]:g} ({len(seq)} unique)")
            elif seq_col:
                seq = number(sequence.iloc[list(rows)]).dropna()
                if len(seq):
                    details.append(f"Die Seq: {seq.min():g}–{seq.max():g} ({seq.nunique()} unique)")
            if len(runs) > 1:
                details.append(f"Run {ordinal} / {len(runs)} inferred from an increasing Die Seq restart.")
            result.append(Measurement(key, wafer, lot, pad, rows, "\n".join(lines), "\n".join(details)))
    cache.insert(0, (signature, metadata, tuple(replace(item) for item in result)))
    del cache[4:]
    return result
