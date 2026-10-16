"""Independent application reminders, through their persistence interface."""
from dataclasses import replace
from contextlib import closing
from datetime import date, time
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from metrology_app.reminders import Reminder, ReminderStore


class ReminderTests(unittest.TestCase):
    def test_invalid_edits_and_newer_files_never_replace_existing_reminders(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'reminders.sqlite3'
            store = ReminderStore(path)
            task = Reminder('Keep measurements unchanged')
            store.put(task)
            with self.assertRaisesRegex(ValueError, 'title'):
                store.put(replace(task, title='   '))
            self.assertEqual(store.items(), (task,))
            with closing(sqlite3.connect(path)) as connection:
                connection.execute('PRAGMA user_version=99')
                connection.commit()
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'newer'):
                store.put(replace(task, title='Do not overwrite'))
            self.assertEqual(path.read_bytes(), original)

    def test_two_application_instances_preserve_each_others_reminders(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'reminders.sqlite3'
            first, second = ReminderStore(path), ReminderStore(path)
            paper, review = Reminder('Submit paper'), Reminder('Review report')
            first.put(paper)
            second.put(review)
            first.put(replace(paper, completed=True))
            self.assertEqual(second.items(), (review,))
            self.assertEqual(second.items('Completed'), (replace(paper, completed=True),))

    def test_smart_views_search_and_overdue_dates_do_not_change_saved_tasks(self):
        with TemporaryDirectory() as folder:
            store = ReminderStore(Path(folder) / 'reminders.sqlite3')
            overdue = Reminder('Review NOVA report', due_date=date(2026, 10, 15))
            future = Reminder('Submit paper', due_date=date(2026, 10, 20), flagged=True)
            undated = Reminder('Buy notebook', notes='For NOVA notes')
            for task in (overdue, future, undated):
                store.put(task)
            self.assertEqual(store.items('Today', today=date(2026, 10, 16)), (overdue,))
            self.assertEqual(store.items('Scheduled'), (overdue, future))
            self.assertEqual(store.items('Flagged'), (future,))
            self.assertEqual(store.items(query='nova'), (overdue, undated))
            self.assertEqual(store.items(), (overdue, future, undated))

    def test_reminder_edits_and_completion_survive_reopen_without_a_workbook(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'reminders.sqlite3'
            store = ReminderStore(path)
            task = Reminder('Submit paper', due_date=date(2026, 10, 20),
                            due_time=time(15, 30), notes='Check figures first', flagged=True)
            store.put(task)
            self.assertEqual(ReminderStore(path).items(), (task,))
            edited = replace(task, title='Submit revised paper', completed=True)
            store.put(edited)
            self.assertEqual(ReminderStore(path).items('Completed'), (edited,))
            self.assertEqual(store.items(), ())
            store.put(replace(edited, completed=False))
            store.delete(task.id)
            self.assertEqual(ReminderStore(path).items(), ())


if __name__ == '__main__':
    unittest.main()
