"""Independent application reminders, through their persistence interface."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from contextlib import closing
from datetime import date, time
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch
import os
import sqlite3
import unittest

from metrology_app import reminders
from metrology_app.reminders import Reminder, ReminderStore


class ReminderTests(unittest.TestCase):
    def test_two_versions_can_initialize_and_save_to_the_same_user_file(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            legacy = root / 'old-source' / 'reminders.sqlite3'
            paper = Reminder('Submit paper')
            ReminderStore(legacy).put(paper)
            review, notebook = Reminder('Review report'), Reminder('Buy notebook')
            start = Barrier(2)

            def add(task):
                store = ReminderStore()
                start.wait(timeout=5)
                store.put(task)

            with patch.dict(os.environ, {'LOCALAPPDATA': str(root / 'user-data'),
                                         'METROLOGY_REMINDERS_PATH': ''}), \
                    patch.object(reminders, 'SETTINGS_PATH', legacy.with_name('settings.yaml')):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(add, task) for task in (review, notebook)]
                    for result in futures:
                        result.result(timeout=10)
                self.assertCountEqual(ReminderStore().items(), (paper, review, notebook))

    def test_old_copies_do_not_overwrite_edits_or_restore_deleted_reminders(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            legacy = root / 'source' / 'reminders.sqlite3'
            paper = Reminder('Submit paper')
            ReminderStore(legacy).put(paper)
            with patch.dict(os.environ, {'LOCALAPPDATA': str(root / 'user-data'),
                                         'METROLOGY_REMINDERS_PATH': ''}), \
                    patch.object(reminders, 'SETTINGS_PATH', legacy.with_name('settings.yaml')):
                store = ReminderStore()
                self.assertEqual(store.items(), (paper,))
                edited = replace(paper, title='Submit revised paper')
                store.put(edited)
                self.assertEqual(ReminderStore().items(), (edited,))
                store.delete(paper.id)
                self.assertEqual(ReminderStore().items(), ())
                portable = root / 'portable' / 'reminders.sqlite3'
                ReminderStore(portable).put(paper)
                with patch.object(reminders, 'SETTINGS_PATH', portable.with_name('settings.yaml')):
                    self.assertEqual(ReminderStore().items(), ())

    def test_explicit_reminder_paths_stay_independent_and_do_not_migrate(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            legacy = root / 'source' / 'reminders.sqlite3'
            ReminderStore(legacy).put(Reminder('Source-only task'))
            original = legacy.read_bytes()
            override = root / 'separate-profile' / 'reminders.sqlite3'
            with patch.dict(os.environ, {'LOCALAPPDATA': str(root / 'user-data'),
                                         'METROLOGY_REMINDERS_PATH': str(override)}), \
                    patch.object(reminders, 'SETTINGS_PATH', legacy.with_name('settings.yaml')):
                custom = ReminderStore()
                self.assertEqual(custom.path, override)
                self.assertEqual(custom.items(), ())
                task = Reminder('Separate profile task')
                custom.put(task)
                other = ReminderStore(root / 'other-profile.sqlite3')
                self.assertEqual(other.items(), ())
                self.assertEqual(ReminderStore().items(), (task,))
                self.assertFalse((root / 'user-data').exists())
            self.assertEqual(legacy.read_bytes(), original)

    def test_unreadable_or_newer_legacy_files_are_kept_and_can_be_retried(self):
        for failure in ('corrupt', 'newer'):
            with self.subTest(failure=failure), TemporaryDirectory() as folder:
                root = Path(folder)
                legacy = root / 'source' / 'reminders.sqlite3'
                paper = Reminder('Submit paper')
                ReminderStore(legacy).put(paper)
                valid = legacy.read_bytes()
                if failure == 'corrupt':
                    legacy.write_bytes(b'Not a SQLite database')
                else:
                    with closing(sqlite3.connect(legacy)) as connection:
                        connection.execute('PRAGMA user_version=99')
                original = legacy.read_bytes()
                with patch.dict(os.environ, {'LOCALAPPDATA': str(root / 'user-data'),
                                             'METROLOGY_REMINDERS_PATH': ''}), \
                        patch.object(reminders, 'SETTINGS_PATH', legacy.with_name('settings.yaml')):
                    with self.assertRaises((sqlite3.DatabaseError, ValueError)):
                        ReminderStore().items()
                    self.assertEqual(legacy.read_bytes(), original)
                    legacy.write_bytes(valid)
                    self.assertEqual(ReminderStore().items(), (paper,))

    def test_invalid_legacy_records_can_be_repaired_and_migration_retried(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            legacy = root / 'old-source' / 'reminders.sqlite3'
            paper = Reminder('Submit paper', due_date=date(2026, 10, 20))
            review = Reminder('Review report', completed=True)
            old_store = ReminderStore(legacy)
            old_store.put(paper)
            old_store.put(review)
            with closing(sqlite3.connect(legacy)) as connection:
                with connection:
                    connection.execute('UPDATE reminders SET due_date=? WHERE id=?',
                                       ('not-a-date', paper.id))
            original = legacy.read_bytes()
            with patch.dict(os.environ, {'LOCALAPPDATA': str(root / 'user-data'),
                                         'METROLOGY_REMINDERS_PATH': ''}), \
                    patch.object(reminders, 'SETTINGS_PATH', legacy.with_name('settings.yaml')):
                with self.assertRaises(ValueError):
                    ReminderStore().items()
                self.assertEqual(legacy.read_bytes(), original)
                old_store.put(paper)
                self.assertEqual(ReminderStore().items(), (paper,))
                self.assertEqual(ReminderStore().items('Completed'), (review,))

    def test_updates_share_automatically_saved_reminders_and_keep_the_old_file(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            legacy = root / 'source' / 'config' / 'reminders.sqlite3'
            paper = Reminder('Submit paper', notes='Check figures first', flagged=True,
                             due_date=date(2026, 10, 20), due_time=time(15, 30))
            reviewed = Reminder('Review report', completed=True)
            old_store = ReminderStore(legacy)
            old_store.put(paper)
            old_store.put(reviewed)
            original = legacy.read_bytes()
            with patch.dict(os.environ, {'LOCALAPPDATA': str(root / 'user-data'),
                                         'METROLOGY_REMINDERS_PATH': ''}):
                with patch.object(reminders, 'SETTINGS_PATH', legacy.with_name('settings.yaml')):
                    updated = ReminderStore()
                    self.assertEqual(updated.path, root / 'user-data' / 'MetrologyWorkspace'
                                     / 'reminders.sqlite3')
                    self.assertEqual(updated.items(), (paper,))
                    self.assertEqual(updated.items('Completed'), (reviewed,))
                    updated.put(replace(paper, title='Submit revised paper'))
                with patch.object(reminders, 'SETTINGS_PATH', root / 'portable-v5' / 'settings.yaml'):
                    reopened = ReminderStore()
                    self.assertEqual(reopened.path, updated.path)
                    self.assertEqual(reopened.items(), (replace(paper, title='Submit revised paper'),))
                    self.assertEqual(reopened.items('Completed'), (reviewed,))
            self.assertEqual(legacy.read_bytes(), original)

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
