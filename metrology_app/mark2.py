"""Source-linked Mark2 labels and hierarchical ordinal axes (no Qt dependency)."""
from collections import Counter
from decimal import Decimal, InvalidOperation
import re

import pandas as pd

from .id_matching import _coordinate, _value


def text(value):
    return "" if value is None or pd.isna(value) else str(value).strip()


def normalized(name):
    return "".join(c.lower() for c in str(name) if c.isalnum())


def config(state=None):
    if state is None:
        return {"identity_columns": [], "columns": [], "records": [],
                "selected": [], "order_mode": "source"}
    if not isinstance(state, dict):
        raise ValueError("Invalid Mark2 settings.")
    result = {key: state.get(key, default) for key, default in config().items()}
    for key in ("identity_columns", "columns", "selected"):
        values = result[key]
        if (not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values)
                or len(values) != len(set(values))):
            raise ValueError("Mark2 fields must have distinct, non-empty names.")
        result[key] = list(values)
    if (result["identity_columns"] and len(result["identity_columns"]) != 8
            or any(name not in result["columns"] for name in result["selected"])
            or result["order_mode"] not in ("source", "hierarchy")):
        raise ValueError("Invalid Mark2 identities, selected labels or ordering mode.")
    records = result["records"]
    if not isinstance(records, list):
        raise ValueError("Invalid Mark2 label records.")
    if records and (len(result["identity_columns"]) != 8 or not result["columns"]):
        raise ValueError("Mark2 label records need eight identity fields and label columns.")
    for record in records:
        if (not isinstance(record, dict) or set(record) != {"identity", "values"}
                or not isinstance(record["identity"], list) or len(record["identity"]) != 8
                or not isinstance(record["values"], list) or len(record["values"]) != len(result["columns"])
                or any(not isinstance(v, str) for v in record["identity"] + record["values"])):
            raise ValueError("Invalid Mark2 label record.")
    # Containers have already been detached by group_state; keep large tables cheap.
    return result


def _identity(values, columns):
    # Blank metadata is allowed: the complete eight-field tuple identifies a row.
    return tuple(_value(v, _coordinate(c)) for v, c in zip(values, columns))


def import_excel(path, sheet=0):
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        table = book.worksheets[sheet] if isinstance(sheet, int) else book[sheet]
        iterator = table.iter_rows(values_only=True)
        header = [text(v) for v in next(iterator, ())]
        if len(header) < 10 or any(not v for v in header[:8]) or header[8]:
            raise ValueError("Mark2 Excel needs eight Raw identity columns, a blank ninth column, then label columns.")
        positions = [i for i in range(9, len(header)) if header[i]]
        names = [header[i] for i in positions]
        if not names or len(set(names)) != len(names) or len({normalized(c) for c in header[:8]}) != 8:
            raise ValueError("Mark2 needs unique identity headers and at least one uniquely named label column.")
        records, seen = [], set()
        for row_number, source in enumerate(iterator, 2):
            row = [text(v) for v in source]
            if not any(row):
                continue
            if row[8] or any(row[i] for i in range(9, len(row)) if i not in positions):
                raise ValueError(f"Mark2 Excel row {row_number}: data in a separator or unnamed label column.")
            key = _identity(row[:8], header[:8])
            if key in seen or not any(row[:8]):
                raise ValueError(f"Mark2 Excel row {row_number}: duplicate or empty eight-column identity.")
            seen.add(key)
            records.append({"identity": row[:8], "values": [row[i] for i in positions]})
        if not records:
            raise ValueError("The Mark2 Excel contains no label records.")
        return config({"identity_columns": header[:8], "columns": names,
                       "records": records, "selected": names, "order_mode": "source"})
    finally:
        book.close()


def export_excel(path, state):
    """Export every imported label column, including fields not selected for plots."""
    from .identity_excel import write_identity_table
    state = config(state)
    if not state["records"]:
        raise ValueError("Import Mark2 labels before exporting their classification table.")
    return write_identity_table(
        path, "Mark2", [*state["identity_columns"], None, *state["columns"]],
        ([*record["identity"], None, *record["values"]] for record in state["records"]),
    )


def labels_for_raw(raw, state):
    """Return labels for each Raw row; ambiguous identities never borrow a label."""
    from .wafer_id_mapping import original_raw
    raw = original_raw(raw)
    state = config(state)
    columns = state["identity_columns"]
    empty = tuple("" for _ in state["selected"])
    if not columns:
        return tuple(empty for _ in range(len(raw)))
    resolved = []
    for column in columns:
        candidates = [c for c in raw.columns if normalized(c) == normalized(column)]
        if column in raw.columns:
            resolved.append(column)
        elif len(candidates) == 1:
            resolved.append(candidates[0])
        else:
            resolved.append(None)
    missing = [c for c, actual in zip(columns, resolved) if actual is None]
    if missing:
        raise ValueError("Raw Data has missing or ambiguous Mark2 identity columns: " + ", ".join(missing))
    raw_keys = [_identity(row, columns) for row in raw[resolved].itertuples(index=False, name=None)]
    counts = Counter(raw_keys)
    records = state["records"]
    imported_keys = [_identity(r["identity"], columns) for r in records]
    imported_counts = Counter(imported_keys)
    lookup = {key: r["values"] for key, r in zip(imported_keys, records) if imported_counts[key] == 1}
    indices = [state["columns"].index(c) for c in state["selected"]]
    return tuple(tuple(lookup[key][i] for i in indices) if counts[key] == 1 and key in lookup else empty
                 for key in raw_keys)


def natural_key(value):
    value = text(value)
    try:
        # Product codes such as 0E69 are labels, not scientific-notation zero.
        if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", value):
            raise InvalidOperation
        number = Decimal(value)
        if number.is_finite():
            return (0, number)
    except InvalidOperation:
        pass
    return (1, tuple((0, int(v)) if v.isdigit() else (1, v.casefold())
                     for v in re.split(r"(\d+)", value))) if value else (2, ())


def ordered_rows(rows, labels, state):
    rows = sorted(rows)  # Source means the Raw input, independent of table sorting.
    if state["order_mode"] == "hierarchy":
        rows.sort(key=lambda row: tuple(natural_key(v) for v in labels[row]))
    return rows


def hierarchy(columns, values, *, origin=1):
    """Contiguous prefix spans: outer parents never merge across intervening rows.

    Each span uses ordinal half-point edges; level zero is nearest the curve.
    """
    values = tuple(tuple(text(v) for v in row) for row in values)
    result = []
    for field, name in enumerate(columns):
        start = 0
        for stop in range(1, len(values) + 1):
            if stop != len(values) and values[start][:field + 1] == values[stop][:field + 1]:
                continue
            result.append({"field": name, "level": len(columns) - field - 1,
                           "start": start + origin - .5, "end": stop + origin - .5,
                           "text": values[start][field], "row": start})
            start = stop
    return result
