"""Visible menu controls distinguish exclusive choices from copy toggles."""
import unittest

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QActionGroup, QColor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMenu

from metrology_app.settings import apply_theme

APP = QApplication.instance() or QApplication([])


class MenuControlTests(unittest.TestCase):
    def test_menu_checkboxes_are_square_and_radios_round_on_the_right_in_both_themes(self):
        for theme, fill in (("light", "#2563eb"), ("dark", "#8b5ab7")):
            with self.subTest(theme=theme):
                menu = QMenu()
                apply_theme(menu, theme)
                copy = menu.addAction("Copy from WKB")
                copy.setCheckable(True)
                copy.setChecked(True)
                group = QActionGroup(menu)
                match = menu.addAction("Match Workbook selection")
                full = menu.addAction("Full data (before selection)")
                for action in (match, full):
                    action.setCheckable(True)
                    group.addAction(action)
                full.setChecked(True)
                try:
                    menu.popup(QPoint(20, 20))
                    APP.processEvents()
                    captured = menu.grab().toImage()
                    scale = captured.devicePixelRatio()
                    corners = []
                    for action in (copy, full):
                        row = menu.actionGeometry(action)
                        colored = [(x, y) for y in range(int(row.top() * scale), int(row.bottom() * scale))
                                   for x in range(captured.width())
                                   if captured.pixelColor(x, y) == QColor(fill)]
                        self.assertTrue(colored)
                        left = min(x for x, y in colored)
                        top = min(y for x, y in colored)
                        self.assertGreater(left, captured.width() * .8)
                        corners.append(captured.pixelColor(left + 1, top + 1) == QColor(fill))
                    self.assertEqual(corners, [True, False], "Checkbox corner is filled; round radio corner is not")
                    # Styling does not change full-row pointer or native keyboard
                    # activation, and a radio choice cannot turn both options on.
                    QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(match).center())
                    self.assertTrue(match.isChecked())
                    self.assertFalse(full.isChecked())
                    menu.popup(QPoint(20, 20))
                    APP.processEvents()
                    menu.setActiveAction(copy)
                    QTest.keyClick(menu, Qt.Key.Key_Return)
                    self.assertFalse(copy.isChecked())
                finally:
                    menu.hide()
                    menu.deleteLater()
                    APP.processEvents()


if __name__ == "__main__":
    unittest.main()
