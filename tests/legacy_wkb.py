"""Write genuine pre-unification fixtures; production writes only the new format."""
from contextlib import closing
import json
import sqlite3

import pandas as pd

from metrology_app.matching.analysis import _write_frame, SCHEMA_VERSION


def save_legacy(workbook, path):
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "match_type": workbook.match_type, "result_mode": workbook.result_mode,
        "bias_mode": workbook.bias_mode, "bias_views": ",".join(workbook.bias_views),
        "setup_splitter_sizes": None if workbook.setup_splitter_sizes is None else
            ",".join(map(str, workbook.setup_splitter_sizes)),
        "saved_utc": "2026-09-01T00:00:00+00:00",
    }
    for name in ("parameter_order", "workspace_selections", "correlation_selections", "trend_axis_settings"):
        metadata[name] = json.dumps(getattr(workbook, name))
    with closing(sqlite3.connect(path)) as connection, connection:
        pd.DataFrame([metadata]).to_sql("metadata", connection, index=False)
        pd.DataFrame([{"position": i, "name": m.name, "reference_column": m.reference_column,
                       "raw_column": m.raw_column} for i, m in enumerate(workbook.mappings)]).to_sql(
            "parameter_mappings", connection, index=False)
        for name in ("reference", "raw", "preview_raw", "final_raw", "final_match_raw",
                     "preview_map", "final_map", "preview_dynamic", "final_dynamic"):
            frame = getattr(workbook, name)
            if frame is not None:
                _write_frame(connection, name + "_data", frame)
    return path
