"""Detached table preparation for automatic Workbook child refreshes."""
from .sheet import prepare_sheet_frame, prepare_sheet_version


def copy_linked_workbook(book):
    """Detach a request, copying proven string record tables without recursion."""
    from copy import deepcopy
    memo = {}
    for state in (book.grouping_state, book.grouping_state.get('applied', {})):
        records = (state.get('data_selection') or {}).get('records')
        if (isinstance(records, list) and id(records) not in memo
                and all(type(record) is dict and all(type(key) is str and type(value) is str
                        for key, value in record.items()) for record in records)):
            copied = []
            memo[id(records)] = copied
            for record in records:
                if id(record) not in memo:
                    memo[id(record)] = record.copy()
                copied.append(memo[id(record)])
    return deepcopy(book, memo)


def prepare_linked_values(frame, baseline, *, cancelled=None):
    """Qualify a detached numeric-only Correlation update, without Qt mutation."""
    import numpy as np
    import pandas as pd
    from .data import number
    from .sheet_batch import ColumnChanges, ColumnDelta
    if baseline is None:
        return None
    previous = baseline['document']
    document = frame.fillna('').astype(str).reset_index(drop=True)
    document.columns = [str(name) for name in document.columns]
    try:
        same_attributes = (document.attrs == previous.attrs
                           and previous.attrs == baseline['analysis'].attrs)
    except (TypeError, ValueError):
        return None  # Uncertain provenance/metadata must retain full loading.
    if (document.empty or document.size < 8192 or document.shape != previous.shape
            or not document.columns.equals(previous.columns) or not document.columns.is_unique
            or any(not name or name != name.strip() for name in document.columns)
            or not same_attributes or not previous.equals(baseline['analysis'])):
        return None
    allowed = set(baseline['numeric_columns']) - set(baseline['identity_columns'])
    parts = []
    changed_rows = np.zeros(len(document), dtype=bool)
    for column, name in enumerate(document.columns):
        if cancelled is not None and cancelled():
            raise InterruptedError('Linked source update cancelled')
        old = previous.iloc[:, column].to_numpy()
        new = document.iloc[:, column].to_numpy()
        positions = np.flatnonzero(old != new)
        if not len(positions):
            continue
        if column == 0 or name not in allowed:
            return None
        old_values, new_values = old[positions], new[positions]
        if not (number(pd.Series(old_values)).notna().all()
                and number(pd.Series(new_values)).notna().all()):
            return None
        rows = (range(1, len(document) + 1) if len(positions) == len(document)
                else tuple(int(position) + 1 for position in positions))
        parts.append(ColumnDelta(column, rows, tuple(old_values), tuple(new_values)))
        changed_rows[positions] = True
    if not parts:
        return None
    values = ColumnChanges(tuple(parts), 'after', int(np.count_nonzero(changed_rows)))
    return {'document': document, 'analysis': document.copy(deep=True),
            'base_document': previous, 'value_changes': values,
            'base_revision': baseline['revision'], 'value_context': baseline['context']}


def prepare_linked_sources(request, cancelled):
    if cancelled():
        return None
    book = request["book"]
    from .input_planning import prepare_workbook_participation
    participation = prepare_workbook_participation(book) if book is not None else None
    prepared = {}
    for key, kind, stage, follows, locked, options in request["children"]:
        if cancelled():
            return None
        if not follows:
            continue
        if kind == "correlation":
            frame = request["raw"]
        elif kind == "map" and book is not None:
            if book.match_type == "TEM":
                source = book.final_match_raw if stage == "final" and book.final_match_raw is not None else book.raw
                frame = book.participating_frame(source, paired_source=True, apply_selection=False)
            else:
                frame = book.stage_frame(stage, apply_card=False, apply_selection=False, use_snapshot=False)
        else:
            continue
        if locked:
            # Locked metadata is merged and validated against the live child.
            # Its final frame may differ from the parent's prepared table.
            continue
        table = (prepare_linked_values(frame, options.get('value_baseline'), cancelled=cancelled)
                 if kind == 'correlation' else None)
        if table is None and kind == 'correlation':
            version = request.get('raw_version')
            if version is None:
                from .table_version import LiteralTableVersion
                try:
                    version = LiteralTableVersion.from_frame(frame)
                except (TypeError, ValueError):
                    pass  # Unnormalized/sparse inputs keep the ordinary loader.
            table = prepare_sheet_version(frame, version,
                                          source=request.get('raw_source'))
        elif table is None and kind == 'map':
            from .table_version import LiteralTableVersion
            table = prepare_sheet_version(frame, LiteralTableVersion.from_frame(frame))
        table = prepared[key] = table if table is not None else prepare_sheet_frame(frame)
        table["source_frame"] = frame
        if table.get('version') is not None:
            table['load_frame'] = table['document']
        current = options.get('document')
        if current is not None and table.get('version') is not None:
            document = table['document']
            same_document = document.equals(current)
            same_values = same_document
            if (not same_document and document.shape == current.shape
                    and not document.columns.equals(current.columns)):
                same_values = current.set_axis(document.columns, axis=1, copy=False).equals(document)
            table['comparison'] = (options['revision'], same_document, same_values)
        analysis = table["analysis"]
        if cancelled():
            return None
        if analysis is not None and not options["carded"] and 'value_changes' not in table:
            from .input_planning import prepare_measurement_choices
            table["recognition"] = {"frame": analysis,
                "include_fit_quality": options["include_fit_quality"],
                "choices": prepare_measurement_choices(analysis,
                    include_fit_quality=options["include_fit_quality"])}
        if cancelled():
            return None
        if kind == "correlation" and book is not None and analysis is not None:
            from .correlation_groups import prepare_group_result, prepare_trend_parts
            group_result = table["group_result"] = prepare_group_result(book, analysis,
                options["reference"], options["applies"])
            if group_result["plan"] is not None and not cancelled():
                groups, split = options["trend_groups"], len(options["reference"])
                group_result["trend_parts"] = (group_result["plan"], split, groups,
                    prepare_trend_parts(group_result["plan"], split, groups))
    return {"generation": request["generation"], "book": book,
            "inputs": request["inputs"], "tables": prepared, "participation": participation}
