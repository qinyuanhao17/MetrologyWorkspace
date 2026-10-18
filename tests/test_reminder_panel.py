"""Home-screen reminders are saved separately from analysis tools."""
import os
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QDate, QPoint, QRect, QTimer, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDateEdit, QDialogButtonBox, QLabel, QLineEdit,
                            QListWidget, QMessageBox, QPushButton, QScrollArea, QTableView, QToolButton, QWidget)
from metrology_app.module_registry import ComponentRegistry, ComponentSpec
from metrology_app.reminders import Reminder, ReminderStore
from metrology_app.shell import MainWindow

APP = QApplication.instance() or QApplication([])


class ReminderPanelTests(unittest.TestCase):
    def test_empty_reminder_body_has_no_scrollbar_or_workspace_heading(self):
        from metrology_app.settings import apply_theme
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'reminders.sqlite3'
            shell = MainWindow(reminders_path=path)
            try:
                shell.show()
                for filtered in (False, True):
                    if filtered:
                        shell.reminders.store.put(Reminder('Review NOVA report'))
                        shell.reminders.refresh()
                        shell.reminders.search.setText('No matching task')
                    for theme in ('light', 'dark'):
                        apply_theme(shell, theme)
                        for size in ((1180, 820), (1000, 620)):
                            with self.subTest(filtered=filtered, theme=theme, size=size):
                                shell.resize(*size)
                                shell.shell_splitter.moveSplitter(220, 1)
                                APP.processEvents()
                                panel = shell.reminders
                                self.assertEqual(panel.list.count(), 0)
                                self.assertFalse(panel.list.verticalScrollBar().isVisible())
                                self.assertEqual(panel.list.verticalScrollBar().maximum(), 0)
                                self.assertFalse(any(label.text() == 'Workspace'
                                                     for label in shell.findChildren(QLabel)))
                                viewport = shell.shell_scroll.viewport()
                                for widget in (panel.search, panel.completed, panel.add_button):
                                    rect = QRect(widget.mapTo(viewport, QPoint()), widget.size())
                                    self.assertTrue(viewport.rect().contains(rect))
                                for scroll in shell.findChildren(QScrollArea):
                                    content = scroll.widget()
                                    if content is not None and (content is panel or content.isAncestorOf(panel)):
                                        self.assertEqual(scroll.verticalScrollBar().maximum(), 0)
            finally:
                shell.close()
                shell.deleteLater()
                APP.processEvents()

    def test_new_reminder_uses_blue_in_both_themes(self):
        from metrology_app.settings import apply_theme
        with TemporaryDirectory() as folder:
            shell = MainWindow(reminders_path=Path(folder) / 'reminders.sqlite3')
            try:
                shell.show()
                for theme in ('light', 'dark'):
                    apply_theme(shell, theme)
                    APP.processEvents()
                    button = shell.findChild(QToolButton, 'newReminder')
                    button.clearFocus()
                    image = button.grab().toImage()
                    scale = image.devicePixelRatio()
                    color = image.pixelColor(round(8*scale), round(8*scale))
                    self.assertGreater(color.blue(), color.red()+60, theme)
            finally:
                shell.close()
                shell.deleteLater()
                APP.processEvents()

    def test_only_reminder_body_scrolls_above_an_expanded_log(self):
        from metrology_app.settings import apply_theme
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'reminders.sqlite3'
            store = ReminderStore(path)
            for index in range(30):
                store.put(Reminder(f'{index+1:02} Review NOVA measurements and all exported Wafer captions'))
            before = store.items()
            shell = MainWindow(reminders_path=path)
            try:
                shell.show()
                APP.processEvents()
                for theme in ('light', 'dark'):
                    apply_theme(shell, theme)
                    for size in ((1180, 820), (1000, 620)):
                        shell.resize(*size)
                        for height in (500, 340, 220):
                            with self.subTest(size=size, upper_height=height, theme=theme):
                                shell.shell_splitter.moveSplitter(height, 1)
                                APP.processEvents()
                                divider = shell.shell_splitter.sizes()
                                viewport = shell.shell_scroll.viewport()
                                area = QRect(viewport.mapTo(shell, QPoint()), viewport.size())
                                log = shell.log_output.parentWidget()
                                self.assertLessEqual(area.bottom(), log.mapTo(shell, QPoint()).y())
                                panel = shell.reminders
                                controls = (shell.findChild(QLabel, 'remindersTitle'), panel.search,
                                            panel.completed, panel.add_button, *panel.buttons.values())
                                before_scroll = [QRect(widget.mapTo(shell, QPoint()), widget.size())
                                                 for widget in controls]
                                for rect in before_scroll:
                                    self.assertTrue(area.contains(rect), 'Reminder controls must stay above Log')
                                tasks = shell.reminders.list
                                tasks.scrollToBottom()
                                APP.processEvents()
                                for scroll in shell.findChildren(QScrollArea):
                                    content = scroll.widget()
                                    if content is not None and (content is panel or content.isAncestorOf(panel)):
                                        self.assertEqual(scroll.verticalScrollBar().maximum(), 0,
                                                         'Only the reminder body should scroll, not the card')
                                last = tasks.visualItemRect(tasks.item(tasks.count()-1))
                                # Long reminders can exceed the viewport height;
                                # pixel scrolling must still expose their final line.
                                self.assertTrue(tasks.viewport().rect().contains(last.bottomLeft()),
                                                'The end of the last reminder must be readable inside the list')
                                self.assertTrue(tasks.verticalScrollBar().isVisible())
                                self.assertEqual([QRect(widget.mapTo(shell, QPoint()), widget.size())
                                                  for widget in controls], before_scroll)
                                self.assertEqual(shell.shell_splitter.sizes(), divider)
                self.assertEqual(store.items(), before)
            finally:
                shell.close()
                shell.deleteLater()
                APP.processEvents()

    def test_calendar_shows_complete_english_week_and_saves_the_chosen_date(self):
        from metrology_app.settings import apply_theme
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'reminders.sqlite3'
            ReminderStore(path).put(Reminder('Submit revised paper', due_date=date(2026, 10, 20)))
            shell = MainWindow(reminders_path=path)
            try:
                shell.show()
                for theme in ('light', 'dark'):
                    apply_theme(shell, theme)
                    errors = []
                    def choose_date():
                        dialog = APP.activeModalWidget()
                        try:
                            field = dialog.findChild(QDateEdit, 'reminderDateInput')
                            field.setDate(QDate(2026, 10, 20))
                            QTest.mouseClick(field, Qt.MouseButton.LeftButton,
                                pos=QPoint(field.width()-12, field.height()//2))
                            APP.processEvents()
                            calendar = field.calendarWidget()
                            self.assertTrue(calendar.isVisible())
                            self.assertGreaterEqual(field.height(), 32)
                            self.assertGreaterEqual(calendar.width(), 320)
                            self.assertGreaterEqual(calendar.height(), 280)
                            self.assertEqual(calendar.firstDayOfWeek(), Qt.DayOfWeek.Monday)
                            self.assertEqual(calendar.locale().monthName(10), 'October')
                            calendar.findChild(QToolButton, 'qt_calendar_nextmonth').click()
                            self.assertEqual((calendar.yearShown(), calendar.monthShown()), (2026, 11))
                            view = calendar.findChild(QTableView)
                            model = view.model()
                            target = next(model.index(row,col) for row in range(1, model.rowCount())
                                          for col in range(model.columnCount())
                                          if str(model.index(row,col).data()) == '21')
                            QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                                             pos=view.visualRect(target).center())
                            self.assertEqual(field.date(), QDate(2026, 11, 21))
                            self.assertFalse(calendar.isVisible())
                            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
                        except Exception as error:
                            errors.append(error)
                            if dialog:
                                dialog.reject()
                    QTimer.singleShot(0, choose_date)
                    shell.reminders.edit(shell.reminders.list.item(0).data(Qt.ItemDataRole.UserRole))
                    self.assertEqual(errors, [], theme)
            finally:
                shell.close()
                shell.deleteLater()
                APP.processEvents()
            reopened = MainWindow(reminders_path=path)
            try:
                task = reopened.reminders.list.item(0).data(Qt.ItemDataRole.UserRole)
                self.assertEqual(task.due_date, date(2026, 11, 21))
            finally:
                reopened.close()
                reopened.deleteLater()
                APP.processEvents()

    def test_reminder_symbols_stay_centered_while_pressed_in_both_themes(self):
        from metrology_app.settings import apply_theme
        from metrology_app.appearance import configure_fonts, set_theme_palette
        old_font, old_palette = APP.font(), APP.palette()
        configure_fonts(APP)
        try:
            with TemporaryDirectory() as folder:
                shell = MainWindow(reminders_path=Path(folder) / 'reminders.sqlite3')
                shell.reminders.store.put(Reminder('Review NOVA report', completed=True))
                shell.reminders.set_view('Completed')
                shell.show()
                try:
                    for theme in ('light', 'dark'):
                        set_theme_palette(theme)
                        apply_theme(shell, theme)
                        APP.processEvents()
                        check = shell.findChild(QToolButton, 'reminderCheck')
                        for button in (shell.findChild(QToolButton, 'newReminder'), check):
                            with self.subTest(theme=theme, control=button.objectName()):
                                boxes = []
                                for down in (False, True):
                                    button.setDown(down)
                                    image = button.grab().toImage()
                                    scale = image.devicePixelRatio()
                                    points = [(x, y) for y in range(round(6*scale), image.height()-round(6*scale))
                                              for x in range(round(6*scale), image.width()-round(6*scale))
                                              if min(image.pixelColor(x,y).getRgb()[:3]) > 240]
                                    self.assertTrue(points)
                                    boxes.append((min(x for x,y in points), min(y for x,y in points),
                                                  max(x for x,y in points), max(y for x,y in points)))
                                self.assertEqual(boxes[0], boxes[1], 'Pressing must not shift the symbol')
                                x0, y0, x1, y1 = boxes[0]
                                self.assertLessEqual(abs((x0+x1)/2 - (image.width()-1)/2), scale)
                                self.assertLessEqual(abs((y0+y1)/2 - (image.height()-1)/2), scale)
                                button.setDown(False)
                finally:
                    shell.close()
                    shell.deleteLater()
                    APP.processEvents()
        finally:
            APP.setFont(old_font)
            APP.setPalette(old_palette)

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
