"""Record-level Wafer ID aliases; source tables are never edited in place."""
from collections import Counter
from dataclasses import dataclass

from .id_matching import _coordinate, _value

_ATTR = "metrology_wafer_id_mapping"


@dataclass(frozen=True, slots=True)
class _MappingProvenance:
    """Immutable identity data shared by pandas slices and derived tables."""

    columns: tuple[str, ...]
    records: tuple[tuple[tuple[str, ...], str], ...]

    @classmethod
    def from_state(cls, state):
        return cls(tuple(state["identity_columns"]), tuple(
            (tuple(record["identity"]), record["wafer_id"]) for record in state["records"]
        ))

    def __deepcopy__(self, memo):
        return self


def _name(value):
    return "".join(c.lower() for c in str(value) if c.isalnum())


def _text(value):
    import pandas as pd
    return "" if value is None or pd.isna(value) else str(value).strip()


def _key(values, numeric):
    return tuple(_value(value, use_number) for value, use_number in zip(values, numeric))


def config(state=None):
    if state is None:
        return {"identity_columns": [], "records": []}
    if not isinstance(state, dict) or set(state) != {"identity_columns", "records"}:
        raise ValueError("Invalid Wafer ID mapping settings.")
    columns, records = state["identity_columns"], state["records"]
    if (not isinstance(columns, list) or not isinstance(records, list)
            or any(not isinstance(c, str) or not c.strip() for c in columns)
            or (columns and (len(columns) != 8 or len({_name(c) for c in columns}) != 8
                             or sum(_name(c) == "waferid" for c in columns) != 1))
            or (records and not columns)):
        raise ValueError("Wafer ID mapping requires eight distinct Raw identity fields, including Wafer ID.")
    seen, targets = set(), set()
    wafer = next((i for i, c in enumerate(columns) if _name(c) == "waferid"), None)
    numeric = tuple(map(_coordinate, columns))
    pairs = []
    for record in records:
        if (not isinstance(record, dict) or set(record) != {"identity", "wafer_id"}
                or not isinstance(record["identity"], list) or len(record["identity"]) != 8
                or any(not isinstance(v, str) for v in record["identity"])
                or not isinstance(record["wafer_id"], str) or not record["wafer_id"].strip()
                or not record["identity"][wafer].strip()):
            raise ValueError("Each Wafer ID mapping record needs its original eight fields and a non-empty new Wafer ID.")
        key = _key(record["identity"], numeric)
        target = list(record["identity"])
        target[wafer] = record["wafer_id"]
        target = _key(target, numeric)
        if key in seen:
            raise ValueError("Duplicate or conflicting eight-column identities in Wafer ID mapping.")
        if target in targets:
            raise ValueError("Wafer ID mapping merges distinct records into the same identity.")
        seen.add(key)
        targets.add(target)
        pairs.append((key, target))
    # A canonical row must not also name a different original record.
    for key, target in pairs:
        if target in seen and target != key:
            raise ValueError("A new Wafer ID conflicts with another original record in the mapping.")
    return {"identity_columns": list(columns), "records": records}


def import_excel(path):
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        rows = iter(book.worksheets[0].iter_rows(values_only=True))
        header = [_text(v) for v in next(rows, ())]
        if (len(header) < 10 or any(not c for c in header[:8]) or header[8]
                or _name(header[9]) != "waferid" or any(header[10:])):
            raise ValueError("Wafer ID mapping Excel needs the first eight Raw columns, a blank ninth column, and 'Wafer ID' in column ten.")
        records = []
        for number, row in enumerate(rows, 2):
            values = [_text(v) for v in row]
            if not any(values):
                continue
            if values[8] or any(values[10:]) or not values[9]:
                raise ValueError(f"Wafer ID mapping Excel row {number}: keep the separator empty and provide a new Wafer ID in column ten.")
            records.append({"identity": values[:8], "wafer_id": values[9]})
        if not records:
            raise ValueError("The Wafer ID mapping Excel contains no records.")
        return config({"identity_columns": header[:8], "records": records})
    finally:
        book.close()


def export_excel(path, state=None, raw=None):
    """Export imported aliases, or an editable identity mapping for current Raw."""
    from .identity_excel import write_identity_table
    state = config(state)
    if state["records"]:
        columns = state["identity_columns"]
        rows = ([*record["identity"], None, record["wafer_id"]] for record in state["records"])
    else:
        if raw is None or raw.empty:
            raise ValueError("Paste Raw Data before exporting a Wafer ID mapping template.")
        raw = original_raw(raw)
        columns = _raw_identity_columns(raw)
        wafer = next(i for i, column in enumerate(columns) if _name(column) == "waferid")
        rows = ([*values, None, values[wafer]] for values in
                ([_text(value) for value in row] for row in raw[columns].itertuples(index=False, name=None)))
    return write_identity_table(path, "Wafer ID mapping", [*columns, None, "Wafer ID"], rows)


def _raw_identity_columns(raw):
    columns = list(raw.columns[:8])
    if (len(columns) != 8 or any(not isinstance(c, str) or not c.strip() for c in columns)
            or len({_name(c) for c in columns}) != 8
            or sum(_name(c) == "waferid" for c in columns) != 1):
        raise ValueError("Wafer ID mapping needs the first eight Raw identity columns, including Wafer ID.")
    return columns


def _columns(frame, identity_columns):
    resolved = []
    for column in identity_columns:
        matches = [c for c in frame if _name(c) == _name(column)]
        if column in frame:
            resolved.append(column)
        elif len(matches) == 1:
            resolved.append(matches[0])
        else:
            raise ValueError(f"Raw Data has a missing or ambiguous Wafer ID mapping field: {column}")
    return resolved


def parse_wafer_id_list(rows):
    """Validate two columns of text and report errors using visible row numbers."""
    aliases, first_rows = {}, {}
    for number, (old, new) in enumerate(rows, 1):
        old, new = old.strip(), new.strip()
        if not old and not new:
            continue
        if not old or not new:
            raise ValueError(f"Row {number}: enter both the original and new Wafer ID.")
        if old in first_rows:
            raise ValueError(f"Duplicate original Wafer ID {old!r} in rows {first_rows[old]} and {number}.")
        first_rows[old] = number
        aliases[old] = new
    return aliases


def list_source_wafer_ids(sources):
    ids = set()
    for source in sources:
        if not source.empty:
            source = original_raw(source)
            column, = _columns(source, ["Wafer ID"])
            ids.update(map(_text, source[column]))
    ids.discard("")
    return ids


def mapping_from_wafer_id_list(aliases, sources):
    """Expand wafer aliases into the existing record-level mapping format."""
    frames = [original_raw(source) for source in sources if not source.empty]
    if not frames:
        raise ValueError("Paste Raw Data before applying a Wafer ID list.")
    columns = _raw_identity_columns(frames[0])
    wafer = next(i for i, column in enumerate(columns) if _name(column) == "waferid")
    numeric = tuple(map(_coordinate, columns))
    records = {}
    changed = False
    for frame in frames:
        for values in frame[_columns(frame, columns)].itertuples(index=False, name=None):
            identity = [_text(value) for value in values]
            original = identity[wafer]
            target = aliases.get(original, original)
            changed |= target != original
            if target == original and isinstance(values[wafer], str):
                identity[wafer] = target = values[wafer]
            # Preview and Final may contain the same measurement record.
            records.setdefault(_key(identity, numeric), {"identity": identity, "wafer_id": target})
    return {"identity_columns": columns, "records": list(records.values())} if changed else config()


def original_raw(frame):
    """Recover literal identities for Mark2 and participation, even after slicing."""
    mapping = frame.attrs.get(_ATTR)
    if mapping is None or frame.empty:
        return frame
    columns = _columns(frame, mapping.columns)
    wafer = next(i for i, c in enumerate(mapping.columns) if _name(c) == "waferid")
    numeric = tuple(map(_coordinate, columns))
    reverse = {}
    for identity, wafer_id in mapping.records:
        values = list(identity)
        values[wafer] = wafer_id
        reverse[_key(values, numeric)] = identity[wafer]
    result = frame.copy()
    result[columns[wafer]] = [reverse.get(_key(values, numeric), values[wafer])
                              for values in frame[columns].itertuples(index=False, name=None)]
    result.attrs.pop(_ATTR, None)
    return result


def apply(frame, state, *, source_only=False):
    """Return canonical processing rows; reject incomplete or ambiguous coverage."""
    if frame is None or frame.empty or not state or not state["records"]:
        return frame
    mapping = _MappingProvenance.from_state(state)
    if frame.attrs.get(_ATTR) == mapping:
        return frame
    frame = original_raw(frame)
    columns = _columns(frame, mapping.columns)
    wafer = next(i for i, c in enumerate(mapping.columns) if _name(c) == "waferid")
    numeric = tuple(map(_coordinate, columns))
    lookup, canonical = {}, {}
    for identity, wafer_id in mapping.records:
        lookup[_key(identity, numeric)] = wafer_id
        values = list(identity)
        values[wafer] = wafer_id
        canonical[_key(values, numeric)] = wafer_id
    keys = [_key(values, numeric) for values in frame[columns].itertuples(index=False, name=None)]
    duplicates = sum(count - 1 for count in Counter(keys).values() if count > 1)
    if duplicates:
        raise ValueError(f"Raw Data contains {duplicates} duplicate eight-column identities; Wafer ID mapping is ambiguous.")
    missing = [i + 1 for i, key in enumerate(keys)
               if key not in lookup and (source_only or key not in canonical)]
    if missing:
        raise ValueError(f"Wafer ID mapping has no entry for {len(missing)} Raw rows (first data rows: {', '.join(map(str, missing[:8]))}). Check all eight fields, including Lot ID, or reset the mapping.")
    result = frame.copy()
    result[columns[wafer]] = [lookup.get(key, canonical.get(key)) for key in keys]
    result.attrs[_ATTR] = mapping
    return result


def processing_keys(frame, state):
    """Display identities for child tables, whose sheet storage drops attrs."""
    from .match_groups import participation_source_keys
    frame = apply(frame, state)
    if frame.attrs.get(_ATTR):
        frame = frame.copy()
        frame.attrs.pop(_ATTR, None)
    return participation_source_keys(frame)
