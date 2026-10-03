"""One atomic, typed SQLite container for every metrology document.

Only plain tables and JSON cross this interface; no GUI or executable objects.
Column identifiers are generated so duplicate headers can be saved as drafts.
"""
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile

import pandas as pd


FORMAT_VERSION = 1
WORKSPACE_TYPES = {"match_workbook", "wafer_map", "dynamic", "correlation_trend"}
EXTENSIONS = {"match_workbook": ".wkb", "wafer_map": ".wmap", "dynamic": ".wdyn", "correlation_trend": ".wct"}
WORKSPACE_LABELS = {"match_workbook": "Match Workbook", "wafer_map": "Wafer Map / Radius",
                    "dynamic": "Dynamic", "correlation_trend": "Correlation and Trend"}
WORKSPACE_FILTER = "Metrology workspaces (*.wkb *.wmap *.wdyn *.wct)"
_UNCHECKED = object()
REQUIRED_FRAMES = {"match_workbook": {"reference", "raw"}, "wafer_map": {"input_data"},
                   "dynamic": {"input_data"}, "correlation_trend": {"reference_data", "raw_data"}}


@dataclass
class WorkspaceSnapshot:
    workspace_type: str
    frames: dict = field(default_factory=dict)
    states: dict = field(default_factory=dict)
    revision: str | None = None
    warnings: list = field(default_factory=list)


def workspace_path(path, kind):
    """Normalize the final target without erasing dots in a user filename."""
    target = Path(path).expanduser()
    suffix = target.suffix.lower()
    expected = EXTENSIONS[kind]
    if suffix == expected:
        return target.resolve()
    if suffix == ".wkb":  # Explicit legacy-tool migration, never rename the source.
        return target.with_suffix(expected).resolve()
    if suffix in EXTENSIONS.values():
        raise ValueError(f"{WORKSPACE_LABELS[kind]} must be saved as {expected}, not {suffix}.")
    if suffix in (".bak", ".lock", ".tmp"):
        raise ValueError("A backup, lock or temporary file cannot be a save target.")
    return target.with_name(target.name + expected).resolve()


def same_file(first, second):
    if first is None or second is None:
        return False
    first, second = Path(first).resolve(), Path(second).resolve()
    return first == second or (first.exists() and second.exists() and os.path.samefile(first, second))


def json_text(value):
    def scalar(item):
        if hasattr(item, "item"):
            return item.item()
        raise TypeError(f"Unsupported document state: {type(item).__name__}")
    return json.dumps(value, ensure_ascii=False, allow_nan=False, default=scalar)


def file_revision(path):
    """Detect edits by another document instance, not just its file timestamp."""
    path = Path(path)
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate(snapshot):
    if snapshot.workspace_type not in WORKSPACE_TYPES:
        raise ValueError(f"Unknown workspace type: {snapshot.workspace_type}")
    if not REQUIRED_FRAMES[snapshot.workspace_type].issubset(snapshot.frames):
        raise ValueError("This WKB is missing its required measurement tables.")
    if any(not isinstance(scope, str) or not isinstance(state, dict)
           for scope, state in snapshot.states.items()):
        raise ValueError("Invalid WKB document state.")
    if snapshot.workspace_type == "match_workbook" and "match" not in snapshot.states:
        raise ValueError("This WKB is missing its Match settings.")
    if any(not isinstance(name, str) or not isinstance(frame, pd.DataFrame)
           for name, frame in snapshot.frames.items()):
        raise ValueError("Invalid WKB measurement table.")


def _json(payload):
    def invalid_constant(value):
        raise ValueError(f"Invalid non-finite JSON value: {value}")
    return json.loads(payload, parse_constant=invalid_constant)


def _temporary(target):
    handle = tempfile.NamedTemporaryFile(prefix=f".{target.name}-", suffix=".tmp",
                                         dir=target.parent, delete=False)
    handle.close()
    return Path(handle.name)


def save_workspace(path, snapshot, *, expected_revision=_UNCHECKED, backup=True):
    """Replace a complete document only after writing and validating a temp DB.

    Passing the revision returned by load_workspace refuses a stale overwrite.
    Save As intentionally uses the revision of the newly selected destination.
    """
    _validate(snapshot)
    target = workspace_path(path, snapshot.workspace_type)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = target.with_name(target.name + ".lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise ValueError(f"A save is already in progress for {target.name}. "
                         "If the app crashed, remove its .lock file after closing all instances.") from error
    temporary = None
    committed = False
    try:
        os.close(descriptor)
        original_revision = file_revision(target)
        if expected_revision is not _UNCHECKED and original_revision != expected_revision:
            raise ValueError("This WKB changed in another window or application. "
                             "Reopen it or use Save As; the existing file was not overwritten.")
        if original_revision is not None:
            load_workspace(target, expected_type=snapshot.workspace_type)
        temporary = _temporary(target)
        with closing(sqlite3.connect(temporary)) as connection, connection:
            connection.execute("PRAGMA application_id = 1297566530")
            connection.execute("PRAGMA user_version = 1")
            connection.execute("CREATE TABLE workspace_manifest "
                               "(format_version INTEGER, workspace_type TEXT, saved_utc TEXT)")
            connection.execute("INSERT INTO workspace_manifest VALUES (?, ?, ?)",
                               (FORMAT_VERSION, snapshot.workspace_type,
                                datetime.now(timezone.utc).isoformat()))
            connection.execute("CREATE TABLE workspace_state "
                               "(scope TEXT PRIMARY KEY, state_version INTEGER, payload_json TEXT)")
            connection.executemany("INSERT INTO workspace_state VALUES (?, ?, ?)",
                                   [(scope, 2 if scope == "recovery" and state.get("payload_version") == 2 else 1,
                                     json_text(state)) for scope, state in snapshot.states.items()])
            connection.execute("CREATE TABLE frame_catalog "
                               "(name TEXT PRIMARY KEY, table_name TEXT, columns_json TEXT, "
                               "dtypes_json TEXT, row_count INTEGER)")
            for position, (name, frame) in enumerate(snapshot.frames.items()):
                if not isinstance(frame, pd.DataFrame):
                    raise TypeError(f"{name} must be a DataFrame.")
                table = f"frame_{position}"
                columns = list(frame.columns)
                if not all(isinstance(column, str) for column in columns):
                    raise ValueError("Measurement headers must be strings.")
                stored = frame.reset_index(drop=True).copy()
                stored.columns = [f"c{i}" for i in range(len(columns))]
                stored.insert(0, "row_order", range(len(stored)))
                stored.to_sql(table, connection, index=False, chunksize=2000)
                connection.execute("INSERT INTO frame_catalog VALUES (?, ?, ?, ?, ?)",
                                   (name, table, json_text(columns),
                                    json_text([str(dtype) for dtype in frame.dtypes]), len(frame)))
            mappings = snapshot.states.get("match", {}).get("mappings", ())
            if mappings:
                connection.execute("CREATE TABLE parameter_mappings "
                                   "(position INTEGER, name TEXT, reference_column TEXT, raw_column TEXT)")
                connection.executemany("INSERT INTO parameter_mappings VALUES (?, ?, ?, ?)",
                                       [(i, m["name"], m["reference_column"], m["raw_column"])
                                        for i, m in enumerate(mappings)])
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("The saved workspace failed its integrity check.")
        with temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        saved_revision = file_revision(temporary)
        if backup and target.exists():
            backup_path = target.with_name(target.name + ".bak")
            backup_temp = _temporary(backup_path)
            try:
                shutil.copyfile(target, backup_temp)
                with backup_temp.open("r+b") as stream:
                    os.fsync(stream.fileno())
                os.replace(backup_temp, backup_path)
            finally:
                backup_temp.unlink(missing_ok=True)
        if file_revision(target) != original_revision:
            raise ValueError("This workspace changed in another window while saving. Use Save As.")
        os.replace(temporary, target)
        committed = True
        snapshot.revision = saved_revision
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        try:
            lock.unlink(missing_ok=True)
        except OSError:
            if not committed:
                raise
            logging.getLogger(__name__).warning("Workspace saved, but write lock could not be removed: %s", lock)
            snapshot.warnings.append(f"Saved, but write lock could not be removed: {lock}")
    return target


def load_workspace(path, expected_type=None):
    """Read without creating a missing file or partially loading a wrong type."""
    source = Path(path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    revision = file_revision(source)
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "workspace_manifest" not in tables:
                if expected_type not in (None, "match_workbook"):
                    raise ValueError("This legacy WKB is a Match Workbook, not the selected tool.")
                from .matching import MatchWorkbook
                snapshot = MatchWorkbook._load_legacy(source).to_snapshot()
            else:
                manifest = connection.execute("SELECT * FROM workspace_manifest").fetchall()
                if len(manifest) != 1 or manifest[0][0] != FORMAT_VERSION:
                    raise ValueError("Unsupported or invalid WKB container version.")
                kind = manifest[0][1]
                if kind not in WORKSPACE_TYPES or expected_type not in (None, kind):
                    raise ValueError(f"This WKB contains {kind}, not {expected_type or 'a supported workspace'}.")
                states = {}
                for scope, version, payload in connection.execute("SELECT * FROM workspace_state"):
                    if version != 1 and not (scope == "recovery" and version == 2):
                        raise ValueError(f"Unsupported state version for {scope}.")
                    states[scope] = _json(payload)
                    if scope == "recovery" and states[scope].get("payload_version", 1) not in (1, 2):
                        raise ValueError("Unsupported recovery payload version.")
                    if scope == "recovery" and version == 2 and states[scope].get("payload_version") != 2:
                        raise ValueError("Invalid recovery state version.")
                frames = {}
                used_tables = set()
                for name, table, headers, dtypes, row_count in connection.execute("SELECT * FROM frame_catalog"):
                    if not isinstance(table, str) or not re.fullmatch(r"frame_[0-9]+", table) or table in used_tables:
                        raise ValueError("Invalid stored measurement table.")
                    used_tables.add(table)
                    columns, types = _json(headers), _json(dtypes)
                    if (not isinstance(columns, list) or not isinstance(types, list)
                            or not all(isinstance(column, str) for column in columns)
                            or not all(isinstance(dtype, str) for dtype in types)):
                        raise ValueError("Invalid measurement column schema.")
                    frame = pd.read_sql_query(f'SELECT * FROM "{table}" ORDER BY row_order', connection)
                    if (len(frame) != row_count or len(types) != len(columns)
                            or list(frame.columns) != ["row_order", *[f"c{i}" for i in range(len(columns))]]
                            or frame["row_order"].tolist() != list(range(row_count))):
                        raise ValueError(f"Incomplete measurement table: {name}")
                    frame = frame.drop(columns="row_order")
                    for i, dtype in enumerate(types):
                        frame[frame.columns[i]] = frame.iloc[:, i].astype(dtype)
                    frame.columns = columns
                    frames[name] = frame
                snapshot = WorkspaceSnapshot(kind, frames, states)
            _validate(snapshot)
    except (sqlite3.Error, pd.errors.DatabaseError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("This file is not a valid metrology WKB workspace.") from error
    if file_revision(source) != revision:
        raise ValueError("This WKB changed while being loaded. Reopen the latest file.")
    snapshot.revision = revision
    return snapshot
