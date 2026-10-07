"""Identify measurement sets without modifying, dropping or averaging samples."""
from dataclasses import dataclass
import json

import numpy as np

from .data import number


@dataclass
class Measurement:
    key: str
    wafer: str
    lot: str
    pad: str
    rows: tuple
    label: str
    detail: str


def wafer_identity_label(frame, wafer_column=None):
    """Wafer, Lot and PAD values only; source strings remain untouched."""
    return wafer_identity_labels(frame, [range(len(frame))], wafer_column)[0]


def wafer_identity_labels(frame, row_ranges, wafer_column=None):
    """Prepare identity columns once for many contiguous sequence labels.

    Interleaved measurements can have thousands of spans. Normalizing a pandas
    slice for each one makes footer preparation much slower than the fit itself.
    Only label text is normalized; the source frame and row positions are intact.
    """
    names = {"".join(ch.lower() for ch in str(c) if ch.isalnum()): c for c in frame}
    fields = (("waferid", "wafer", "waferno"), ("lotid", "lot", "lotno"), ("padname", "pad"))
    values = []
    for index, aliases in enumerate(fields):
        column = wafer_column if index == 0 and wafer_column in frame else next(
            (names[name] for name in aliases if name in names), None)
        if column is not None:
            values.append(frame[column].fillna("").astype(str).str.strip().to_numpy())
    labels = []
    for rows in row_ranges:
        fields = [", ".join(dict.fromkeys(column[row] for row in rows if column[row]))
                  for column in values]
        labels.append("\n".join(field for field in fields if field))
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


def detect_measurements(frame, wafer_column, group_columns=None, use_die_seq=True):
    """Group by selected columns; a string wafer column keeps legacy auto Lot/PAD grouping."""
    if wafer_column not in frame:
        return []
    names = {"".join(ch.lower() for ch in str(c) if ch.isalnum()): c for c in frame}
    find = lambda *aliases: next((names[a] for a in aliases if a in names), None)
    lot_col = find("lotid", "lot", "lotno")
    pad_col = find("padname", "pad")
    seq_col = find("dieseq", "diesequence", "diesequenceno")
    sequence = frame[seq_col] if seq_col else None
    columns = ([c for c in (wafer_column, lot_col, pad_col) if c] if group_columns is None
               else [c for c in group_columns if c in frame])
    if not columns:
        return []
    identity = [frame[column].fillna("").astype(str).str.strip().tolist() for column in columns]
    buckets = {}
    for position, values in enumerate(zip(*identity)):
        if values[columns.index(wafer_column)]:
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
            if seq_col:
                seq = number(sequence.iloc[list(rows)]).dropna()
                if len(seq):
                    details.append(f"Die Seq: {seq.min():g}–{seq.max():g} ({seq.nunique()} unique)")
            if len(runs) > 1:
                details.append(f"Run {ordinal} / {len(runs)} inferred from an increasing Die Seq restart.")
            result.append(Measurement(key, wafer, lot, pad, rows, "\n".join(lines), "\n".join(details)))
    return result
