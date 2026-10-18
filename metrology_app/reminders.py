"""Application-level reminders, independent of analysis documents and settings."""
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import date, time
from pathlib import Path
import os
import sqlite3
from uuid import uuid4

from .settings import SETTINGS_PATH


@dataclass(frozen=True)
class Reminder:
    title: str
    notes: str = ''
    due_date: date | None = None
    due_time: time | None = None
    flagged: bool = False
    completed: bool = False
    id: str = field(default_factory=lambda: str(uuid4()))


class ReminderStore:
    """Immediately commit each edit; failed writes leave saved reminders intact.

    SQLite also keeps separate application instances from overwriting each
    other's lists. No settings or WKB save operation owns this file.
    """

    def __init__(self, path=None):
        override = path or os.environ.get('METROLOGY_REMINDERS_PATH')
        user_data = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
        self.path = Path(override) if override else user_data / 'MetrologyWorkspace' / 'reminders.sqlite3'
        self._legacy_path = None if override else SETTINGS_PATH.parent / 'reminders.sqlite3'

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=2)) as connection:
            connection.row_factory = sqlite3.Row
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise ValueError('This reminders file needs a newer application version.')
            if version == 0:
                with connection:
                    # Serialize first use, including migration, across app instances.
                    connection.execute('BEGIN IMMEDIATE')
                    version = connection.execute('PRAGMA user_version').fetchone()[0]
                    if version not in (0, 1):
                        raise ValueError('This reminders file needs a newer application version.')
                    if version == 0:
                        rows = self._legacy_rows()
                        connection.execute('''CREATE TABLE IF NOT EXISTS reminders (
                            id TEXT PRIMARY KEY, title TEXT NOT NULL, notes TEXT NOT NULL,
                            due_date TEXT, due_time TEXT, flagged INTEGER NOT NULL,
                            completed INTEGER NOT NULL)''')
                        connection.executemany('INSERT INTO reminders VALUES (?, ?, ?, ?, ?, ?, ?)', rows)
                        connection.execute('PRAGMA user_version = 1')
            with connection:
                yield connection

    def _legacy_rows(self):
        # Only an uninitialized destination imports. Once created, the user file
        # is authoritative: old copies must not restore deleted or edited tasks.
        path = self._legacy_path
        if path is None or path.resolve() == self.path.resolve() or not path.exists():
            return ()
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as source:
            version = source.execute('PRAGMA user_version').fetchone()[0]
            if version != 1:
                raise ValueError(f'Cannot migrate {path}: unsupported reminders version {version}. '
                                 'Keep the original file and use a compatible application version.')
            rows = source.execute('''SELECT id, title, notes, due_date, due_time, flagged, completed
                                     FROM reminders ORDER BY rowid''').fetchall()
            # Reject unreadable legacy dates before committing the destination,
            # so repairing the untouched original allows migration to be retried.
            for row in rows:
                if row[3]:
                    date.fromisoformat(row[3])
                if row[4]:
                    time.fromisoformat(row[4])
            return rows

    def put(self, reminder):
        if not reminder.title.strip():
            raise ValueError('Enter a reminder title.')
        if len(reminder.title) > 500 or len(reminder.notes) > 10000:
            raise ValueError('Use at most 500 characters for the title and 10,000 for notes.')
        if reminder.due_time is not None and reminder.due_date is None:
            raise ValueError('Choose a date before setting a time.')
        with self._connect() as connection:
            connection.execute('''INSERT INTO reminders VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET title=excluded.title, notes=excluded.notes,
                due_date=excluded.due_date, due_time=excluded.due_time,
                flagged=excluded.flagged, completed=excluded.completed''',
                (reminder.id, reminder.title, reminder.notes,
                 reminder.due_date.isoformat() if reminder.due_date else None,
                 reminder.due_time.isoformat() if reminder.due_time else None,
                 int(reminder.flagged), int(reminder.completed)))

    def delete(self, reminder_id):
        with self._connect() as connection:
            connection.execute('DELETE FROM reminders WHERE id = ?', (reminder_id,))

    def items(self, view='All', query='', *, today=None):
        if view not in ('All', 'Today', 'Scheduled', 'Flagged', 'Completed'):
            raise ValueError('Unknown reminders view.')
        with self._connect() as connection:
            rows = connection.execute('SELECT * FROM reminders ORDER BY rowid').fetchall()
        reminders = tuple(Reminder(
            id=row['id'], title=row['title'], notes=row['notes'],
            due_date=date.fromisoformat(row['due_date']) if row['due_date'] else None,
            due_time=time.fromisoformat(row['due_time']) if row['due_time'] else None,
            flagged=bool(row['flagged']), completed=bool(row['completed'])) for row in rows)
        today = today or date.today()
        query = query.strip().casefold()
        return tuple(item for item in reminders
            if item.completed == (view == 'Completed')
            and (view != 'Today' or item.due_date is not None and item.due_date <= today)
            and (view != 'Scheduled' or item.due_date is not None)
            and (view != 'Flagged' or item.flagged)
            and (not query or query in (item.title + '\n' + item.notes).casefold()))
