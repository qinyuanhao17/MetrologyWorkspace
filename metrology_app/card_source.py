"""Stage-specific settings and source rows for the overall Match Card."""

import math

from .mark2 import labels_for_raw, natural_key


def card_sources(state=None):
    state = {} if state is None else state
    if not isinstance(state, dict) or set(state) - {"preview", "final"}:
        raise ValueError("Invalid Card sources.")
    sources = {}
    for stage in ("preview", "final"):
        source = state.get(stage, {})
        allowed = {"mode", "scope", "manual"}
        if stage == "preview":
            allowed.add("mark2_offset")
        if not isinstance(source, dict) or set(source) - allowed:
            raise ValueError("Invalid Card source settings.")
        mode = source.get("mode", "all")
        if mode not in ("all", "group", "manual"):
            raise ValueError("Invalid Card source mode.")
        scope = source.get("scope")
        if scope is not None:
            if (not isinstance(scope, (list, tuple)) or not all(isinstance(part, str) for part in scope)
                    or not ((len(scope) == 2 and scope[0] == "group" and scope[1])
                            or (len(scope) == 3 and scope[0] == "mark2" and scope[1]))):
                raise ValueError("Invalid Card fit scope.")
            scope = list(scope)
        manual = source.get("manual", [])
        if not isinstance(manual, list):
            raise ValueError("Invalid manual Cards.")
        coefficients = {}
        for row in manual:
            if (not isinstance(row, (list, tuple)) or len(row) != 5
                    or any(not isinstance(name, str) or not name.strip() for name in row[:3])
                    or any(type(value) not in (int, float) for value in row[3:])):
                raise ValueError("Manual Cards require a mapping and finite Slope and Intercept values.")
            try:
                values = tuple(map(float, row[3:]))
            except OverflowError as error:
                raise ValueError("Manual Card values must be finite.") from error
            if not all(map(math.isfinite, values)):
                raise ValueError("Manual Card values must be finite.")
            key = tuple(row[:3])
            if key in coefficients:
                raise ValueError("Duplicate manual Card mapping.")
            coefficients[key] = values
        sources[stage] = {"mode": mode, "scope": scope,
                          "manual": [[*key, *values] for key, values in coefficients.items()]}
        if stage == "preview":
            offset = source.get("mark2_offset", {})
            if (not isinstance(offset, dict) or set(offset) - {"enabled", "field"}
                    or type(offset.get("enabled", False)) is not bool
                    or not isinstance(offset.get("field", ""), str)):
                raise ValueError("Invalid Mark2 offset settings.")
            sources[stage]["mark2_offset"] = {"enabled": offset.get("enabled", False),
                                               "field": offset.get("field", "")}
    return sources


def mapping_key(mapping):
    return mapping.name, mapping.reference_column, mapping.raw_column


def manual_cards(source):
    return {tuple(row[:3]): tuple(row[3:]) for row in source["manual"]}


def fit_rows(source, plan, workbook_type):
    if source["mode"] == "all":
        return plan.included_rows
    scope = source["scope"]
    if source["mode"] == "manual" or not scope:
        return ()
    if scope[0] == "group":
        return plan.rows(scope[1]) if scope[1] in plan.plot_group_keys else ()
    field, value = scope[1:]
    if not value or workbook_type != "type2" or not plan.mark2_enabled:
        return ()
    labels = mark2_field_labels(plan, field)
    if labels is None:
        return ()
    return tuple(row for row in plan.included_rows if labels[row] == value)


def mark2_field_labels(plan, field):
    if not plan.mark2_enabled or field not in plan.state["mark2"]["columns"]:
        return None
    mark2 = plan.state["mark2"]
    if field in mark2["selected"]:
        labels, index = plan.mark2_labels, mark2["selected"].index(field)
    else:
        labels, index = labels_for_raw(plan.raw, {**mark2, "selected": [field]}), 0
    return tuple(values[index] for values in labels)


def mark2_values(plan, field):
    if plan is None or not plan.mark2_enabled:
        return ()
    mark2 = plan.state["mark2"]
    if field not in mark2["columns"]:
        return ()
    index = mark2["columns"].index(field)
    return tuple(sorted({record["values"][index] for record in mark2["records"]
                         if record["values"][index]}, key=natural_key))
