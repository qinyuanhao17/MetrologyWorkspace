"""Explicit, source-preserving composite-ID matching for Type2 workbooks."""
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import pandas as pd


def matching_keys(state=None):
    if state is None:
        return {"reference": [], "raw": []}
    if not isinstance(state, dict) or set(state) - {"reference", "raw"}:
        raise ValueError("Invalid matching conditions.")
    result = {}
    for side in ("reference", "raw"):
        values = state.get(side, [])
        if (not isinstance(values, (list, tuple))
                or any(not isinstance(value, str) or not value.strip() for value in values)
                or len(set(values)) != len(values)):
            raise ValueError("Matching conditions must contain distinct column names.")
        result[side] = list(values)
    return result


def _coordinate(name):
    return "".join(c.lower() for c in name if c.isalnum()) in {
        "x", "y", "fieldx", "fieldy", "colx", "rowy", "dieseq", "dieorder", "site", "siteno",
    }


def _value(value, numeric):
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    if numeric:
        try:
            value = Decimal(text)
            if value.is_finite():
                return value  # Numeric coordinates 0, 0.0 and -0 compare equally.
        except InvalidOperation:
            pass
    return text  # Identity text, including leading zeros, is never converted.


@dataclass(frozen=True)
class IDAlignment:
    reference: pd.DataFrame
    reference_rows: tuple
    matched: int
    raw_count: int
    unused_reference: int
    duplicate_reference: tuple
    duplicate_raw: tuple
    blank_reference: tuple
    blank_raw: tuple

    @property
    def message(self):
        text = f"Matched IDs: {self.matched} / {self.raw_count} Raw rows; {self.raw_count-self.matched} unmatched"
        if self.unused_reference:
            text += f"; {self.unused_reference} unused Reference rows"
        for label, rows in (("duplicate Reference IDs", self.duplicate_reference),
                            ("duplicate Raw IDs", self.duplicate_raw),
                            ("blank Reference keys", self.blank_reference),
                            ("blank Raw keys", self.blank_raw)):
            if rows:
                text += f"; {label}: {len(rows)} rows"
        return text

    @property
    def details(self):
        lines = [self.message, "Duplicate or incomplete IDs are excluded, never averaged or matched by position."]
        for label, rows in (("Duplicate Reference", self.duplicate_reference), ("Duplicate Raw", self.duplicate_raw),
                            ("Blank Reference", self.blank_reference), ("Blank Raw", self.blank_raw)):
            if rows:
                lines.append(f"{label} data rows (1-based): " + ", ".join(str(i+1) for i in rows[:20]))
        return "\n".join(lines)


def align_by_id(reference, raw, conditions):
    keys = matching_keys(conditions)
    if not keys["reference"] or len(keys["reference"]) != len(keys["raw"]):
        raise ValueError("Choose the same non-zero number of Reference and Raw matching fields, in corresponding order.")
    for side, frame in (("reference", reference), ("raw", raw)):
        if not frame.columns.is_unique:
            raise ValueError(f"Rename duplicate {side} headers before ID matching.")
        missing = [column for column in keys[side] if column not in frame]
        if missing:
            raise ValueError(f"Missing {side} matching fields: {', '.join(missing)}")
    numeric = [_coordinate(a) and _coordinate(b) for a, b in zip(keys["reference"], keys["raw"])]

    def ids(frame, columns):
        values = [tuple(_value(value, mode) for value, mode in zip(row, numeric))
                  for row in frame[columns].itertuples(index=False, name=None)]
        return [None if any(value is None for value in row) else row for row in values]

    ref_ids, raw_ids = ids(reference, keys["reference"]), ids(raw, keys["raw"])
    ref_counts, raw_counts = Counter(ref_ids), Counter(raw_ids)
    lookup = {key: row for row, key in enumerate(ref_ids) if key is not None and ref_counts[key] == 1}
    positions = tuple(lookup.get(key) if key is not None and raw_counts[key] == 1 else None for key in raw_ids)
    aligned = reference.reset_index(drop=True).reindex([-1 if row is None else row for row in positions])
    aligned = aligned.reset_index(drop=True).fillna("")
    used = {row for row in positions if row is not None}
    return IDAlignment(aligned, positions, len(used), len(raw), len(reference)-len(used),
        tuple(i for i, key in enumerate(ref_ids) if key is not None and ref_counts[key] > 1),
        tuple(i for i, key in enumerate(raw_ids) if key is not None and raw_counts[key] > 1),
        tuple(i for i, key in enumerate(ref_ids) if key is None),
        tuple(i for i, key in enumerate(raw_ids) if key is None))
