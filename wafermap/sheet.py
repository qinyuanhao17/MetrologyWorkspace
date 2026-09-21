"""Small spreadsheet model: editable cells, range clipboard and undo/redo."""
import csv
from io import StringIO

import pandas as pd
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QKeySequence, QUndoCommand, QUndoStack
from PyQt6.QtWidgets import QApplication, QTableView

from .settings import get_settings


HEADER_COLOURS = {"dark": ("#201629", "#d6b9f5"), "light": ("#f0f0f2", "#18181b")}


def header_colours():
    return HEADER_COLOURS.get(get_settings()["theme"], HEADER_COLOURS["dark"])


def column_letter(index):
    result = ""
    while index >= 0:
        result = chr(65 + index % 26) + result
        index = index // 26 - 1
    return result


def clipboard_rows(text):
    if not text:
        return []
    try:
        delimiter = "\t" if "\t" in text else csv.Sniffer().sniff(text, delimiters=",;").delimiter
    except csv.Error:
        delimiter = "\t"
    return list(csv.reader(StringIO(text), delimiter=delimiter))


class CellEdit(QUndoCommand):
    def __init__(self, model, changes):
        super().__init__("Edit cells")
        self.model = model
        self.before = {cell: model.cells.get(cell, "") for cell in changes}
        self.after = changes

    def redo(self):
        self.model.apply(self.after)

    def undo(self):
        self.model.apply(self.before)


class SheetModel(QAbstractTableModel):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.cells = {}
        self.height, self.width = 100, 26
        self.undo = QUndoStack(self)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self.height

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self.width

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            return column_letter(section) if orientation == Qt.Orientation.Horizontal else str(section + 1)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        value = self.cells.get((index.row(), index.column()), "")
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole, Qt.ItemDataRole.ToolTipRole):
            return value
        if index.row() == 0:
            background, foreground = header_colours()
            if role == Qt.ItemDataRole.BackgroundRole:
                return QColor(background)
            if role == Qt.ItemDataRole.ForegroundRole:
                return QColor(foreground)
            if role == Qt.ItemDataRole.FontRole:
                font = QFont()
                font.setWeight(QFont.Weight.DemiBold)
                return font

    def flags(self, index):
        return super().flags(index) | Qt.ItemFlag.ItemIsEditable

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        self.edit({(index.row(), index.column()): str(value)})
        return True

    def edit(self, changes):
        changes = {key: value for key, value in changes.items() if self.cells.get(key, "") != value}
        if changes:
            self.undo.push(CellEdit(self, changes))

    def apply(self, changes):
        rows = max(self.height, max(r for r, _ in changes) + 21)
        cols = max(self.width, max(c for _, c in changes) + 4)
        if rows > self.height:
            self.beginInsertRows(QModelIndex(), self.height, rows - 1)
            self.height = rows
            self.endInsertRows()
        if cols > self.width:
            self.beginInsertColumns(QModelIndex(), self.width, cols - 1)
            self.width = cols
            self.endInsertColumns()
        for key, value in changes.items():
            if value:
                self.cells[key] = value
            else:
                self.cells.pop(key, None)
        first = self.index(min(r for r, _ in changes), min(c for _, c in changes))
        last = self.index(max(r for r, _ in changes), max(c for _, c in changes))
        self.dataChanged.emit(first, last)
        self.changed.emit()

    def load(self, frame):
        matrix = [list(frame.columns)] + frame.fillna("").astype(str).values.tolist() if len(frame.columns) else []
        self.load_matrix(matrix)

    def load_matrix(self, matrix):
        """Replace every cell with a rectangular clipboard matrix."""
        matrix = [list(row) for row in matrix]
        if matrix:
            width = max(len(row) for row in matrix)
            matrix = [row + [""] * (width - len(row)) for row in matrix]
        width = max((len(row) for row in matrix), default=0)
        self.beginResetModel()
        self.cells = {(r, c): str(v) for r, row in enumerate(matrix) for c, v in enumerate(row) if str(v)}
        self.height = max(100, len(matrix) + 20)
        self.width = max(26, width + 3)
        self.endResetModel()
        self.undo.clear()
        self.undo.setClean()
        self.changed.emit()

    def frame(self):
        if not self.cells:
            return pd.DataFrame()
        columns = max(c for _, c in self.cells) + 1
        rows = max(r for r, _ in self.cells) + 1
        headers = [self.cells.get((0, c), "").strip() or f"Column {column_letter(c)}" for c in range(columns)]
        if len(set(headers)) != len(headers):
            raise ValueError("Duplicate column names in row 1. Rename them to continue.")
        matrix = [[self.cells.get((r, c), "") for c in range(columns)] for r in range(1, rows)]
        return pd.DataFrame([row for row in matrix if any(v.strip() for v in row)], columns=headers)


class SheetView(QTableView):
    table_pasted = pyqtSignal()

    def __init__(self, model):
        super().__init__()
        self.setModel(model)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(self.SelectionMode.ContiguousSelection)
        self.setHorizontalScrollMode(self.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(self.ScrollMode.ScrollPerPixel)
        self.setWordWrap(False)
        self.verticalHeader().setDefaultSectionSize(29)
        self.horizontalHeader().setDefaultSectionSize(118)
        self.horizontalHeader().setMinimumSectionSize(48)
        self.verticalHeader().setMinimumWidth(44)

    def paste(self):
        model = self.model()
        was_empty = not model.cells
        matrix = clipboard_rows(QApplication.clipboard().text())
        index = self.currentIndex()
        row, column = (index.row(), index.column()) if index.isValid() else (0, 0)
        replaces_table = (row, column) == (0, 0) and len(matrix) > 1
        if replaces_table:
            # Pasting a header row plus data at A1 replaces the whole table, so no
            # stale cells from a previously pasted file survive.
            model.load_matrix(matrix)
        else:
            model.edit({(row + r, column + c): v for r, line in enumerate(matrix) for c, v in enumerate(line)})
        if matrix and (was_empty or replaces_table):
            # The first paste into an empty sheet replaces the table, so the
            # window should re-run automatic wafer/parameter identification.
            self.table_pasted.emit()

    def copy(self):
        indexes = self.selectedIndexes()
        if not indexes:
            return
        rows = range(min(i.row() for i in indexes), max(i.row() for i in indexes) + 1)
        columns = range(min(i.column() for i in indexes), max(i.column() for i in indexes) + 1)
        output = StringIO()
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        for row in rows:
            writer.writerow([self.model().cells.get((row, c), "") for c in columns])
        QApplication.clipboard().setText(output.getvalue())

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste()
        elif event.matches(QKeySequence.StandardKey.Copy):
            self.copy()
        elif event.matches(QKeySequence.StandardKey.Undo):
            self.model().undo.undo()
        elif event.matches(QKeySequence.StandardKey.Redo):
            self.model().undo.redo()
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.model().edit({(i.row(), i.column()): "" for i in self.selectedIndexes()})
        else:
            super().keyPressEvent(event)
