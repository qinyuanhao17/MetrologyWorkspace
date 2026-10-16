"""Home-screen reminders are saved separately from analysis tools."""
import os
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QDate, QTimer
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDateEdit, QDialogButtonBox, QLabel, QLineEdit,
                            QListWidget, QMessageBox, QPushButton, QToolButton, QWidget)
from metrology_app.module_registry import ComponentRegistry, ComponentSpec
from metrology_app.reminders import Reminder, ReminderStore
from metrology_app.shell import MainWindow

APP = QApplication.instance() or QApplication([])


class ReminderPanelTests(unittest.TestCase):
    def test_long_titles_wrap_and_completion_can_be_restored_before_deletion(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'reminders.sqlite3'
            title = 'Review the NOVA data and check all measurement groups before submitting the revised paper'
            ReminderStore(path).put(Reminder(title))
            shell = MainWindow(reminders_path=path)
            try:
                shell.show()
                APP.processEvents()
                tasks = shell.findChild(QListWidget, 'reminderList')
                row = tasks.itemWidget(tasks.item(0))
                label = row.findChild(QLabel, 'reminderText')
                self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))
                row.findChild(QToolButton, 'reminderCheck').click()
                self.assertEqual(tasks.count(), 0)
                shell.findChild(QPushButton, 'reminderCompleted').click()
                self.assertEqual(tasks.count(), 1)
                self.assertFalse(any(button.isChecked() for button in shell.findChildren(QPushButton)
                                     if button.objectName() == 'reminderFilter'))
                tasks.itemWidget(tasks.item(0)).findChild(QToolButton, 'reminderCheck').click()
                self.assertEqual(tasks.count(), 0)
                buttons = [button for button in shell.findChildren(QPushButton)
                           if button.objectName() == 'reminderFilter']
                next(button for button in buttons if button.text().startswith('All ')).click()
                self.assertEqual(tasks.count(), 1)
                tasks.setCurrentRow(0)
                from PyQt6.QtCore import Qt
                from PyQt6.QtTest import QTest
                tasks.setFocus()
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
                    QTest.keyClick(tasks, Qt.Key.Key_Delete)
                self.assertEqual(tasks.count(), 1)
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                    QTest.keyClick(tasks, Qt.Key.Key_Delete)
                self.assertEqual(tasks.count(), 0)
                self.assertEqual(ReminderStore(path).items(), ())
            finally:
                shell.close()
                shell.deleteLater()
                APP.processEvents()

    def test_add_from_home_then_reopen_and_switch_tools_without_losing_reminders(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'reminders.sqlite3'
            registry = ComponentRegistry()
            registry.register(ComponentSpec('sample', 'Sample', '', 'Test', QWidget))
            shell = MainWindow(registry, reminders_path=path)
            try:
                shell.show()
                failures = []
                def enter_reminder():
                    dialog = APP.activeModalWidget()
                    try:
                        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
                        self.assertTrue(dialog.isVisible(), 'An empty title must not be saved')
                        dialog.findChild(QLineEdit, 'reminderTitleInput').setText('Submit revised paper')
                        dialog.findChild(QCheckBox, 'reminderDateEnabled').setChecked(True)
                        dialog.findChild(QDateEdit, 'reminderDateInput').setDate(QDate(2026, 10, 20))
                        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
                    except Exception as error:
                        failures.append(error)
                        if dialog:
                            dialog.reject()
                QTimer.singleShot(0, enter_reminder)
                shell.findChild(QToolButton, 'newReminder').click()
                self.assertEqual(failures, [])
                shell.open_component('sample')
                self.assertIn('Submit revised paper', [label.text() for label in shell.findChildren(QLabel)])
                self.assertNotIn('CURRENT SESSION', [label.text() for label in shell.findChildren(QLabel)])
            finally:
                shell.close()
                shell.deleteLater()
                APP.processEvents()
            reopened = MainWindow(registry, reminders_path=path)
            try:
                self.assertIn('Submit revised paper', [label.text() for label in reopened.findChildren(QLabel)])
                self.assertEqual(ReminderStore(path).items()[0].due_date, date(2026, 10, 20))
            finally:
                reopened.close()
                reopened.deleteLater()
                APP.processEvents()
