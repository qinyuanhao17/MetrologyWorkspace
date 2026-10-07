"""Source-preserving measurement classification and one paired row projection."""
from collections import Counter
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json
from uuid import uuid4

import numpy as np
import pandas as pd

from .measurements import Measurement, default_identity_columns, detect_measurements


DEFAULT_FLAGS = ("0", "1", "-1")
DEFAULT_MARK_NAMES = ("Old", "New")


def normalized_mark_values(state):
    """Ordered Mark names; the first entry also catches unassigned wafers."""
    values = state.get("mark_values")
    if values is None:
        # Workbooks written before Marks were free-form used exactly Old/New.
        # Keeping those ids lets their saved group keys keep resolving.
        names = state.get("mark_names")
        names = names if isinstance(names, dict) else {}
        return [
            {"id": key, "name": str(names.get(key, key)).strip() or key}
            for key in DEFAULT_MARK_NAMES
        ]
    if not isinstance(values, list) or not values:
        raise ValueError("Keep at least one Mark.")
    result, seen_ids, seen_names = [], set(), set()
    for spec in values:
        if not isinstance(spec, dict):
            raise ValueError("Invalid Mark definition.")
        key, name = str(spec.get("id", "")).strip(), str(spec.get("name", "")).strip()
        if not key or not name or key in seen_ids or name.casefold() in seen_names:
            raise ValueError("Marks need unique, non-empty ids and names.")
        seen_ids.add(key)
        seen_names.add(name.casefold())
        result.append({"id": key, "name": name})
    return result


def normalized_mark_rows(state):
    """Row ids explicitly assigned to a Mark; the rest fall back to the first."""
    known = {spec["id"] for spec in state["mark_values"]}
    rows = state.get("mark_rows")
    if rows is None:
        fallback = "New" if "New" in known else state["mark_values"][0]["id"]
        legacy = [str(item) for item in (state.get("new_rows") or [])]
        rows = {fallback: legacy} if legacy else {}
    if not isinstance(rows, dict):
        raise ValueError("Invalid Mark assignments.")
    result = {}
    for key, assigned in rows.items():
        key = str(key)
        if key not in known or not isinstance(assigned, (list, tuple)):
            raise ValueError("Mark assignments must reference a defined Mark.")
        result[key] = sorted({str(item) for item in assigned})
    return result


def flag_order(values):
    values = list(dict.fromkeys(values))
    return ([flag for flag in DEFAULT_FLAGS if flag in values]
            + [flag for flag in values if flag and flag not in DEFAULT_FLAGS]
            + ([""] if "" in values else []))


def normalized(value):
    return "".join(c.lower() for c in str(value) if c.isalnum())


def flag_value(value):
    if pd.isna(value) or not str(value).strip():
        return ""
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValueError(f"Invalid TestFlag {value!r}; enter an integer or leave blank.") from None
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError(f"Invalid TestFlag {value!r}; enter an integer or leave blank.")
    return "0" if not number else format(number, "f").split(".")[0]


def group_state(state=None):
    source = state or {}
    # Normalize the accepted state separately below: copying it here and again
    # recursively doubles the largest participation/Mark lists on every edit.
    state = deepcopy({key: value for key, value in source.items() if key != "applied"})
    state.setdefault("enabled", False)
    # Old workbooks used Old/New unconditionally; files that never stored Mark
    # data must not switch Mark on by themselves.
    legacy_marks = any(key in state for key in ("mark_values", "mark_names", "mark_rows", "new_rows"))
    state.setdefault("mark_enabled", legacy_marks)
    if not isinstance(state["mark_enabled"], bool):
        raise ValueError("Mark needs a checkbox value.")
    if not isinstance(state.get("mark_names", {}), dict):
        raise ValueError("Mark names must be a mapping.")
    state["mark_values"] = normalized_mark_values(state)
    state["mark_rows"] = normalized_mark_rows(state)
    state.pop("mark_names", None)
    state.pop("new_rows", None)
    state.setdefault("head_names", {"0": "TestFlag 0", "1": "TestFlag 1", "-1": "Unknown"})
    for flag, default in (("0", "TestFlag 0"), ("1", "TestFlag 1"), ("-1", "Unknown")):
        state["head_names"].setdefault(flag, default)
    state["head_names"] = {str(flag): str(name).strip() or f"TestFlag {flag}"
                           for flag, name in state["head_names"].items()}
    state.setdefault("identity_columns", None)
    state.setdefault("filters", [])
    state.setdefault("sort", [])
    state.setdefault("trend_order", "groups")
    # "Current table order" was folded into "Original row order": a saved table
    # order is still a row order, so keep it defined instead of resetting it.
    if state["trend_order"] == "table":
        state["trend_order"] = "original"
    elif state["trend_order"] not in ("groups", "original"):
        state["trend_order"] = "groups"
    state.setdefault("group_order", [])
    state.setdefault("use_group_card", False)
    state.setdefault("combined_groups", [])
    state.setdefault("show_wafer_groups", [])
    if not isinstance(state["show_wafer_groups"], list) or any(not isinstance(key, str) for key in state["show_wafer_groups"]):
        raise ValueError("Invalid Group wafer-label settings.")
    state.setdefault("data_selection", None)
    selection = state["data_selection"]
    if selection is not None:
        if not isinstance(selection, dict) or not isinstance(selection.get("records"), list) or not isinstance(selection.get("excluded"), list):
            raise ValueError("Invalid data participation state.")
        records = selection["records"]
        if any(not isinstance(record, dict) or not isinstance(record.get("id"), str)
               or not isinstance(record.get("key"), str) for record in records):
            raise ValueError("Invalid source row identities.")
        ids = [record["id"] for record in records]
        keys = [record["key"] for record in records]
        id_set = set(ids)
        if (len(ids) != len(id_set) or len(keys) != len(set(keys))
                or any(not isinstance(value, str) or value not in id_set for value in selection["excluded"])):
            raise ValueError("Data participation needs unique source row identities.")
    mark_ids = {*(spec["id"] for spec in state["mark_values"]), "All"}
    seen_ids, seen_names = set(), set()
    for spec in state["combined_groups"]:
        if not isinstance(spec, dict):
            raise ValueError("Invalid combined Group definition.")
        key, name, members = spec.get("id"), str(spec.get("name", "")).strip(), spec.get("members", [])
        if (not isinstance(key, str) or not key.startswith("combined:") or key in seen_ids
                or not name or name.casefold() in seen_names or not isinstance(members, list)
                or any(not isinstance(m, str) or ":" not in m or m.split(":", 1)[0] not in mark_ids for m in members)
                or len(set(members)) < 2):
            raise ValueError("Combined Groups need a unique name, ID and at least two base Groups.")
        spec["name"] = name
        seen_ids.add(key)
        seen_names.add(name.casefold())
    for spec in state["filters"] + state["sort"]:
        if spec.get("table") == "order" and spec.get("column") == "Age":
            spec["column"] = "Mark"
            if spec.get("values") is not None:
                names = {spec["id"]: spec["name"] for spec in state["mark_values"]}
                spec["values"] = [names.get(value, value) for value in spec["values"]]
    if "applied" in source:
        state["applied"] = group_state(source["applied"])
    return state


def applied_state(state):
    return group_state(state.get("applied", state) if state else None)


def row_ids(raw):
    """Identity plus occurrence preserves assignments across regrouping and Final.

    Source position is only used when no identifying columns are available.
    Neither displayed row order nor user-facing head names enter the identity.
    """
    aliases = {normalized(c): c for c in raw}
    columns = [aliases[key] for key in ("waferid", "lotid", "padname", "dieseq") if key in aliases]
    if not columns:
        columns = [c for c in raw if normalized(c) == "cursmefilepath"]
    seen, ids = Counter(), []
    for position, values in enumerate(raw[columns].fillna("").astype(str).values):
        key = tuple(str(v).strip() for v in values) if columns else ("row", str(position))
        ordinal = seen[key]
        seen[key] += 1
        ids.append(json.dumps([columns, key, ordinal], ensure_ascii=False))
    return tuple(ids)


def filter_mask(series, spec):
    text = series.fillna("").astype(str).str.strip()
    mask = np.ones(len(text), dtype=bool)
    if spec.get("values") is not None:
        mask &= text.isin([str(v) for v in spec["values"]]).to_numpy()
    if spec.get("query"):
        mask &= text.str.contains(str(spec["query"]), case=False, regex=False).to_numpy()
    numeric = pd.to_numeric(series, errors="coerce")
    for key, operation in (("minimum", numeric.ge), ("maximum", numeric.le)):
        if spec.get(key) not in (None, ""):
            mask &= operation(float(spec[key])).to_numpy()
    return mask


def participation_ids(raw, selection):
    """Persisted record IDs survive value edits and display sorting; new rows opt in."""
    previous = {record["key"]: record["id"] for record in (selection or {}).get("records", [])}
    return tuple(previous.get(key) or uuid4().hex for key in row_ids(raw))


def participation_source_keys(frame):
    """A file path, when present, distinguishes separately imported measurements."""
    keys = row_ids(frame)
    path = next((column for column in frame if normalized(column) == "cursmefilepath"), None)
    if path is None:
        return keys
    values = frame[path].fillna("").astype(str).str.strip()
    return tuple(json.dumps([key, value], ensure_ascii=False) for key, value in zip(keys, values))


def participation_rows(raw, selection):
    if selection is None:
        return tuple(range(len(raw)))
    excluded = set((selection or {}).get("excluded", []))
    return tuple(i for i, key in enumerate(participation_ids(raw, selection)) if key not in excluded)


class GroupPlan:
    """Resolve inclusion, table order and grouped Trend spans from complete sources."""

    def __init__(self, raw, test_flags=None, state=None, reference=None):
        self.raw = raw
        self.reference = reference if reference is not None else pd.DataFrame(index=range(len(raw)))
        self.state = applied_state(state)
        self.ids = row_ids(raw)
        self.mark_enabled = self.state["mark_enabled"]
        if "flags" in self.state:
            test_flags = pd.DataFrame({"TestFlag": self.state["flags"]})
        if test_flags is None:
            column = next((c for c in raw if normalized(c) == "testflag"), None)
            test_flags = raw[[column]] if column else pd.DataFrame()
        if len(test_flags) > len(raw):
            raise ValueError("TestFlag has more rows than Raw Data. Keep the three tables row-aligned.")
        values = test_flags.iloc[:, 0].tolist() if len(test_flags.columns) else []
        values += [""] * (len(raw) - len(values))
        selected = set(participation_rows(raw, self.state["data_selection"]))
        def parsed_flag(i, value):
            try:
                return flag_value(value)
            except ValueError:
                if i in selected:
                    raise
                return ""
        self.flags = tuple(parsed_flag(i, value) for i, value in enumerate(values))
        names = [self.head(flag) for flag in dict.fromkeys(self.flags) if flag]
        if len(set(names)) != len(names):
            raise ValueError("Head names must be distinct.")
        has_flags = any(flag for flag in self.flags)
        # Stored TestFlags matter only when Head groups is enabled. Mark can
        # group independently without deleting the retained Head assignments.
        head_groups = bool(self.state["enabled"]) and has_flags
        mark_groups = self.mark_enabled and not head_groups
        self.head_groups = head_groups
        self.mark_only = mark_groups
        self.enabled = head_groups or mark_groups
        self.mark_values = tuple(self.state["mark_values"])
        self.mark_names = {spec["id"]: spec["name"] for spec in self.mark_values}
        self.fallback_mark = self.mark_values[0]["id"]
        assigned = {}
        for mark_id, assigned_ids in self.state["mark_rows"].items():
            for row_id in assigned_ids:
                assigned[row_id] = mark_id
        self.marks = tuple(assigned.get(row_id, self.fallback_mark) for row_id in self.ids)
        self.row_groups = tuple(
            f"{mark if self.mark_enabled else 'All'}:{'' if mark_groups else flag}"
            for mark, flag in zip(self.marks, self.flags)
        )
        self.labels = tuple(self.label(key) for key in self.row_groups)
        self.order_frame = pd.DataFrame({"TestFlag": values,
                                         "Head": [self.head(flag) if head_groups else "" for flag in self.flags],
                                         "Mark": [self.mark_names[mark] if self.mark_enabled else ""
                                                  for mark in self.marks],
                                         "Group": self.labels if self.enabled else [""] * len(raw)})
        mask = np.ones(len(raw), dtype=bool)
        for spec in self.state["filters"]:
            if not self.mark_enabled and spec.get("table") == "order" and spec.get("column") == "Mark":
                continue
            series = self.column(spec)
            if series is None:
                if self.state["data_selection"] is not None:
                    continue  # A missing display-filter column cannot veto analysis participation.
                raise ValueError(f"Filter column unavailable: {spec.get('table')} / {spec.get('column')}")
            if (not self.mark_enabled and spec.get("table") == "order"
                    and spec.get("column") == "Group" and spec.get("values") is not None):
                heads = {self.label(f"{age}:{flag}"): self.head(flag)
                         for age in self.mark_names for flag in dict.fromkeys(self.flags)}
                spec = {**spec, "values": [heads.get(value, value) for value in spec["values"]]}
            mask &= filter_mask(series, spec)
        self.visible_rows = tuple(int(i) for i in np.flatnonzero(mask))
        self.included_rows = (tuple(sorted(selected)) if self.state["data_selection"] is not None else self.visible_rows)
        # Sort the complete source once: view filters must not silently remove
        # participating records from the "Current table order" Trend.
        displayed = pd.DataFrame(index=(range(len(raw)) if self.state["data_selection"] is not None else list(self.visible_rows)))
        ascending = []
        for i, spec in enumerate(self.state["sort"]):
            if not self.mark_enabled and spec.get("table") == "order" and spec.get("column") == "Mark":
                continue
            series = self.column(spec)
            if series is None:
                continue
            text = series.fillna("").astype(str).str.strip()
            numeric = pd.to_numeric(text, errors="coerce")
            displayed[str(i)] = numeric if numeric.notna().sum() == text.ne("").sum() else text
            ascending.append(not spec.get("descending", False))
        if len(displayed.columns):
            displayed = displayed.sort_values(list(displayed.columns), ascending=ascending, kind="stable", na_position="last")
        visible = set(self.visible_rows)
        participating = set(self.included_rows)
        self.display_rows = tuple(int(i) for i in displayed.index if i in visible)
        self.analysis_table_rows = tuple(int(i) for i in displayed.index if i in participating)
        names = {normalized(c): c for c in raw}
        wafer = next((names[c] for c in ("waferid", "wafer", "waferno") if c in names), None)
        columns = self.state["identity_columns"]
        if columns is None:
            columns = default_identity_columns(raw, wafer, names.get("lotid"), names.get("padname"))
        columns = [c for c in columns if c in raw]
        primary = wafer if wafer in columns else (columns[0] if columns else None)
        self.identity_columns = columns
        self.measurements = detect_measurements(raw, primary, columns, use_die_seq=False) if primary else []
        assigned = {row for measurement in self.measurements for row in measurement.rows}
        missing = tuple(i for i in range(len(raw)) if i not in assigned)
        if missing:
            self.measurements.append(Measurement("unassigned", "", "", "", missing,
                                                 "Identity pending", "No selected primary identity value."))
        configured = self.state["group_order"]
        if configured == [f"{mark}:{flag}" for mark in self.mark_names for flag in (*DEFAULT_FLAGS, "")]:
            configured = []  # Extend the previous default without altering the saved editing state.
        marks = tuple(self.mark_names) if self.mark_enabled else ("All",)
        flags = flag_order(self.flags) if head_groups else ([""] if mark_groups else [])
        candidates = [f"{mark}:{flag}" for mark in marks for flag in flags]
        order = list(dict.fromkeys(
            [key for key in configured if key in candidates] + candidates
        ))
        self.group_keys = tuple(key for key in order if self.rows(key))
        self.plot_group_keys = self.group_keys + tuple(spec["id"] for spec in self.state["combined_groups"])

    def head(self, flag):
        return self.state["head_names"].get(flag, f"TestFlag {flag}" if flag else "Not provided")

    def label(self, key, *, multiline=False):
        if key.startswith("combined:"):
            return next(spec["name"] for spec in self.state["combined_groups"] if spec["id"] == key)
        if key == "all":
            return getattr(self, "scope_label", "") or "All"
        if ":" not in key:
            # A bare Mark key selects one Mark across every TestFlag.
            return f"{self.mark_names[key]} All" if key in self.mark_names else self.head(key)
        mark, flag = key.split(":", 1)
        if mark == "All":
            return self.head(flag)
        if not flag and self.mark_only:
            # Grouped by Mark alone: the TestFlag column is not part of the name.
            return self.mark_names[mark]
        separator = "\n" if multiline else " "
        return f"{self.mark_names[mark]}{separator}{self.head(flag)}"

    def column(self, spec):
        frame = {"raw": self.raw, "reference": self.reference, "order": self.order_frame}.get(spec.get("table"))
        if frame is None or spec.get("column") not in frame:
            return None
        return frame[spec["column"]].reset_index(drop=True)

    def rows(self, key="all"):
        if key.startswith("combined:"):
            spec = next((s for s in self.state["combined_groups"] if s["id"] == key), None)
            allowed = set(row for member in spec["members"] for row in self.rows(member)) if spec else set()
            return tuple(row for row in self.included_rows if row in allowed)
        if key == "all":
            return self.included_rows
        if ":" not in key:
            if not self.mark_enabled or key not in self.mark_names:
                return ()
            return tuple(i for i in self.included_rows if self.marks[i] == key)
        return tuple(i for i in self.included_rows if self.row_groups[i] == key)

    def trend_spans(self, key="all"):
        """One continuous ordinal axis, with source-aligned wafer and group spans."""
        allowed = set(self.rows(key))
        if not allowed:
            return []
        order = self.state["trend_order"]
        if order == "original":
            rows = [i for i in self.included_rows if i in allowed]
            spans = []
            identities = ({row: (measurement.key, measurement.label) for measurement in self.measurements for row in measurement.rows}
                          if getattr(self, "scope_label", "") else {})
            previous = None
            for row in rows:
                label = self.row_groups[row]
                identity, wafer = identities.get(row, ("", ""))
                boundary = (label, identity)
                if not spans or previous != boundary:
                    spans.append({"group": label, "label": self.label(label) + ("\n" + wafer if wafer else ""), "rows": []})
                spans[-1]["rows"].append(row)
                previous = boundary
            return spans
        names = {normalized(c): c for c in self.raw}
        die = names.get("dieseq")
        die_values = pd.to_numeric(self.raw[die], errors="coerce").to_numpy(float) if die else None
        spans = []
        for group in self.group_keys:
            group_rows = set(self.rows(group)) & allowed
            for measurement in self.measurements:
                rows = [i for i in measurement.rows if i in group_rows]
                if die_values is not None and rows:
                    rows = [rows[i] for i in np.argsort(die_values[rows], kind="stable")]
                if rows:
                    spans.append({"group": group, "label": f"{self.label(group)}\n{measurement.label}", "rows": rows})
        return spans
