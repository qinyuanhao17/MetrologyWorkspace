"""Storage for rich-text notes and their attached tables."""

from contextlib import closing
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
from time import time_ns
from uuid import uuid4


WORKBOOK_NOTES_SCOPE = "workbook_notes"


def workbook_note_records(state):
    """Validate the optional JSON state used by a Match Workbook."""
    if state is None:
        return {}
    records = state.get("notes") if isinstance(state, dict) else None
    if not isinstance(records, dict):
        raise ValueError("Invalid Workbook Note state.")
    for note_id, note in records.items():
        if (not isinstance(note_id, str) or not note_id or not isinstance(note, dict)
                or not isinstance(note.get("title"), str) or not note["title"].strip()
                or type(note.get("created_at")) is not int or not 0 <= note["created_at"] < 2**63
                or type(note.get("pinned")) is not bool or not isinstance(note.get("html"), str)
                or not isinstance(note.get("tables"), dict)):
            raise ValueError("Invalid note in Workbook Note state.")
        for table_id, table in note["tables"].items():
            if (not isinstance(table_id, str) or not table_id or not isinstance(table, dict)
                    or not isinstance(table.get("title"), str) or not table["title"].strip()):
                raise ValueError("Invalid table in a Workbook Note.")
            columns, rows = table.get("columns"), table.get("rows")
            if (not isinstance(columns, list) or not all(isinstance(column, str) for column in columns)
                    or not isinstance(rows, list) or any(not isinstance(row, list) or len(row) != len(columns)
                        or not all(isinstance(cell, str) for cell in row) for row in rows)):
                raise ValueError("Invalid table cells in a Workbook Note.")
    return records


class NoteStore:
    def __init__(self):
        user_data = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        self.path = user_data / "MetrologyWorkspace" / "notes.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    html TEXT NOT NULL DEFAULT '',
                    tables TEXT NOT NULL DEFAULT '{}'
                )
            """)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=1)
        db.row_factory = sqlite3.Row
        return db

    def list_notes(self):
        with closing(self._connect()) as db:
            return db.execute("""
                SELECT id, title, pinned, created_at, html FROM notes
                ORDER BY pinned DESC, created_at DESC, id DESC
            """).fetchall()

    def create(self, title):
        with closing(self._connect()) as db, db:
            return db.execute("INSERT INTO notes (title, created_at) VALUES (?, ?)",
                              (title, time_ns())).lastrowid

    def load(self, note_id):
        with closing(self._connect()) as db:
            row = db.execute("SELECT title, html, tables FROM notes WHERE id = ?", (note_id,)).fetchone()
        if row is None:
            raise sqlite3.OperationalError("This note no longer exists.")
        return row["title"], row["html"], json.loads(row["tables"])

    def save(self, note_id, html, tables, *, title=None):
        with closing(self._connect()) as db, db:
            cursor = db.execute("UPDATE notes SET title = COALESCE(?, title), html = ?, tables = ? WHERE id = ?",
                                (title, html, json.dumps(tables, ensure_ascii=False), note_id))
            if cursor.rowcount != 1:
                raise sqlite3.OperationalError("This note no longer exists.")

    def rename(self, note_id, title):
        with closing(self._connect()) as db, db:
            cursor = db.execute("UPDATE notes SET title = ? WHERE id = ?", (title, note_id))
            if cursor.rowcount != 1:
                raise sqlite3.OperationalError("This note no longer exists.")

    def set_pinned(self, note_id, pinned):
        with closing(self._connect()) as db, db:
            db.execute("UPDATE notes SET pinned = ? WHERE id = ?", (pinned, note_id))

    def delete(self, note_id):
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM notes WHERE id = ?", (note_id,))


class WorkbookNoteStore:
    """Own one workbook's editable notes until its document is saved."""

    def __init__(self, state=None):
        self._notes = deepcopy(workbook_note_records(state))

    def list_notes(self):
        ordered = sorted(reversed(self._notes.items()),
                         key=lambda pair: (pair[1]["pinned"], pair[1]["created_at"]), reverse=True)
        fields = ("title", "pinned", "created_at", "html")
        return [{"id": note_id, **{field: note[field] for field in fields}} for note_id, note in ordered]

    def create(self, title):
        note_id = uuid4().hex
        self._notes[note_id] = {"title": title, "created_at": time_ns(), "pinned": False, "html": "", "tables": {}}
        return note_id

    def _note(self, note_id):
        note = self._notes.get(note_id)
        if note is None:
            raise sqlite3.OperationalError("This note no longer exists.")
        return note

    def load(self, note_id):
        note = self._note(note_id)
        return note["title"], note["html"], deepcopy(note["tables"])

    def save(self, note_id, html, tables, *, title=None):
        note = self._note(note_id)
        note.update(html=html, tables=deepcopy(tables))
        if title is not None:
            note["title"] = title

    def rename(self, note_id, title):
        self._note(note_id)["title"] = title

    def set_pinned(self, note_id, pinned):
        self._note(note_id)["pinned"] = bool(pinned)

    def delete(self, note_id):
        self._notes.pop(note_id, None)

    def snapshot(self, draft=None):
        """Borrow the current state, with the open editor's pending edits if any."""
        notes = self._notes
        if draft is not None:
            note_id, title, html, tables = draft
            note = dict(self._note(note_id), title=title, html=html, tables=tables)
            notes = {**notes, note_id: note}
        return {"notes": notes} if notes else None
