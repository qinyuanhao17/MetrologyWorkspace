"""Versioned JSON recipes for selection views and source participation."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json
import math

from .match_groups import normalized


IDENTITY_FIELDS = ("wafer_id", "lot_id", "pad_name", "die")


def canonical_die(value):
    value = str(value).strip()
    try:
        number = Decimal(value)
        if number.is_finite() and number == number.to_integral_value():
            return str(int(number))
    except InvalidOperation:
        pass
    return value


def selection_view(selection):
    """Read current and legacy Workbook selection views without their UUIDs."""
    selection = selection or {}
    groups = selection.get("view_filter_groups")
    rows = selection.get("view_filter_row_bools")
    joins = selection.get("view_filter_group_bools", [])
    if groups is None:
        flat = selection.get("view_filters", [])
        bools = selection.get("view_filter_bools")
        if bools is None:
            bools = ["or" if selection.get("view_filter_mode") == "any" else "and"] * max(0, len(flat) - 1)
        groups, rows, joins = ([flat], [bools], []) if flat else ([], [], [])
    return deepcopy({"filters": groups, "row_bools": rows or [[] for _ in groups],
                     "group_bools": joins, "show": selection.get("view_show", "all"),
                     "search": selection.get("view_search", ""),
                     "hide_excluded": selection.get("hide_excluded", False)})


def _source_keys(frame):
    copied = frame.attrs.get("_selection_context_columns", ())
    if copied:
        frame = frame.drop(columns=list(copied), errors="ignore")
    raw = frame.loc[:, [c for c in frame if c.startswith("Raw Data / ")]]
    raw = raw.rename(columns=lambda c: c[len("Raw Data / "):]) if len(raw.columns) else frame
    columns = {normalized(c): c for c in raw}
    aliases = (("waferid", "wafer", "waferno"), ("lotid", "lot", "lotno"),
               ("padname", "pad"), ("dieseq", "diesequence", "dieid", "die"))
    selected = [next((columns[a] for a in names if a in columns), None) for names in aliases]
    if selected[0] is None:
        raise ValueError("Selection sharing requires a Wafer ID column.")
    values = [raw[c].fillna("").astype(str).str.strip().tolist() if c else [""] * len(raw) for c in selected]
    return [(wafer, lot, pad, canonical_die(die)) for wafer, lot, pad, die in zip(*values)]


def _filter_columns(state):
    groups = state.get("filters", [])
    if not isinstance(groups, list):
        return set()
    return {spec["column"] for group in groups if isinstance(group, list)
            for spec in group if isinstance(spec, dict) and isinstance(spec.get("column"), str)}


def _record_key(record):
    return tuple(record[field].strip() if field != "die" else canonical_die(record[field]) for field in IDENTITY_FIELDS)


def context_frame(frame, state):
    """Supply copied filter values without changing the target's source cells."""
    records = state.get("context", [])
    if not isinstance(records, list):
        raise ValueError("Invalid selection filter context.")
    values = {}
    for record in records:
        if (not isinstance(record, dict) or any(not isinstance(record.get(f), str) for f in IDENTITY_FIELDS)
                or not isinstance(record.get("values"), dict)
                or any(not isinstance(k, str) or not isinstance(v, str) for k, v in record["values"].items())):
            raise ValueError("Invalid selection filter context record.")
        key = _record_key(record)
        if key in values and values[key] != record["values"]:
            raise ValueError("Conflicting selection filter context.")
        values[key] = record["values"]
    available = {column for record in values.values() for column in record}
    missing = (_filter_columns(state) | available) - set(frame.columns)
    if missing & available:
        frame = frame.copy()
        keys = _source_keys(frame)
        for column in sorted(missing & available):
            frame[column] = [values.get(key, {}).get(column, "") for key in keys]
        frame.attrs["_selection_context_columns"] = sorted(
            set(frame.attrs.get("_selection_context_columns", ())) | (missing & available))
    return frame


def validate_view(frame, state):
    if not isinstance(state, dict):
        raise ValueError("Selection view must be an object.")
    frame = context_frame(frame, state)
    view = {name: deepcopy(state.get(name, default)) for name, default in
            (("filters", []), ("row_bools", []), ("group_bools", []),
             ("show", "all"), ("search", ""), ("hide_excluded", False))}
    if (view["show"] not in ("all", "filtered", "checked", "unchecked")
            or not isinstance(view["search"], str) or type(view["hide_excluded"]) is not bool):
        raise ValueError("Invalid selection view or Hide excluded rows setting.")
    groups, rows, joins = view["filters"], view["row_bools"], view["group_bools"]
    if (not isinstance(groups, list) or not isinstance(rows, list) or not isinstance(joins, list)
            or len(rows) != len(groups) or len(joins) != max(0, len(groups) - 1)):
        raise ValueError("Invalid filter rows or AND/OR connectors.")
    for group, bools in zip(groups, rows):
        if (not isinstance(group, list) or not group or not isinstance(bools, list)
                or len(bools) != len(group) - 1):
            raise ValueError("Each filter row needs conditions and matching AND/OR connectors.")
        for spec in group:
            if not isinstance(spec, dict) or not isinstance(spec.get("column"), str):
                raise ValueError("Invalid filter condition.")
            if spec["column"] not in frame:
                raise ValueError(f"Filter column is unavailable: {spec['column']}")
            if (set(spec) - {"column", "values", "query", "minimum", "maximum"}
                    or not isinstance(spec.get("query", ""), str)
                    or (spec.get("values") is not None and
                        (not isinstance(spec["values"], list) or any(not isinstance(v, str) for v in spec["values"])))):
                raise ValueError("Invalid filter values or query.")
            for bound in ("minimum", "maximum"):
                if spec.get(bound) not in (None, ""):
                    try:
                        valid = type(spec[bound]) is not bool and math.isfinite(float(spec[bound]))
                    except (ValueError, TypeError, OverflowError):
                        valid = False
                    if not valid:
                        raise ValueError("Filter bounds must be finite numbers.")
    if any(value not in ("and", "or") for bools in [*rows, joins] for value in bools):
        raise ValueError("Filter connectors must be AND or OR.")
    if state.get("context"):
        view["context"] = deepcopy(state["context"])
    return view


def _participation(frame, checked):
    checked = set(checked)
    uses = {}
    for row, key in enumerate(_source_keys(frame)):
        use = row in checked
        if key in uses and uses[key] != use:
            raise ValueError("The same Wafer/Lot/PAD/Die has conflicting checkbox states. Make them consistent before copying a selection.")
        uses[key] = use
    return uses


def export_script(frame, state):
    frame = context_frame(frame, state)
    view = validate_view(frame, state)
    uses = _participation(frame, state["checked"])
    records = [{**dict(zip(IDENTITY_FIELDS, key)), "use": use} for key, use in uses.items()]
    columns = sorted(frame.columns if view["search"].strip() else _filter_columns(view))
    if columns:
        values = {}
        for key, row in zip(_source_keys(frame), frame[columns].fillna("").astype(str).to_dict("records")):
            if key in values and values[key] != row:
                raise ValueError("The same Wafer/Lot/PAD/Die has conflicting filter values.")
            values[key] = row
        for record, key in zip(records, uses):
            record["values"] = values[key]
    view.pop("context", None)  # Filter data travels with its four-field identity.
    if view["search"].strip():
        view["search_columns"] = columns
    return json.dumps({"format": "metrology-selection", "version": 2, **view, "records": records},
                      ensure_ascii=False, indent=2, allow_nan=False)


def import_script(frame, text, *, allow_partial=False, current_checked=()):
    """Validate fully before returning a replacement selection for this table."""
    try:
        state = json.loads(text)
    except (ValueError, TypeError, RecursionError) as error:
        raise ValueError("Selection script must contain valid JSON.") from error
    if (not isinstance(state, dict) or state.get("format") != "metrology-selection"
            or type(state.get("version")) is not int or state["version"] != 2):
        raise ValueError("Unsupported selection script format or version. Copy a new script from the updated source window.")
    records = state.get("records")
    if not isinstance(records, list) or any(not isinstance(r, dict) or any(not isinstance(r.get(f), str) for f in IDENTITY_FIELDS)
                                           or type(r.get("use")) is not bool for r in records):
        raise ValueError("Selection records need Wafer ID, Lot ID, PAD Name, Die and checkbox values.")
    if any("values" in r and (not isinstance(r["values"], dict) or
           any(not isinstance(k, str) or not isinstance(v, str) for k, v in r["values"].items())) for r in records):
        raise ValueError("Invalid selection filter values.")
    uses = {_record_key(r): r["use"] for r in records}
    if len(uses) != len(records):
        raise ValueError("Selection script contains duplicate source identities.")
    search_columns = state.get("search_columns", [])
    if (not isinstance(search_columns, list) or any(not isinstance(c, str) for c in search_columns)
            or len(set(search_columns)) != len(search_columns)):
        raise ValueError("Invalid Selection Script search columns.")
    needed = (_filter_columns(state) | set(search_columns)) - set(frame.columns)
    if needed:
        if any(not needed.issubset(r.get("values", {})) for r in records):
            raise ValueError("Filter columns are unavailable and the script has no complete copied values.")
        context = [{**{field: r[field] for field in IDENTITY_FIELDS},
                    "values": {column: r["values"][column] for column in needed if column in r.get("values", {})}}
                   for r in records if r.get("values")]
        state = {**state, "context": context}
    view = validate_view(frame, state)
    keys = _source_keys(frame)
    missing = set(uses) - set(keys)
    if missing and not allow_partial:
        raise ValueError(f"{len(missing)} Wafer/Lot/PAD/Die identities are missing from this table. Selection was not changed.")
    if allow_partial:
        matched = sum(key in uses for key in keys)
        if not matched:
            raise ValueError("No source records match this table's Wafer ID / Lot / PAD / Die. Selection was not changed.")
        current = set(current_checked)
        return {"checked": [row for row, key in enumerate(keys) if uses.get(key, row in current)],
                "matched": matched, "unmatched": len(keys) - matched, **view}
    return {"checked": [row for row, key in enumerate(keys) if uses.get(key, True)], **view}
