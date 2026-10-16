"""A small, local-first reminders list for the home screen."""
from dataclasses import replace
from datetime import date, datetime, timedelta
import sqlite3

from PyQt6.QtCore import QDate, QSize, QTime, Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QTimeEdit, QToolButton, QVBoxLayout,
)

from .reminders import Reminder, ReminderStore


class ReminderDialog(QDialog):
    def __init__(self, reminder=None, parent=None):
        super().__init__(parent)
        self.reminder = reminder or Reminder('')
        self.setWindowTitle('Edit reminder' if reminder else 'New reminder')
        self.resize(420, 360)
        layout = QFormLayout(self)
        self.title_input = QLineEdit(self.reminder.title, objectName='reminderTitleInput')
        self.title_input.setPlaceholderText('What do you want to remember?')
        self.title_input.setMaxLength(500)
        layout.addRow('Title', self.title_input)
        self.notes_input = QPlainTextEdit(self.reminder.notes)
        self.notes_input.setPlaceholderText('Notes (optional)')
        self.notes_input.setMaximumHeight(100)
        layout.addRow('Notes', self.notes_input)
        self.date_enabled = QCheckBox('Date', objectName='reminderDateEnabled')
        self.date_enabled.setChecked(self.reminder.due_date is not None)
        self.date_input = QDateEdit(QDate(self.reminder.due_date or date.today()),
                                    calendarPopup=True, objectName='reminderDateInput')
        self.date_input.setDisplayFormat('yyyy-MM-dd')
        self.date_input.setEnabled(self.date_enabled.isChecked())
        self.date_enabled.toggled.connect(self.date_input.setEnabled)
        layout.addRow(self.date_enabled, self.date_input)
        self.time_enabled = QCheckBox('Time', objectName='reminderTimeEnabled')
        self.time_enabled.setChecked(self.reminder.due_time is not None)
        self.time_enabled.setEnabled(self.date_enabled.isChecked())
        self.time_input = QTimeEdit(QTime(self.reminder.due_time) if self.reminder.due_time
                                   else QTime(9, 0), objectName='reminderTimeInput')
        self.time_input.setDisplayFormat('HH:mm')
        self.time_input.setEnabled(self.date_enabled.isChecked() and self.time_enabled.isChecked())
        self.time_enabled.toggled.connect(self.time_input.setEnabled)
        self.date_enabled.toggled.connect(self._date_toggled)
        layout.addRow(self.time_enabled, self.time_input)
        self.flagged = QCheckBox('Flagged')
        self.flagged.setChecked(self.reminder.flagged)
        layout.addRow('', self.flagged)
        self.error = QLabel('', objectName='reminderError')
        self.error.setWordWrap(True)
        layout.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        self.title_input.setFocus()

    def _date_toggled(self, enabled):
        self.time_enabled.setEnabled(enabled)
        self.time_input.setEnabled(enabled and self.time_enabled.isChecked())

    def value(self):
        return replace(self.reminder, title=self.title_input.text().strip(),
            notes=self.notes_input.toPlainText(), flagged=self.flagged.isChecked(),
            due_date=self.date_input.date().toPyDate() if self.date_enabled.isChecked() else None,
            due_time=self.time_input.time().toPyTime()
                if self.date_enabled.isChecked() and self.time_enabled.isChecked() else None)

    def accept(self):
        if not self.title_input.text().strip():
            self.error.setText('Enter a reminder title.')
            self.title_input.setFocus()
        else:
            super().accept()


class _ReminderList(QListWidget):
    def fit_rows(self):
        width = max(100, self.viewport().width())
        for index in range(self.count()):
            item = self.item(index)
            row = self.itemWidget(item)
            if row is not None:
                row.ensurePolished()
                height = max(row.minimumSizeHint().height(), row.layout().totalHeightForWidth(width))
                item.setSizeHint(QSize(width, height))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_rows()


class ReminderPanel(QFrame):
    def __init__(self, path=None, parent=None):
        super().__init__(parent, objectName='remindersCard')
        self.store = ReminderStore(path)
        self.view = 'All'
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(QLabel('Reminders', objectName='remindersTitle'))
        header.addStretch()
        self.count = QLabel('0', objectName='remindersCount')
        header.addWidget(self.count)
        layout.addLayout(header)
        self.filters = QButtonGroup(self)
        self.buttons = {}
        grid = QGridLayout()
        grid.setSpacing(6)
        for index, view in enumerate(('Today', 'Scheduled', 'All', 'Flagged')):
            button = QPushButton(view, objectName='reminderFilter')
            button.setCheckable(True)
            button.clicked.connect(lambda _checked, name=view: self.set_view(name))
            self.filters.addButton(button)
            self.buttons[view] = button
            grid.addWidget(button, index // 2, index % 2)
        layout.addLayout(grid)
        self.search = QLineEdit(objectName='reminderSearch')
        self.search.setPlaceholderText('Search reminders')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)
        self.status = QLabel('', objectName='muted')
        layout.addWidget(self.status)
        self.list = _ReminderList(objectName='reminderList')
        self.list.setMinimumHeight(100)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.list.itemActivated.connect(lambda item: self.edit(item.data(Qt.ItemDataRole.UserRole)))
        layout.addWidget(self.list, 1)
        self.empty = QLabel('', objectName='muted')
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty)
        footer = QHBoxLayout()
        self.completed = QPushButton('Completed', objectName='reminderCompleted')
        self.completed.setCheckable(True)
        self.filters.addButton(self.completed)
        self.completed.clicked.connect(lambda checked: self.set_view('Completed' if checked else 'All'))
        footer.addWidget(self.completed)
        footer.addStretch()
        self.add_button = QToolButton(objectName='newReminder')
        self.add_button.setText('+')
        self.add_button.setFixedSize(38, 38)
        self.add_button.setAccessibleName('New reminder')
        self.add_button.setToolTip('New reminder')
        self.add_button.clicked.connect(lambda: self.edit())
        footer.addWidget(self.add_button)
        layout.addLayout(footer)
        self.setToolTip('Saved automatically, independently of all Tools and WKB files.\n'
                        'Double-click or press F2 to edit. Right-click for more actions.')
        for key, callback in (('F2', self._edit_current), ('Delete', self._delete_current)):
            shortcut = QShortcut(QKeySequence(key), self.list)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(callback)
        self.timer = QTimer(self)
        self.timer.setInterval(60000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def set_view(self, view):
        self.view = view
        self.refresh()

    def refresh(self, *_args):
        try:
            active = self.store.items()
            done = self.store.items('Completed')
            rows = self.store.items(self.view, self.search.text())
            for view, button in self.buttons.items():
                button.setText(f'{view}  {len(self.store.items(view))}')
                button.setChecked(view == self.view)
            self.completed.setText(f'Completed ({len(done)})')
            self.completed.setChecked(self.view == 'Completed')
            self.count.setText(str(len(active)))
            overdue = sum(self._overdue(item) for item in active)
            self.status.setWordWrap(False)
            self.status.setText(f'{len(active)} remaining' + (f' · {overdue} overdue' if overdue else ''))
            self.status.setObjectName('muted')
            self.add_button.setEnabled(True)
        except (OSError, sqlite3.Error, ValueError) as error:
            self.status.setWordWrap(True)
            self.status.setText(f'Cannot load reminders: {error}\nYour file has not been replaced. Retry in a minute.')
            self.add_button.setEnabled(False)
            return
        current = self.list.currentItem()
        selected = current.data(Qt.ItemDataRole.UserRole).id if current else None
        scroll = self.list.verticalScrollBar().value()
        self.list.clear()
        for task in rows:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, task)
            item.setToolTip(task.title + ('\n' + task.notes if task.notes else ''))
            row = QFrame(objectName='reminderRow')
            box = QHBoxLayout(row)
            box.setContentsMargins(2, 12, 2, 12)
            box.setSpacing(10)
            check = QToolButton(objectName='reminderCheck')
            check.setCheckable(True)
            check.setChecked(task.completed)
            check.setText('✓' if task.completed else '')
            check.setFixedSize(24, 24)
            check.setAccessibleName(('Restore ' if task.completed else 'Complete ') + task.title)
            check.clicked.connect(lambda checked, value=task: self._save(replace(value, completed=checked)))
            box.addWidget(check, alignment=Qt.AlignmentFlag.AlignTop)
            text = QVBoxLayout()
            text.setSpacing(3)
            title = QLabel(task.title + (' · Flagged' if task.flagged else ''), objectName='reminderText')
            title.setTextFormat(Qt.TextFormat.PlainText)
            title.setWordWrap(True)
            font = title.font()
            font.setStrikeOut(task.completed)
            title.setFont(font)
            text.addWidget(title)
            if task.notes:
                preview = task.notes.splitlines()[0]
                notes = QLabel(preview[:160] + ('…' if len(preview) > 160 else ''), objectName='muted')
                notes.setTextFormat(Qt.TextFormat.PlainText)
                notes.setWordWrap(True)
                text.addWidget(notes)
            if task.due_date:
                today = date.today()
                caption = ('Today' if task.due_date == today else 'Tomorrow'
                           if task.due_date == today + timedelta(days=1) else task.due_date.isoformat())
                if task.due_time:
                    caption += ' at ' + task.due_time.strftime('%H:%M')
                if self._overdue(task):
                    caption = 'Overdue · ' + caption
                text.addWidget(QLabel(caption, objectName='reminderOverdue' if self._overdue(task) else 'muted'))
            box.addLayout(text, 1)
            self.list.addItem(item)
            item.setSizeHint(row.sizeHint())
            self.list.setItemWidget(item, row)
            if task.id == selected:
                self.list.setCurrentItem(item)
        self.list.fit_rows()
        self.list.verticalScrollBar().setValue(scroll)
        self.empty.setText('No matching reminders.' if self.search.text() else
                           'All caught up.' if self.view == 'Today' else 'No reminders here yet.')
        self.empty.setVisible(not rows)

    @staticmethod
    def _overdue(task):
        if task.completed or task.due_date is None:
            return False
        now = datetime.now()
        return task.due_date < now.date() or (task.due_date == now.date()
            and task.due_time is not None and task.due_time < now.time())

    def _save(self, task):
        try:
            self.store.put(task)
        except (OSError, sqlite3.Error, ValueError) as error:
            QMessageBox.warning(self, 'Cannot save reminder', str(error))
            self.refresh()
            return False
        self.refresh()
        return True

    def edit(self, task=None):
        dialog = ReminderDialog(task, self)
        while dialog.exec() == QDialog.DialogCode.Accepted:
            if self._save(dialog.value()):
                break
        dialog.deleteLater()

    def _edit_current(self):
        if self.list.currentItem():
            self.edit(self.list.currentItem().data(Qt.ItemDataRole.UserRole))

    def _delete_current(self):
        if self.list.currentItem():
            self.delete(self.list.currentItem().data(Qt.ItemDataRole.UserRole))

    def delete(self, task):
        if QMessageBox.question(self, 'Delete reminder', f'Delete “{task.title}”?') != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.delete(task.id)
        except (OSError, sqlite3.Error, ValueError) as error:
            QMessageBox.warning(self, 'Cannot delete reminder', str(error))
        self.refresh()

    def _context_menu(self, position):
        item = self.list.itemAt(position)
        if item is None:
            return
        self.list.setCurrentItem(item)
        task = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction('Edit…', lambda: self.edit(task))
        menu.addAction('Mark incomplete' if task.completed else 'Complete',
                       lambda: self._save(replace(task, completed=not task.completed)))
        menu.addAction('Remove flag' if task.flagged else 'Flag',
                       lambda: self._save(replace(task, flagged=not task.flagged)))
        menu.addSeparator()
        menu.addAction('Delete', lambda: self.delete(task))
        menu.exec(self.list.viewport().mapToGlobal(position))
        menu.deleteLater()
