"""Export matching reference values in the active Raw table's source order."""
from pathlib import Path

import numpy as np
import pandas as pd

from .card_source import mark2_field_labels
from .match_groups import applied_state


def ref_mappings(book, raw):
    positions = {column: index for index, column in enumerate(raw.columns)}
    return sorted(book.mappings, key=lambda mapping: positions[mapping.raw_column])


def ref_offset_option(book):
    """Return the active Offset field or the reason REF compensation is unavailable."""
    if book.workbook_type != "type2":
        return None, "Mark2 Offset is available in Type2 Preview."
    if book.result_mode != "preview":
        return None, "Switch to Preview to export REF with Mark2 Offset."
    offset = book.card_sources["preview"]["mark2_offset"]
    state = applied_state(book.grouping_state)
    field = offset["field"]
    if not state["mark2_enabled"] or not state["mark2"]["records"]:
        return None, "Enable Mark2, load its labels, and apply the group settings."
    if not offset["enabled"]:
        return None, "Enable By Mark2 Offset under Card setting."
    if field not in state["mark2"]["columns"]:
        return None, "Select a Mark2 field under By Mark2 Offset."
    return field, ""


def write_ref(path, book, raw, mappings, *, offset_result=None):
    from openpyxl import Workbook

    from .excel_export import _write_frame, save_atomic

    field, _ = ref_offset_option(book) if offset_result is not None else (None, "")
    if field is not None:
        alignment = offset_result.id_alignment
        labels = pd.Series(mark2_field_labels(offset_result.group_plan, field), dtype=object)
        offsets = offset_result.mark2_offset_table()
    elif book.workbook_type == "type2":
        alignment = book.id_alignment(raw)
    else:
        alignment = None
    reference = (alignment.reference if alignment is not None else
                 book.reference.reset_index(drop=True).reindex(range(len(raw)), fill_value=""))

    columns = {}
    compensated_rows = {}
    for mapping in mappings:
        values = reference[mapping.reference_column].astype(object).copy()
        if field is not None:
            adjustment = labels.map(offsets[mapping.name]).to_numpy(float)
            numeric = pd.to_numeric(values, errors="coerce").to_numpy(float)
            corrected = numeric - adjustment
            rows = np.flatnonzero(np.isfinite(corrected))
            values.iloc[rows] = np.round(corrected[rows], 4)
            compensated_rows[mapping.name] = rows
        columns[mapping.name] = values

    target = Path(path).with_suffix(".xlsx")
    workbook = Workbook()
    try:
        sheet = workbook.active
        sheet.title = "REF"
        sheet.freeze_panes = "A2"
        _write_frame(sheet, pd.DataFrame(columns))
        for column, name in enumerate(columns, 1):
            for row in compensated_rows.get(name, ()):
                sheet.cell(int(row) + 2, column).number_format = "0.0000"
        return save_atomic(workbook, target)
    finally:
        workbook.close()
