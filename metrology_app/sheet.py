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


class TableReplace(QUndoCommand):
    """Undoable replacement used when a user pastes a complete table at A1."""

    def __init__(self, model, matrix):
        super().__init__("Replace table")
        self.model = model
        self.before = model.snapshot()
        self.after = model.state_from_matrix(matrix)

    def redo(self):
        self.model.restore(self.after)

    def undo(self):
        self.model.restore(self.before)


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
        self.restore(self.state_from_matrix(matrix), emit_changed=False)
        self.undo.clear()
        self.undo.setClean()
        self.changed.emit()

    def replace_matrix(self, matrix):
        """Replace the table as one user-visible, undoable operation."""
        command = TableReplace(self, matrix)
        if command.before != command.after:
            self.undo.push(command)

    def snapshot(self):
        return dict(self.cells), self.height, self.width

    @staticmethod
    def state_from_matrix(matrix):
        matrix = [list(row) for row in matrix]
        if matrix:
            width = max(len(row) for row in matrix)
            matrix = [row + [""] * (width - len(row)) for row in matrix]
        width = max((len(row) for row in matrix), default=0)
        cells = {
            (r, c): str(value)
            for r, row in enumerate(matrix)
            for c, value in enumerate(row)
            if str(value)
        }
        return cells, max(100, len(matrix) + 20), max(26, width + 3)

    def restore(self, state, emit_changed=True):
        cells, height, width = state
        self.beginResetModel()
        self.cells = dict(cells)
        self.height = height
        self.width = width
        self.endResetModel()
        if emit_changed:
            self.changed.emit()

    def frame(self):
        if not self.cells:
            return pd.DataFrame()
        columns = max(c for _, c in self.cells) + 1
        rows = max(r for r, _ in self.cells) + 1
        headers = self.headers(columns)
        if len(set(headers)) != len(headers):
            raise ValueError("Duplicate column names in row 1. Rename them to continue.")
        matrix = [[self.cells.get((r, c), "") for c in range(columns)] for r in range(1, rows)]
        return pd.DataFrame([row for row in matrix if any(v.strip() for v in row)], columns=headers)

    def headers(self, columns=None):
        """Row-1 header text, falling back to the column letter when it is blank."""
        if columns is None:
            columns = max((c for _, c in self.cells), default=-1) + 1
        return [self.cells.get((0, c), "").strip() or f"Column {column_letter(c)}"
                for c in range(columns)]

    def duplicate_header_count(self):
        """How many row-1 names repeat (0 when every header is unique)."""
        headers = self.headers()
        return len(headers) - len(set(headers))

    def rename_duplicate_headers(self):
        """Number repeated row-1 headers by column order and return the renames.

        The first column of each name keeps it; later repeats become ``name_2``,
        ``name_3`` … (skipping any suffix already used elsewhere), so the table
        can be read again without touching any other cell. Renames go through the
        undo stack.
        """
        headers = self.headers()
        used = set(headers)
        seen, changes = {}, {}
        for column, name in enumerate(headers):
            seen[name] = seen.get(name, 0) + 1
            if seen[name] == 1:
                continue
            suffix = seen[name]
            candidate = f"{name}_{suffix}"
            while candidate in used:
                suffix += 1
                candidate = f"{name}_{suffix}"
            used.add(candidate)
            changes[(0, column)] = candidate
        if changes:
            self.edit(changes)
        return {column: (headers[column], value) for (_, column), value in changes.items()}


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
            model.replace_matrix(matrix)
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
