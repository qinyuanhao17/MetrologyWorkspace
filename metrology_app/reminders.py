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
        self.path = Path(path or os.environ.get('METROLOGY_REMINDERS_PATH')
                         or SETTINGS_PATH.parent / 'reminders.sqlite3')

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=2)) as connection:
            connection.row_factory = sqlite3.Row
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise ValueError('This reminders file needs a newer application version.')
            with connection:
                if version == 0:
                    connection.execute('''CREATE TABLE IF NOT EXISTS reminders (
                        id TEXT PRIMARY KEY, title TEXT NOT NULL, notes TEXT NOT NULL,
                        due_date TEXT, due_time TEXT, flagged INTEGER NOT NULL,
                        completed INTEGER NOT NULL)''')
                    connection.execute('PRAGMA user_version = 1')
                yield connection

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
