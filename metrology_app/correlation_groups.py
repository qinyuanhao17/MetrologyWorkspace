"""Workbook classification preparation without Qt models or widgets."""
from copy import deepcopy
from collections import Counter
import pandas as pd
from .match_groups import row_ids, participation_source_keys, GroupPlan


def prepare_group_context(book, raw, applies):
    raw = book.effective_raw(raw)
    from .match_groups import applied_state, participation_rows, wafer_identity_keys
    effective = applied_state(book.grouping_state)
    if (not (effective["enabled"] or effective["mark_enabled"] or effective["mark2_enabled"])
            and effective["trend_order"] == "groups"
            and (effective["data_selection"] is None or not applies)):
        return None
    state = deepcopy(book.grouping_state)
    identities = list(row_ids(raw))
    flags = (book.test_flags.iloc[:, 0].astype(object).reset_index(drop=True).reindex(range(len(book.raw)))
             if book.test_flags is not None and len(book.test_flags.columns) else pd.Series([""] * len(book.raw)))
    flags = flags.where(flags.notna(), "")
    if applies and len(raw) != len(book.raw):
        rows = list(participation_rows(book.raw, effective["data_selection"]))
        source = book.effective_raw().iloc[rows].reset_index(drop=True).fillna("").astype(str)
        if raw.equals(source):
            flags = flags.iloc[rows]
    full_selection = None
    if not applies and (effective["data_selection"] is not None or effective["filters"]):
        known_ids = {record["key"]: record["id"] for record in
                     (effective["data_selection"] or {}).get("records", ())}
        full_selection = {"records": [{"id": known_ids.get(key, key), "key": key}
                                      for key in identities], "excluded": []}
    for config in (state, state.get("applied", {})):
        if config.get("trend_order") == "wafers":
            # Selected child tables omit rows, not the parent's original
            # first-appearance order. Retain only identity metadata here.
            config["wafer_source_order"] = list(dict.fromkeys(wafer_identity_keys(book.effective_raw()) or ()))
        if "flags" in config:
            config["flags"] = flags.tolist()
        if not applies:
            # Full data ignores the parent's participation restriction, not
            # its classification. Explicit all-record participation also
            # keeps legacy display filters from excluding plotted rows.
            config["data_selection"] = deepcopy(full_selection)
    return {"grouping": state,
                          "wafer_id_mapping": deepcopy(book.wafer_id_mapping),
                          "flags": flags.tolist(),
                          "identities": identities,
                          "provenance": list(participation_source_keys(raw)),
                          "mappings": [{"name": m.name, "reference_column": m.reference_column, "raw_column": m.raw_column} for m in book.mappings],
                          "result_mode": book.result_mode, "match_type": book.match_type}


def prepare_group_result(book, raw, reference, applies):
    raw = book.effective_raw(raw)
    context = prepare_group_context(book, raw, applies)
    plan, error = None, None
    if context:
        try:
            plan = GroupPlan(raw, pd.DataFrame({"TestFlag": context["flags"]}),
                             context["grouping"], reference)
        except ValueError as failure:
            error = str(failure)
    return {"context": context, "comparison": deepcopy(context), "plan": plan, "error": error,
            "raw": raw, "reference": reference, "applies": applies, "book_state": book.grouping_state}


def prepare_trend_parts(plan, split, groups):
    spans = plan.trend_spans()
    labels = {key: plan.label(key, multiline=True) for key in {span["group"] for span in spans}}
    sources = {}
    for name, offset in (("Reference", 0), ("Raw Data", split)):
        keys = [key for key in groups if key[0] == name]
        order = {key: index for index, key in enumerate(keys)}
        owners = {}
        for key in keys:
            for row in set(groups[key]):
                owners.setdefault(row, []).append(key)
        parts = []
        for n, span in enumerate(spans):
            matches = {}
            for row in span["rows"]:
                position = offset + row
                for key in owners.get(position, ()):
                    matches.setdefault(key, []).append(position)
            parts.append((n, span, [(key, tuple(matches[key]))
                                   for key in sorted(matches, key=order.__getitem__)]))
        occurrences = Counter(key for _, _, matches in parts for key, _ in matches)
        sources[name] = (parts, occurrences)
    result = sources, labels
    return result
