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


def validate_view(frame, state):
    if not isinstance(state, dict):
        raise ValueError("Selection view must be an object.")
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
    return view


def export_script(frame, state):
    view = validate_view(frame, state)
    checked = set(state["checked"])
    uses = {}
    for row, key in enumerate(_source_keys(frame)):
        use = row in checked
        if key in uses and uses[key] != use:
            raise ValueError("The same Wafer/Lot/PAD/Die has conflicting checkbox states. Make them consistent before copying a script.")
        uses[key] = use
    records = [{**dict(zip(IDENTITY_FIELDS, key)), "use": use} for key, use in uses.items()]
    return json.dumps({"format": "metrology-selection", "version": 2, **view, "records": records},
                      ensure_ascii=False, indent=2, allow_nan=False)


def import_script(frame, text):
    """Validate fully before returning a replacement selection for this table."""
    try:
        state = json.loads(text)
    except (ValueError, TypeError, RecursionError) as error:
        raise ValueError("Selection script must contain valid JSON.") from error
    if (not isinstance(state, dict) or state.get("format") != "metrology-selection"
            or type(state.get("version")) is not int or state["version"] != 2):
        raise ValueError("Unsupported selection script format or version. Copy a new script from the updated source window.")
    view = validate_view(frame, state)
    records = state.get("records")
    if not isinstance(records, list) or any(not isinstance(r, dict) or any(not isinstance(r.get(f), str) for f in IDENTITY_FIELDS)
                                           or type(r.get("use")) is not bool for r in records):
        raise ValueError("Selection records need Wafer ID, Lot ID, PAD Name, Die and checkbox values.")
    uses = {tuple(r[f].strip() if f != "die" else canonical_die(r[f]) for f in IDENTITY_FIELDS): r["use"] for r in records}
    if len(uses) != len(records):
        raise ValueError("Selection script contains duplicate source identities.")
    keys = _source_keys(frame)
    missing = set(uses) - set(keys)
    if missing:
        raise ValueError(f"{len(missing)} Wafer/Lot/PAD/Die identities are missing from this table. Selection was not changed.")
    return {"checked": [row for row, key in enumerate(keys) if uses.get(key, True)], **view}
