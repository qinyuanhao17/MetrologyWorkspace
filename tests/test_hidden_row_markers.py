"""Collapsed source rows are visible without adding editable placeholder rows."""
import unittest
from unittest.mock import patch

import pandas as pd
from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QColor, QHelpEvent
from PyQt6.QtWidgets import QApplication, QToolTip

from metrology_app import settings
from metrology_app.match_group_ui import ProjectedSheetModel
from metrology_app.sheet import SheetModel, SheetView

APP = QApplication.instance() or QApplication([])


class HiddenRowMarkerTests(unittest.TestCase):
    def sheet(self):
        source = SheetModel()
        source.load(pd.DataFrame({"CD": [f"{row}.000" for row in range(1, 7)],
                                  "Depth": ["1.2300"] * 6}))
        proxy = ProjectedSheetModel(source)
        proxy.set_rows([0, 2, 3, 5])
        view = SheetView(proxy)
        view.resize(520, 240)
        self.addCleanup(source.deleteLater)
        self.addCleanup(proxy.deleteLater)
        self.addCleanup(view.deleteLater)
        self.addCleanup(view.close)
        return source, proxy, view

    def test_gaps_report_original_row_numbers_and_counts_without_adding_rows(self):
        source, proxy, _view = self.sheet()
        before = source.document_frame()
        self.assertIsNone(proxy.hidden_rows_before(1))
        self.assertEqual(proxy.hidden_rows_before(2), (3, 3))
        self.assertIsNone(proxy.hidden_rows_before(3))
        self.assertEqual(proxy.hidden_rows_before(4), (6, 6))
        self.assertEqual([proxy.headerData(row, Qt.Orientation.Vertical) for row in range(5)],
                         ["1", "2", "4", "5", "7"])
        tip = proxy.headerData(2, Qt.Orientation.Vertical, Qt.ItemDataRole.ToolTipRole)
        self.assertIn("1 hidden row", tip)
        self.assertIn("original row 3", tip)
        self.assertEqual(proxy.rowCount(), 5)
        pd.testing.assert_frame_equal(source.document_frame(), before)

    def test_leading_and_reversed_gaps_are_truthful_and_sort_alone_is_not_hidden_data(self):
        _source, proxy, _view = self.sheet()
        proxy.set_rows([2, 3, 4, 5])
        self.assertEqual(proxy.hidden_rows_before(1), (2, 3))
        self.assertIn("2 hidden rows", proxy.headerData(1, Qt.Orientation.Vertical, Qt.ItemDataRole.ToolTipRole))
        proxy.set_rows([5, 3, 2, 0])
        self.assertIsNone(proxy.hidden_rows_before(1))  # earlier visible records are not hidden
        self.assertEqual(proxy.hidden_rows_before(2), (6, 6))
        self.assertEqual(proxy.hidden_rows_before(4), (3, 3))
        proxy.set_rows([2, 0, 5, 3, 1, 4])
        self.assertTrue(all(proxy.hidden_rows_before(row) is None for row in range(proxy.rowCount())))
        proxy.set_rows(None)
        self.assertIsNone(proxy.hidden_rows_before(2))

    def test_boundary_and_header_marks_render_in_both_themes_and_unhide_removes_them(self):
        source, proxy, view = self.sheet()
        for theme, colour in (("light", "#b87200"), ("dark", "#e6b54a")):
            with self.subTest(theme=theme), patch.dict(settings._current, {"theme": theme}):
                settings.apply_theme(view, theme)
                view.setModel(proxy)
                view.show()
                APP.processEvents()
                y = view.rowViewportPosition(2)
                image = view.viewport().grab().toImage()
                target = QColor(colour).rgb()
                count = sum(image.pixel(x, dy) == target for dy in range(y, y + 2)
                            for x in range(5, image.width() - 5))
                self.assertGreater(count, 100, "The hidden-row separator must be visible across the table")
                header = view.verticalHeader().viewport().grab().toImage()
                self.assertTrue(any(header.pixel(x, dy) == target
                                    for dy in range(y, y + 9) for x in range(header.width())))
                view.setModel(source)
                APP.processEvents()
                plain = view.viewport().grab().toImage()
                self.assertFalse(any(plain.pixel(x, dy) == target for dy in range(y, y + 2)
                                     for x in range(5, plain.width() - 5)))

    def test_boundary_hover_explains_the_gap_and_paste_still_targets_visible_source_rows(self):
        source, proxy, view = self.sheet()
        view.show()
        APP.processEvents()
        point = QPoint(90, view.rowViewportPosition(2) + 1)
        event = QHelpEvent(QEvent.Type.ToolTip, point, view.viewport().mapToGlobal(point))
        with patch.object(QToolTip, "showText") as show:
            APP.sendEvent(view.viewport(), event)
            self.assertTrue(show.called)
            self.assertIn("1 hidden row", show.call_args.args[1])
        before = source.document_frame()
        APP.clipboard().setText("91.000\n92.000")
        view.setCurrentIndex(proxy.index(1, 0))
        view.paste()
        self.assertEqual(source.document_frame()["CD"].tolist(),
                         ["91.000", "2.000", "92.000", "4.000", "5.000", "6.000"])
        source.undo.undo()
        pd.testing.assert_frame_equal(source.document_frame(), before)
